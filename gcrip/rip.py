"""The one-shot pipeline: disc image in, glTF models + PNG textures + report out.

out/<GameID>/<disc path>/<model>.gltf   (+ .bin, <model>_tex/*.png, <model>_thumb.png)
out/<GameID>/<disc path>/<texture>.png  standalone BTI/TPL textures
out/<GameID>/report.html
out/<GameID>/disc_manifest.json
"""

from __future__ import annotations

import contextlib
import html
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gcrip.disc import tgc
from gcrip.disc.image import DiscImage
from gcrip.export import gltf, png, thumb
from gcrip.formats import bti, j3d, rarc, tpl, yay0, yaz0
from gcrip.formats import j3d_anim as ja
from gcrip.manifest import Manifest, ManifestEntry, build_manifest


@dataclass
class ModelResult:
    path: str  # manifest path
    out_rel: str | None  # relative path of the .gltf under the game dir (None if failed/dup)
    sha1: str | None
    triangles: int = 0
    vertices: int = 0
    joints: int = 0
    textures: int = 0
    materials: int = 0
    skinned: bool = False
    joint_names: list[str] = field(default_factory=list)
    texture_files: list[str] = field(default_factory=list)
    thumb: str | None = None
    duplicate_of: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    variants: dict[str, str] = field(default_factory=dict)
    animations: list[str] = field(default_factory=list)
    anim_sources: list[str] = field(default_factory=list)  # archives the clips came from
    expressions: list[str] = field(default_factory=list)
    std_bones: dict[str, str] = field(default_factory=dict)
    blend_rel: str | None = None  # set by `gcrip blend`
    glb_rel: str | None = None  # set by `gcrip pack`
    seconds: float = 0.0


@dataclass
class TextureResult:
    path: str
    out_rel: str | None
    fmt: str = ""
    width: int = 0
    height: int = 0
    error: str | None = None


def dump_dir_name(game_id: str, disc_number: int = 0) -> str:
    """Output folder for a disc: bare game id, plus `_disc<N>` for disc 2 and later
    (`disc_number` is the raw header byte, 0-based)."""
    return game_id if disc_number < 1 else f"{game_id}_disc{disc_number + 1}"


@dataclass
class RipResult:
    game_id: str
    title: str
    out_dir: Path
    models: list[ModelResult] = field(default_factory=list)
    textures: list[TextureResult] = field(default_factory=list)
    seconds: float = 0.0


class _Source:
    """Fetches file bytes by manifest path, caching decompressed containers."""

    def __init__(self, image: DiscImage, manifest: Manifest):
        self.image = image
        self.by_path = {f.path: f for f in manifest.files}
        self._cache: dict[str, bytes] = {}
        self._cache_order: list[str] = []

    def _payload(self, path: str) -> bytes:
        """Decompressed contents of a container (archive) by manifest path."""
        if path in self._cache:
            self._cache_order.remove(path)
            self._cache_order.append(path)
            return self._cache[path]
        raw = self.raw(path)
        if yaz0.is_yaz0(raw):
            raw = yaz0.decompress(raw)
        elif yay0.is_yay0(raw):
            raw = yay0.decompress(raw)
        self._cache[path] = raw
        self._cache_order.append(path)
        # nested archives (EA BIG-in-BIG, PAK) are revisited constantly while the manifest
        # is walked in order; keep a generous window of decompressed payloads around
        while len(self._cache_order) > 24:
            old = self._cache_order.pop(0)
            self._cache.pop(old, None)
        return raw

    def raw(self, path: str) -> bytes:
        e = self.by_path[path]
        if e.container is None:
            return self.image.read(e.disc_offset or 0, e.size)
        parent = self._payload(e.container)
        if rarc.is_rarc(parent) or tgc.is_tgc(parent):
            return parent[e.offset : e.offset + e.size]
        # a container a format plugin expanded (PAK, BIG, ...): members are not slices
        return self._expanded(e.container, parent, want=path)[path]

    def _expanded(self, container: str, payload: bytes, want: str | None = None) -> dict[str, bytes]:
        """Members of a plugin container, keyed by full manifest path (cached).

        ``want`` is the member being fetched.  It matters because **this can disagree with the
        walk that built the manifest**: `manifest._walk_plugin_container` skips the fallback
        plugins for anything under a container an ordinary plugin opened, and nothing here knows
        about those roots, so the first plugin to claim at fetch time is not always the one that
        named the members.  When that happened the member simply was not in the dict and the
        model died with a bare `KeyError` on its own path - 502 of them across eight discs,
        Resident Evil, Rayman Arena and Burnout 2 among them.

        So a plugin whose expansion does not contain the member being asked for is not the
        plugin that produced it, and the search carries on.
        """
        cache = self.__dict__.setdefault("_plugin_cache", {})
        if container in cache and (want is None or want in cache[container]):
            cache[container] = cache.pop(container)  # LRU touch: parents stay hot
            return cache[container]
        from gcrip.plugins import container_plugins

        name = container.rsplit("/", 1)[-1]
        folder = container.rsplit("/", 1)[0] if "/" in container else ""

        def sibling(n: str) -> bytes | None:
            want_name = f"{folder}/{n}".lower() if folder else n.lower()
            for p in self.by_path:
                if p.lower() == want_name:
                    return self.get(p)
            return None

        members: dict[str, bytes] = {}
        for mod in container_plugins():
            try:
                if mod.is_container(name, payload[:64]):
                    if getattr(mod, "NEEDS_SIBLING", False):
                        entries = mod.expand_with(payload, name, sibling)
                    else:
                        entries = mod.expand(payload)
                    got = {f"{container}/{inner}": blob for inner, blob in entries}
                    # a plugin that claims and yields nothing must not shadow the next one
                    # that would - see the note in manifest._walk_plugin_container
                    if not got:
                        continue
                    if not members:
                        members = got
                    if want is None or want in got:
                        members = got
                        break
            except Exception:  # noqa: BLE001
                continue
        while len(cache) > 48:
            cache.pop(next(iter(cache)))
        cache[container] = members
        return members

    def get(self, path: str) -> bytes:
        """File contents, decompressed if the file itself is Yaz0/Yay0."""
        data = self.raw(path)
        if yaz0.is_yaz0(data):
            data = yaz0.decompress(data)
        elif yay0.is_yay0(data):
            data = yay0.decompress(data)
        return data


# characters Windows rejects in a path component, plus the control range
_BAD_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
# CON, PRN and friends are device names on Windows whatever the extension
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
    f"lpt{i}" for i in range(1, 10)
}


def _safe_component(part: str) -> str:
    """One path component, made safe to create on this filesystem.

    Members carry names that are not filenames.  EA's cinema assets keep the artist's own
    absolute path - ``d:/DJV2/assets/textures/final/gc`` - inside the member path, so joining it
    onto the output directory produced ``D:\\3d dump\\...\\d:\\DJV2\\...`` and Windows rejected
    the lot; NHL 2004 has names with raw control bytes in them.  Between them that failed
    thousands of models on ten discs, all with ``OSError: [WinError 123]``.

    Components that are already legal come back unchanged, so this does not churn existing
    output paths.
    """
    out = _BAD_PATH_CHARS.sub("_", part)
    out = out.rstrip(". ")  # Windows silently drops a trailing dot or space
    if out.split(".")[0].lower() in _RESERVED:
        out = "_" + out
    return out or "_"


#: Audio and video, which a geometry scanner can never get anything from however big they
#: are.  The fallback pass is time-budgeted per disc and spent biggest-first, on the theory
#: that the largest files hold the most models.  That is wrong on the many discs whose
#: largest files are a movie and an audio stream: Tiger Woods 2003 begins with a 100 MB
#: `Data/Movies/intro.ngc`, and the budget was gone long before the `.skg` that `gxscan`
#: does find display lists in.  Media is scanned last rather than skipped, so a mislabelled
#: file still gets its turn if the budget reaches it.
MEDIA_DIRS = frozenset(
    {"movie", "movies", "video", "videos", "stream", "streams", "audiostr", "audiostream",
     "audiostreams", "sound", "sounds", "audio", "music", "bgm", "voice", "voices", "speech",
     "fmv", "fmvs", "sfx", "song", "songs"}
)
MEDIA_EXTS = frozenset(
    {".thp", ".h4m", ".adp", ".dsp", ".ast", ".mth", ".bik", ".mpg", ".mp3", ".ogg",
     ".wav", ".aiff", ".brstm", ".afc", ".mus", ".sbk", ".ssm", ".aud", ".adx", ".csb",
     ".exa", ".sng", ".vag", ".xa", ".cmp", ".mpeg", ".m2v", ".sad", ".rsd", ".aif"}
)


def _claimed_by_container(path: str, head: bytes) -> bool:
    """True when a container plugin already walks this file, so its members are extracted
    through their own formats and scanning the whole blob again is duplicated work.

    Tiger Woods 2003 is the case that forced this: 273 of its files are EA ``SHOC`` ``.hog``
    course archives of 2-5 MB, every one claimed by ``plugins/shoc.py`` and every one also
    handed to the fallback scanner, where each costs up to ``BUDGET`` seconds and yields
    nothing - a full scan of one finds no display lists at all.  273 x 45s against a 900s
    per-disc budget means the scan never reaches the ``.skg``, which do hold geometry.

    Fallback containers do not count.  ``plugins/generic.py`` is registered as one and claims
    every file there is, so counting it would deprioritise the whole disc and change nothing.
    """
    from gcrip.plugins import container_plugins, is_fallback

    for mod in container_plugins():
        if is_fallback(mod):
            continue
        try:
            if mod.is_container(path, head):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _looks_like_media(path: str) -> bool:
    """True for audio/video by directory or extension - see :data:`MEDIA_DIRS`."""
    parts = [q for q in re.split(r"[\\/]", path.lower()) if q]
    if any(q in MEDIA_DIRS for q in parts[:-1]):
        return True
    return parts and any(parts[-1].endswith(e) for e in MEDIA_EXTS)


def _rel_out_path(entry_path: str) -> Path:
    """Manifest path -> output path (strip the leading 'files/')."""
    p = entry_path
    if p.startswith("files/"):
        p = p[len("files/") :]
    parts = [_safe_component(x) for x in p.replace("\\", "/").split("/") if x not in ("", ".", "..")]
    return Path(*parts) if parts else Path("_")


def _log(quiet: bool, msg: str) -> None:
    if not quiet:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


def rip(
    image_path: Path,
    out_root: Path,
    *,
    thumbnails: bool = True,
    dedupe: bool = True,
    textures: bool = True,
    quiet: bool = False,
    limit: int | None = None,
    path_filter: str | None = None,
    animations: bool = True,
    bone_names: str = "original",
    fps: float = 30.0,
    anim_map: dict[str, str] | None = None,
    max_anims: int | None = None,
    plugins: bool = True,
) -> RipResult:
    """anim_map: {animation archive stem: model archive stem} overrides for archives that
    hold only animations (e.g. {"LkAnm": "Link"}); otherwise the target is guessed."""
    t_start = time.monotonic()
    with DiscImage(image_path) as image:
        _log(quiet, f"[1/3] walking disc {image_path.name} ...")
        manifest = build_manifest(image, recurse=True, hash_files=True)
        game_id = manifest.game["id"]
        # Both discs of a 2-disc game share one game id; without the suffix the second
        # disc overwrites the first (and `verify` then compares disc 1 against disc 2's
        # manifest).  Disc 1 keeps the bare id so existing dumps stay where they are.
        game_dir = out_root / dump_dir_name(game_id, manifest.game.get("disc_number", 0))
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "disc_manifest.json").write_text(
            json.dumps(manifest.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        result = RipResult(game_id=game_id, title=manifest.game["title"], out_dir=game_dir)
        src = _Source(image, manifest)

        models = [f for f in manifest.files if f.kind == "model" and f.fmt in ("BMD", "BDL")]
        # Byte-identical models are exported once; make the copy that lives in its own
        # archive (Kolin.arc/kolin.bmd rather than Demo04_00.arc/demo04_kolin_...) win.
        models.sort(key=lambda f: (0 if _is_home(f) else 1, f.path))
        texs = [f for f in manifest.files if f.kind == "texture" and f.fmt in ("BTI", "TPL")]
        if path_filter:
            models = [m for m in models if path_filter in m.path]
            texs = [t for t in texs if path_filter in t.path]
        if limit:
            models = models[:limit]
            texs = texs[:limit]
        _log(quiet, f"[2/3] {len(models)} models, {len(texs)} standalone textures")

        anims = _AnimIndex(src, manifest, enabled=animations, anim_map=anim_map or {})
        seen_hash: dict[str, str] = {}
        exported: list[tuple[ManifestEntry, ModelResult, j3d.Model]] = []
        for i, e in enumerate(models):
            t0 = time.monotonic()
            r = ModelResult(path=e.path, out_rel=None, sha1=e.sha1_decompressed or e.sha1)
            result.models.append(r)
            rel = _rel_out_path(e.path)
            stem = rel.stem
            out_base = game_dir / rel.parent / stem
            if not quiet and (i % 25 == 0 or i == len(models) - 1):
                sys.stderr.write(f"\r  model {i + 1}/{len(models)}: {str(rel)[:70]:<70}")
                sys.stderr.flush()
            if dedupe and r.sha1 and r.sha1 in seen_hash:
                r.duplicate_of = seen_hash[r.sha1]
                continue
            try:
                data = src.get(e.path)
                if data[:3] != b"J3D":
                    r.error = "skipped: not a J3D file despite the extension"
                    continue
                model = j3d.parse(data, stem)
                clips, pats, sources = anims.for_model(e, model)
                st = gltf.export(
                    model,
                    out_base,
                    animations=_cap(clips, max_anims, r),
                    patterns=pats,
                    bone_names=bone_names,
                    fps=fps,
                )
                r.out_rel = str((rel.parent / f"{stem}.gltf").as_posix())
                _fill_result(r, st, model, rel, sources)
                if thumbnails:
                    r.thumb = _thumbnail(st, model, out_base, rel)
                if r.sha1:
                    seen_hash[r.sha1] = e.path
                exported.append((e, r, model))
            except Exception as ex:  # noqa: BLE001
                r.error = f"{type(ex).__name__}: {ex}"
                if not quiet:
                    sys.stderr.write(f"\n  ! {e.path}: {r.error}\n")
                    if "--debug" in sys.argv:
                        traceback.print_exc()
            r.seconds = time.monotonic() - t0
        if not quiet:
            sys.stderr.write("\n")

        # Archives that hold only animations (LkAnm.arc, AlAnm.arc, ...): attach their
        # clips to the model they most plausibly drive and re-export it in place.
        if animations:
            targets = anims.orphan_targets(exported)
            if targets and not quiet:
                _log(quiet, f"[2b/3] {len(targets)} models get animations from other archives")
            for (e, r, model), (clips, pats, sources) in targets:
                rel = _rel_out_path(e.path)
                out_base = game_dir / rel.parent / rel.stem
                try:
                    own_clips, own_pats, _ = anims.for_model(e, model)
                    st = gltf.export(
                        model,
                        out_base,
                        animations=_cap(own_clips + clips, max_anims, r),
                        patterns=own_pats + pats,
                        bone_names=bone_names,
                        fps=fps,
                    )
                    _fill_result(r, st, model, rel, r.anim_sources + sources)
                except Exception as ex:  # noqa: BLE001
                    r.warnings.append(f"cross-archive animations failed: {ex}")

        if plugins:
            _run_plugins(src, manifest, result, game_dir, quiet, thumbnails, limit, path_filter)

        if textures:
            _log(quiet, f"[3/3] {len(texs)} standalone textures")
            for e in texs:
                tr = TextureResult(path=e.path, out_rel=None)
                result.textures.append(tr)
                rel = _rel_out_path(e.path)
                try:
                    data = src.get(e.path)
                    if e.fmt == "TPL":
                        imgs = tpl.parse(data)
                        for k, t in enumerate(imgs):
                            suffix = "" if len(imgs) == 1 else f"_{k}"
                            out = game_dir / rel.parent / f"{rel.stem}{suffix}.png"
                            out.parent.mkdir(parents=True, exist_ok=True)
                            png.write_rgba(out, t.decode(0))
                            tr.fmt, tr.width, tr.height = t.fmt_name, t.width, t.height
                        tr.out_rel = str((rel.parent / f"{rel.stem}.png").as_posix())
                    else:
                        t = bti.parse(data, 0, rel.stem)
                        out = game_dir / rel.parent / f"{rel.stem}.png"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        png.write_rgba(out, t.decode(0))
                        tr.fmt, tr.width, tr.height = t.fmt_name, t.width, t.height
                        tr.out_rel = str((rel.parent / f"{rel.stem}.png").as_posix())
                except Exception as ex:  # noqa: BLE001
                    tr.error = f"{type(ex).__name__}: {ex}"

    result.seconds = time.monotonic() - t_start
    if path_filter or limit:
        _merge_previous(result, game_dir / "rip_results.json")
    write_report(result)
    (game_dir / "rip_results.json").write_text(
        json.dumps(
            {
                "game_id": result.game_id,
                "title": result.title,
                "seconds": result.seconds,
                "models": [m.__dict__ for m in result.models],
                "textures": [t.__dict__ for t in result.textures],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return result


def _run_plugins(src, manifest, result, game_dir, quiet, thumbnails, limit, path_filter):
    """Non-J3D model formats (gcrip.plugins): each recognised file -> one or more Scenes."""
    from gcrip.plugins import plugins_for
    from ripcore import gltf as core_gltf

    cands = []
    for e in manifest.files:
        if e.kind == "model" and e.fmt in ("BMD", "BDL"):
            continue
        if path_filter and path_filter not in e.path:
            continue
        try:
            head = src.get(e.path)[:64] if e.size <= 64 << 20 else b""
        except Exception:  # noqa: BLE001
            continue
        mods = plugins_for(e.path, head, e.size)
        if mods:
            cands.append((e, mods, _claimed_by_container(e.path, head)))
    if not cands:
        return
    if limit:
        cands = cands[:limit]
    # real formats in disc order, then fallback-only files biggest first - but media and
    # archives a container plugin already walks go last whatever their size, so the per-disc
    # scan budget is not eaten by movies, audio, or blobs whose members are handled anyway
    from gcrip.plugins import is_fallback

    real = [c for c in cands if not all(is_fallback(m) for m in c[1])]
    fb = sorted(
        (c for c in cands if all(is_fallback(m) for m in c[1])),
        key=lambda c: (_looks_like_media(c[0].path), c[2], -c[0].size),
    )
    cands = [(e, mods) for e, mods, _ in real + fb]
    for mod in {m for _, mods in cands for m in mods}:
        begin = getattr(mod, "begin_disc", None)
        if begin:
            begin()
    _log(quiet, f"[2c/3] {len(cands)} files in plugin formats ({len(fb)} fallback)")
    seen_hash: dict[str, str] = {}
    for i, (e, mods) in enumerate(cands):
        if not quiet and (i % 10 == 0 or i == len(cands) - 1):
            sys.stderr.write(f"\r  plugin {i + 1}/{len(cands)}: {e.path[:70]:<70}")
            sys.stderr.flush()
        rel = _rel_out_path(e.path)
        sha = e.sha1_decompressed or e.sha1
        for mod in mods:
            t0 = time.monotonic()
            name = getattr(mod, "NAME", mod.__name__)
            r = ModelResult(path=e.path, out_rel=None, sha1=sha)
            r.warnings.append(f"format: {name}")
            result.models.append(r)
            if sha and (sha, name) in seen_hash:
                r.duplicate_of = seen_hash[(sha, name)]
                continue
            try:
                scenes = mod.extract(src.get(e.path), e.path, src)
            except Exception as ex:  # noqa: BLE001
                r.error = f"{name}: {type(ex).__name__}: {ex}"
                if not quiet:
                    sys.stderr.write(f"\n  ! {e.path}: {r.error}\n")
                    if "--debug" in sys.argv:
                        traceback.print_exc()
                r.seconds = time.monotonic() - t0
                continue
            if not scenes:
                result.models.remove(r)  # not this plugin's file after all: no record
                continue
            for k, scene in enumerate(scenes):
                rk = r if k == 0 else ModelResult(path=f"{e.path}#{k}", out_rel=None, sha1=None)
                if k:
                    rk.warnings.append(f"format: {name}")
                    result.models.append(rk)
                stem = rel.stem if len(scenes) == 1 else f"{rel.stem}#{k}"
                if scene.name and len(scenes) > 1:
                    stem = f"{rel.stem}#{_safe_stem(scene.name)}"
                out_base = game_dir / rel.parent / stem
                try:
                    st = core_gltf.export(scene, out_base)
                    rk.out_rel = str((rel.parent / f"{stem}.gltf").as_posix())
                    rk.triangles, rk.vertices, rk.joints = st.triangles, st.vertices, st.joints
                    rk.textures, rk.materials = st.textures, st.materials
                    rk.skinned = st.joints > 1
                    rk.joint_names = [j.name for j in scene.joints]
                    rk.texture_files = st.texture_files
                    rk.animations = st.clip_names
                    rk.warnings += st.warnings
                    if thumbnails:
                        th = core_gltf.thumbnail(st, out_base)
                        if th:
                            rk.thumb = str((rel.parent / th.name).as_posix())
                except Exception as ex:  # noqa: BLE001
                    rk.error = f"{name} export: {type(ex).__name__}: {ex}"
                rk.seconds = time.monotonic() - t0
            if sha and r.out_rel:
                seen_hash[(sha, name)] = e.path
    if not quiet:
        sys.stderr.write("\n")


def _safe_stem(name: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")[:60] or "model"


def _cap(clips: list, max_anims: int | None, r: ModelResult) -> list:
    if max_anims is not None and len(clips) > max_anims:
        r.warnings = [w for w in r.warnings if not w.startswith("--max-anims")]
        r.warnings.append(f"--max-anims: {len(clips) - max_anims} of {len(clips)} clips dropped")
        return clips[:max_anims]
    return clips


def _fill_result(r: ModelResult, st: gltf.ExportStats, model, rel: Path, sources) -> None:
    r.triangles, r.vertices, r.joints = st.triangles, st.vertices, st.joints
    r.textures, r.materials, r.skinned = st.textures, st.materials, st.skinned
    r.joint_names = [j.name for j in model.joints]
    r.texture_files = [str((rel.parent / f).as_posix()) for f in st.texture_files]
    r.warnings = [w for w in r.warnings if w.startswith("--max-anims")] + st.warnings
    r.variants = st.variants
    r.animations = st.animations
    r.anim_sources = sorted(set(sources))
    r.expressions = st.expressions
    r.std_bones = st.std_bones


def _is_home(f: ManifestEntry) -> bool:
    """True when the model file is named after its archive (kolin.bmd in Kolin.arc)."""
    if not f.container:
        return True
    stem = _arc_stem(f.container).lower()
    name = Path(f.path).stem.lower()
    return bool(stem) and (name.startswith(stem) or stem.startswith(name))


def _arc_stem(path: str | None) -> str:
    """'files/res/Object/LkAnm.arc' -> 'LkAnm'."""
    if not path:
        return ""
    return Path(path).name.split(".")[0]


class _AnimIndex:
    """Finds the BCK/BTP clips that belong to a model.

    Same archive: BCKs whose joint count matches, BTPs whose material names all
    exist in the model. Animation-only archives are resolved after all models are
    exported (see orphan_targets).
    """

    def __init__(self, src: _Source, manifest: Manifest, *, enabled: bool, anim_map: dict):
        self.src = src
        self.enabled = enabled
        self.anim_map = anim_map
        self.by_container: dict[str, list[ManifestEntry]] = {}
        self.model_containers: set[str] = set()
        self._cache: dict[str, ja.Bck | ja.Btp | None] = {}
        # sha1 -> every archive holding a byte-identical copy of that model. A deduped
        # model still "lives" in all of them for animation matching (Kolin.arc's clips
        # belong to kolin.bmd even if the exported copy came from a Demo archive).
        self.homes: dict[str, set[str]] = {}
        if not enabled:
            return
        for f in manifest.files:
            if f.fmt in ("BCK", "BTP") and f.container:
                self.by_container.setdefault(f.container, []).append(f)
            elif f.fmt in ("BMD", "BDL") and f.container:
                self.model_containers.add(f.container)
                h = f.sha1_decompressed or f.sha1
                if h:
                    self.homes.setdefault(h, set()).add(f.container)

    def containers_of(self, e: ManifestEntry) -> list[str]:
        h = e.sha1_decompressed or e.sha1
        homes = set(self.homes.get(h, set())) if h else set()
        if e.container:
            homes.add(e.container)
        return sorted(homes)

    def _load(self, e: ManifestEntry):
        if e.path not in self._cache:
            try:
                data = self.src.get(e.path)
                name = Path(e.path).stem
                self._cache[e.path] = (
                    ja.parse_bck(data, name) if e.fmt == "BCK" else ja.parse_btp(data, name)
                )
            except Exception:  # noqa: BLE001
                self._cache[e.path] = None
        return self._cache[e.path]

    def _match(self, entries, model: j3d.Model, seen: set[str] | None = None):
        """Clips/patterns among `entries` that fit `model`. `seen` (per model) drops
        byte-identical clips that recur in many archives - Sunshine ships every NPC's
        animations inside every level's .szs, which would attach thousands of copies."""
        clips: list[ja.Bck] = []
        pats: list[ja.Btp] = []
        mat_names = {m.name for m in model.materials}
        for e in entries:
            h = e.sha1_decompressed or e.sha1
            if seen is not None and h:
                if h in seen:
                    continue
                seen.add(h)
            a = self._load(e)
            if a is None:
                continue
            if isinstance(a, ja.Bck):
                if a.joint_count == len(model.joints):
                    clips.append(a)
            elif a.tracks and all(t.material in mat_names for t in a.tracks):
                pats.append(a)
        return clips, pats

    def for_model(self, e: ManifestEntry, model: j3d.Model):
        """Clips/patterns from the model's own archive(s)."""
        if not self.enabled or not e.container:
            return [], [], []
        clips: list[ja.Bck] = []
        pats: list[ja.Btp] = []
        sources: list[str] = []
        seen: set[str] = set()
        for c in self.containers_of(e):
            cl, pa = self._match(self.by_container.get(c, []), model, seen)
            if cl or pa:
                clips += cl
                pats += pa
                sources.append(c)
        return clips, pats, sources

    def _own_hashes(self, e: ManifestEntry) -> set[str]:
        """Content hashes of the clips in a model's own archives (already attached)."""
        out: set[str] = set()
        for c in self.containers_of(e):
            for f in self.by_container.get(c, []):
                h = f.sha1_decompressed or f.sha1
                if h:
                    out.add(h)
        return out

    def orphan_targets(self, exported):
        """Clips that no model in their own archive can use (animation-only archives like
        LkAnm.arc, or AlAnm.arc whose 35-joint clips drive a body model stored elsewhere)
        are attached to the most plausible exported model: explicit anim_map, else same
        directory + matching joint count, ranked by shared BTP material names, archive
        name affinity (Kolin.arc <- Kolin1.arc) and detail. Small skeletons need name or
        BTP evidence so coincidental joint counts don't attract clips."""
        out: dict[int, tuple[list, list, list]] = {}
        seen_by_idx: dict[int, set[str]] = {}
        # what each exported model can absorb, by container
        local_counts: dict[str, set[int]] = {}
        local_mats: dict[str, set[str]] = {}
        for me, _r, model in exported:
            for c in self.containers_of(me):
                local_counts.setdefault(c, set()).add(len(model.joints))
                local_mats.setdefault(c, set()).update(m.name for m in model.materials)
        for container, entries in self.by_container.items():
            stem = _arc_stem(container)
            parent = str(Path(container).parent)
            counts: set[int] = set()
            orphan_btps: list[ja.Btp] = []
            for e in entries:
                a = self._load(e)
                if isinstance(a, ja.Bck):
                    if a.joint_count not in local_counts.get(container, set()):
                        counts.add(a.joint_count)
                elif isinstance(a, ja.Btp) and a.tracks:
                    local = local_mats.get(container, set())
                    if not set(a.material_names) <= local:
                        orphan_btps.append(a)
            if not counts and not orphan_btps:
                continue
            mapped = self.anim_map.get(stem)
            best: dict[int, tuple[tuple, int]] = {}  # joint count -> (score, exported idx)
            eligible: list[int] = []
            for idx, (me, r, model) in enumerate(exported):
                homes = self.containers_of(me)
                if not homes or container in homes:
                    continue
                if mapped is not None:
                    if mapped not in {_arc_stem(h) for h in homes}:
                        continue
                elif all(str(Path(h).parent) != parent for h in homes):
                    continue
                n = len(model.joints)
                mats = {m.name for m in model.materials}
                btp_hits = sum(1 for b in orphan_btps if set(b.material_names) <= mats)
                if n not in counts and not btp_hits:
                    continue
                affinity = max(_affinity(stem, _arc_stem(h)) for h in homes)
                if mapped is None and n < 8 and not btp_hits and not affinity:
                    continue
                eligible.append(idx)
                score = (btp_hits, affinity, r.triangles)
                if n not in best or score > best[n][0]:
                    best[n] = (score, idx)
            targets: set[int] = {idx for _score, idx in best.values()}
            # Outfit/variant models on the very same skeleton (identical joint names) that
            # bring no animations of their own (TP's Kmdl/Bmdl/Zmdl Link tunics) share the
            # clips; models in archives with their own clip packs (cutscene copies) don't.
            for idx in list(targets):
                names = [j.name for j in exported[idx][2].joints]
                for j in eligible:
                    if j in targets:
                        continue
                    ent = exported[j]
                    if [x.name for x in ent[2].joints] != names:
                        continue
                    if any(self.by_container.get(h) for h in self.containers_of(ent[0])):
                        continue
                    targets.add(j)
            for idx in sorted(targets):
                me, r, model = exported[idx]
                seen = seen_by_idx.setdefault(idx, self._own_hashes(exported[idx][0]))
                clips, pats = self._match(entries, model, seen)
                clips = [c for c in clips if c.joint_count in counts]
                pats = [p for p in pats if p in orphan_btps]
                if not clips and not pats:
                    continue
                cur = out.setdefault(idx, ([], [], []))
                cur[0].extend(clips)
                cur[1].extend(pats)
                cur[2].append(container)
        return [(exported[i], v) for i, v in out.items()]


def _affinity(anim_stem: str, model_stem: str) -> int:
    """Length of the shared name prefix if it is meaningful (>= 3 chars), else 0."""
    a, b = anim_stem.lower(), model_stem.lower()
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n if n >= 3 else 0


def load_results(game_dir: Path) -> RipResult:
    """Rebuild a RipResult from out/<GameID>/rip_results.json (for re-rendering the report)."""
    d = json.loads((Path(game_dir) / "rip_results.json").read_text(encoding="utf-8"))
    res = RipResult(game_id=d["game_id"], title=d.get("title", ""), out_dir=Path(game_dir))
    res.seconds = d.get("seconds", 0.0)
    res.models = [ModelResult(**m) for m in d.get("models", [])]
    res.textures = [TextureResult(**t) for t in d.get("textures", [])]
    return res


def _merge_previous(result: RipResult, results_json: Path) -> None:
    """A partial (--filter/--limit) run keeps earlier results for everything it didn't touch."""
    if not results_json.exists():
        return
    try:
        prev = json.loads(results_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    have_m = {m.path for m in result.models}
    have_t = {t.path for t in result.textures}
    for m in prev.get("models", []):
        if m["path"] not in have_m:
            result.models.append(ModelResult(**m))
    for t in prev.get("textures", []):
        if t["path"] not in have_t:
            result.textures.append(TextureResult(**t))
    result.models.sort(key=lambda m: m.path)
    result.textures.sort(key=lambda t: t.path)


def _thumbnail(st: gltf.ExportStats, model: j3d.Model, out_base: Path, rel: Path) -> str | None:
    if not st.geometry:
        return None
    pos_list, tri_list, col_list, uv_list, textri_list = [], [], [], [], []
    base = 0
    variant_mats = {i for i, m in enumerate(model.materials) if m.name in st.variants}
    for (pos, tris, mat), shape_uvs in zip(st.geometry, st.uvs, strict=False):
        if mat in variant_mats:
            continue
        pos_list.append(pos)
        tri_list.append(tris + base)
        color = (0.75, 0.75, 0.75)
        tex_index = -1
        uv_set = 0
        if mat is not None and mat < len(st.material_tex):
            d = st.material_tex[mat]
            if 0 <= d[0] < len(st.texture_colors):
                color = st.texture_colors[d[0]]
                tex_index, uv_set = d
        col_list.append(np.tile(np.array(color, dtype=np.float64), (len(tris), 1)))
        uv = shape_uvs.get(uv_set)
        if uv is None:
            uv = np.zeros((len(pos), 2), np.float32)
            tex_index = -1
        uv_list.append(uv)
        textri_list.append(np.full(len(tris), tex_index, dtype=np.int64))
        base += len(pos)
    if not pos_list:
        return None
    img = thumb.render(
        np.concatenate(pos_list),
        np.concatenate(tri_list),
        np.concatenate(col_list),
        size=256,
        uvs=np.concatenate(uv_list),
        tri_texture=np.concatenate(textri_list),
        textures=st.texture_images,
    )
    out = out_base.parent / f"{out_base.name}_thumb.png"
    png.write_rgba(out, img)
    return str((rel.parent / out.name).as_posix())


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

_CSS = """
body{font-family:system-ui,sans-serif;margin:0;padding:1.5rem;background:#141417;color:#e8e8ec}
h1{font-size:1.4rem;margin:0 0 .25rem}h2{font-size:1.1rem;margin:2rem 0 .5rem}
.sub{color:#9a9aa6;margin-bottom:1rem}
.stats span{display:inline-block;background:#232329;border-radius:6px;padding:.3rem .6rem;margin:0 .4rem .4rem 0}
input#q{width:100%;max-width:40rem;padding:.5rem .7rem;border-radius:6px;border:1px solid #33333d;background:#1c1c21;color:#eee;margin:.5rem 0 1rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:.7rem}
.card{background:#1c1c21;border:1px solid #2a2a31;border-radius:8px;padding:.5rem;font-size:.78rem;overflow:hidden}
.card img.t{width:100%;aspect-ratio:1;object-fit:contain;background:
 repeating-conic-gradient(#26262c 0 25%,#1c1c21 0 50%) 0 0/16px 16px;border-radius:4px}
.card .n{font-weight:600;word-break:break-all;margin:.35rem 0 .15rem}
.card .p{color:#8f8f9c;word-break:break-all}
.card .m{color:#b7b7c2;margin-top:.2rem}
.card.err{border-color:#7a2d2d}.card.dup{opacity:.55}
.tex{display:flex;flex-wrap:wrap;gap:3px;margin-top:.3rem}
.tex img{width:28px;height:28px;object-fit:cover;border-radius:3px;background:#333}
a{color:#8ab4f8;text-decoration:none}a:hover{text-decoration:underline}
details{margin:.4rem 0}summary{cursor:pointer;color:#9a9aa6}
summary .src{color:#6f6f7c;font-size:.7rem}
.dl{color:#8f8f9c;margin-top:.25rem}.dl a{margin:0 .1rem}
.act{display:none;gap:.3rem;margin-top:.35rem}body.served .act{display:flex}
.act button{flex:1;background:#2b2b34;color:#dfe3ff;border:1px solid #3a3a46;border-radius:5px;padding:.3rem .4rem;font-size:.72rem;cursor:pointer}
.act button:hover{background:#3a3a48}.act button:disabled{opacity:.6}
.hint{color:#8f8f9c;font-size:.8rem;margin:-.5rem 0 1rem}body.served .hint{display:none}
.sub code,.sub i{color:#c9c9d4}
"""

_JS = """
// filter is debounced: with thousands of cards, filtering on every keystroke froze the tab
const q=document.getElementById('q');const cards=[...document.querySelectorAll('.card')];
let qt=null;q.addEventListener('input',()=>{clearTimeout(qt);qt=setTimeout(()=>{
const s=q.value.toLowerCase();
cards.forEach(c=>{const show=c.dataset.k.includes(s)?'':'none';
if(c.style.display!==show)c.style.display=show;});},200);});
// "Open in Blender" only works when served by `gcrip serve` (needs a local endpoint)
const served=location.protocol.startsWith('http');
document.body.classList.toggle('served',served);
// A browser may show a cached report from a DIFFERENT game served earlier on this port;
// every click would then 404. Ask the server which game it serves and reload if they differ.
if(served&&typeof GCRIP_GAME!=='undefined'){fetch('/status').then(r=>r.json()).then(j=>{
  if(j.game&&j.game!==GCRIP_GAME&&!location.search.includes('fresh')){
    location.replace('/report.html?fresh='+Date.now());}}).catch(()=>{});}
// served: the glb link packs gltf+bin+textures on the fly; on disk it needs `gcrip pack` first
document.querySelectorAll('a.glb').forEach(a=>{
  if(served){a.href='/glb?path='+encodeURIComponent(a.getAttribute('href'));}
  else{a.addEventListener('click',e=>{e.preventDefault();
    alert('Run `gcrip pack <ripdir>` once to write .glb files, or `gcrip serve <ripdir>` to download them from here.');});}
});
document.querySelectorAll('.act button').forEach(b=>b.addEventListener('click',async e=>{
  const path=b.parentElement.dataset.path;const kind=b.classList.contains('open')?'open':'reveal';
  b.disabled=true;const old=b.textContent;b.textContent=kind==='open'?'Launching...':'...';
  try{const r=await fetch(`/${kind}?path=${encodeURIComponent(path)}`);const j=await r.json();
    b.textContent=j.error?('! '+j.error):(kind==='open'?'Opened':'Shown');}
  catch(err){b.textContent='! '+err;}
  setTimeout(()=>{b.textContent=old;b.disabled=false;},2500);}));
"""


def _scan_stages(out_dir: Path) -> list[dict]:
    """Levels written by `gcrip stage` under <out_dir>/stages/<name>/<name>.gltf."""
    stages_dir = Path(out_dir) / "stages"
    if not stages_dir.is_dir():
        return []
    found = []
    for d in sorted(stages_dir.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        for g in sorted(d.glob("*.gltf")):
            info = {"name": d.name, "rel": f"stages/{d.name}/{g.name}"}
            rep = d / f"{g.stem}_report.json"
            if rep.exists():
                with contextlib.suppress(OSError, ValueError):
                    info.update(json.loads(rep.read_text(encoding="utf-8")))
            found.append(info)
    return found


def _stage_cards(res: RipResult) -> list[str]:
    stages = _scan_stages(res.out_dir)
    if not stages:
        return []
    parts = [f"<h2>Levels <small>({len(stages)} recompiled stages)</small></h2>"]
    if (res.out_dir / "stages" / "stage_matrix.md").exists():
        parts.append(
            "<div class='sub'>Whole levels: room geometry + every placed actor, one glTF each "
            "(<code>gcrip stage</code>). Details: <a href='stages/stage_matrix.md'>"
            "stage_matrix.md</a></div>"
        )
    parts.append("<div class='grid'>")
    for s in stages:
        rel = html.escape(s["rel"], quote=True)
        key = html.escape(f"level stage {s['name']} {s.get('stage', '')}".lower(), quote=True)
        parts.append(f"<div class='card' data-k=\"{key}\">")
        parts.append(f"<div class='n'>{html.escape(s['name'])}</div>")
        if "placed" in s:
            parts.append(
                f"<div class='m'>{len(s.get('rooms', []))} rooms · "
                f"{s.get('room_models', 0)} room models · {s.get('placed', 0)} actors · "
                f"{s.get('triangles', 0):,} tris"
                + (f" · {s['unresolved']} unresolved" if s.get("unresolved") else "")
                + "</div>"
            )
        parts.append(
            f"<div class='dl'>download: <a class='glb' href='{rel}' "
            f"title='one file, textures embedded'>glb</a> · "
            f"<a href='{rel}' title='needs the .bin next to it'>gltf</a></div>"
        )
        parts.append(
            f"<div class='act' data-path='{rel}'>"
            "<button class='open'>Open in Blender</button>"
            "<button class='reveal'>Show file</button></div>"
        )
        parts.append("</div>")
    parts.append("</div>")
    return parts


def write_report(res: RipResult) -> Path:
    ok = [m for m in res.models if m.out_rel]
    dups = [m for m in res.models if m.duplicate_of]
    errs = [m for m in res.models if m.error]
    tri = sum(m.triangles for m in ok)
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>gcrip - {html.escape(res.game_id)}</title><style>{_CSS}</style>",
        f"<h1>{html.escape(res.title)} <small>({html.escape(res.game_id)})</small></h1>",
        f"<div class='sub'>ripped by gcrip in {res.seconds:.0f}s &middot; "
        "Blender: File &rsaquo; Import &rsaquo; glTF 2.0, then press <b>Z &rsaquo; Material Preview</b> "
        "to see textures (the default Solid view hides them)</div>",
        "<div class='stats'>",
        f"<span>{len(ok)} models exported</span><span>{len(dups)} duplicates skipped</span>",
        f"<span>{len(errs)} failed</span><span>{tri:,} triangles</span>",
        f"<span>{sum(len(m.animations) for m in ok)} animation clips on "
        f"{sum(1 for m in ok if m.animations)} models</span>",
        f"<span>{sum(1 for m in ok if m.expressions)} models with expression switches</span>",
        f"<span>{sum(1 for t in res.textures if t.out_rel)} standalone textures</span></div>",
        "<div class='sub'>Animations import as actions (set the scene to 30 fps). Face switches "
        "are hidden meshes named <i>material@texture</i> under <i>&lt;model&gt;_variants</i> "
        "(toggle visibility). Humanoid rigs carry Mixamo bone names in bone custom properties "
        "(<i>gcrip_std_bone</i>) or use <code>--bone-names mixamo</code>.</div>",
        "<input id='q' placeholder='filter by name / path / joint name...'>",
        "<div class='hint'>Tip: run <code>gcrip serve "
        + html.escape(str(res.out_dir))
        + "</code> to get <b>Open in Blender</b> buttons on every card, and "
        "<code>gcrip blend ...</code> to make .blend asset files.</div>",
    ]
    parts += _stage_cards(res)
    parts += [
        "<h2>Models</h2><div class='grid'>",
    ]
    for m in res.models:
        rel = _rel_out_path(m.path)
        key = html.escape(
            " ".join([m.path, *m.joint_names, *m.animations, *m.std_bones.values()]).lower(),
            quote=True,
        )
        cls = "card" + (" err" if m.error else "") + (" dup" if m.duplicate_of else "")
        parts.append(f"<div class='{cls}' data-k=\"{key}\">")
        if m.thumb:
            parts.append(
                f"<a href='{html.escape(m.out_rel or '#')}'><img class='t' src='{html.escape(m.thumb)}' loading='lazy'></a>"
            )
        parts.append(f"<div class='n'>{html.escape(rel.name)}</div>")
        parts.append(f"<div class='p'>{html.escape(str(rel.parent.as_posix()))}</div>")
        if m.error:
            parts.append(f"<div class='m' style='color:#e07070'>{html.escape(m.error)}</div>")
        elif m.duplicate_of:
            parts.append(f"<div class='m'>duplicate of {html.escape(m.duplicate_of)}</div>")
        else:
            parts.append(
                f"<div class='m'>{m.triangles:,} tris · {m.joints} joints · {m.textures} tex"
                f"{' · skinned' if m.skinned else ''}</div>"
            )
            # downloads: .glb is the only single-file form (gltf needs its .bin + _tex folder)
            gltf_rel = html.escape(m.out_rel or "", quote=True)
            dl = [f"<a class='glb' href='{gltf_rel}' title='one file, textures embedded'>glb</a>"]
            if m.glb_rel:
                dl = [f"<a href='{html.escape(m.glb_rel, quote=True)}' download>glb</a>"]
            if m.blend_rel:
                dl.append(f"<a href='{html.escape(m.blend_rel, quote=True)}' download>blend</a>")
            dl.append(
                f"<a href='{gltf_rel}' title='needs the .bin and _tex folder next to it'>gltf</a>"
            )
            parts.append("<div class='dl'>download: " + " · ".join(dl) + "</div>")
            target = m.blend_rel or m.out_rel or ""
            parts.append(
                f"<div class='act' data-path='{html.escape(target, quote=True)}'>"
                "<button class='open'>Open in Blender</button>"
                "<button class='reveal'>Show file</button></div>"
            )
            if m.texture_files:
                parts.append("<div class='tex'>")
                for tf in m.texture_files[:16]:
                    parts.append(
                        f"<img src='{html.escape(tf)}' loading='lazy' title='{html.escape(tf)}'>"
                    )
                parts.append("</div>")
            if m.variants:
                parts.append(
                    f"<details><summary>{len(m.variants)} alternate meshes (hidden)</summary>"
                    f"{html.escape(', '.join(sorted(m.variants)))}</details>"
                )
            if m.animations:
                srcs = ", ".join(_arc_stem(a) for a in m.anim_sources)
                parts.append(
                    f"<details><summary>{len(m.animations)} animations "
                    f"<span class='src'>from {html.escape(srcs)}</span></summary>"
                    f"{html.escape(', '.join(m.animations))}</details>"
                )
            if m.expressions:
                parts.append(
                    f"<details><summary>{len(m.expressions)} expression presets</summary>"
                    f"{html.escape(', '.join(m.expressions))}</details>"
                )
            if m.std_bones:
                pairs = ", ".join(f"{k}&rarr;{v}" for k, v in m.std_bones.items())
                parts.append(
                    f"<details><summary>humanoid rig: {len(m.std_bones)} Mixamo bones mapped"
                    f"</summary>{pairs}</details>"
                )
            if m.joint_names and len(m.joint_names) > 1:
                parts.append(
                    f"<details><summary>{len(m.joint_names)} joints</summary>"
                    f"{html.escape(', '.join(m.joint_names))}</details>"
                )
        parts.append("</div>")
    parts.append("</div>")
    if res.textures:
        parts.append("<h2>Standalone textures</h2><div class='grid'>")
        for t in res.textures:
            rel = _rel_out_path(t.path)
            key = html.escape(t.path.lower(), quote=True)
            parts.append(f"<div class='card{' err' if t.error else ''}' data-k=\"{key}\">")
            if t.out_rel:
                parts.append(
                    f"<a href='{html.escape(t.out_rel)}'><img class='t' src='{html.escape(t.out_rel)}' loading='lazy'></a>"
                )
            parts.append(
                f"<div class='n'>{html.escape(rel.name)}</div><div class='p'>{html.escape(str(rel.parent.as_posix()))}</div>"
            )
            parts.append(
                f"<div class='m'>{html.escape(t.error or f'{t.fmt} {t.width}x{t.height}')}</div></div>"
            )
        parts.append("</div>")
    parts.append(f"<script>const GCRIP_GAME={json.dumps(res.game_id)};{_JS}</script>")
    out = res.out_dir / "report.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


__all__ = ["ManifestEntry", "RipResult", "rip", "rarc", "write_report"]
