"""Disc image -> glTF models + PNG textures + report.html (the Dreamcast `rip`).

    dcrip rip "game.zip" out/            ->  out/<product>/<disc path>/<model>.gltf ...

Walks the ISO 9660 tree, expands AFS archives and PRS-compressed files, and collects three
kinds of things: Ninja models (NJTL/NJCM/NJBM files), Ninja motions (NMDM) and PVR/PVM
textures. Textures are matched to models by the names in the model's own texture list
(NJTL) - first among textures in the same directory / same-stem PVM, then disc-wide.
Motions are matched by file stem (NAME.NJM -> NAME.NJ, NAME_*.NJM -> NAME.NJ). Output
layout, rip_results.json and report.html are the same as gcrip's, so `gcrip serve`,
`gcrip blend` and the Blender add-on work on these folders unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from dcrip import ninja_eval
from dcrip.disc.gdi import GdImage, clean_title
from dcrip.disc.iso9660 import walk
from dcrip.export import gltf
from dcrip.formats import afs, ninja, prs, pvr
from gcrip.export import png
from gcrip.rip import ModelResult, RipResult, TextureResult, write_report


@dataclass
class _File:
    path: str  # display path (AFS entries get "archive.afs/NNN_name")
    data: bytes
    kind: str  # "model" | "motion" | "pvr" | "pvm" | ""
    stem: str = ""
    directory: str = ""
    compressed: bool = False


@dataclass
class _TexSource:
    name: str  # lower-case texture name
    path: str
    data: bytes  # one GBIX/PVRT record
    _img: np.ndarray | None = field(default=None, repr=False)

    def image(self) -> np.ndarray:
        if self._img is None:
            self._img = pvr.parse(self.data).decode()
        return self._img


def _classify(name: str, data: bytes) -> str:
    if ninja.is_ninja(data):
        return "model"
    if ninja.is_motion(data):
        return "motion"
    if pvr.is_pvm(data):
        return "pvm"
    if pvr.is_pvr(data):
        return "pvr"
    return ""


def _log(quiet: bool, msg: str) -> None:
    if not quiet:
        print(msg, flush=True)


def _safe_component(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("._") or "x"


def _expand(img: GdImage, quiet: bool, limit_bytes: int = 96 << 20) -> list[_File]:
    """Every interesting file on the disc, archives expanded, PRS inflated."""
    out: list[_File] = []
    vol = walk(img)
    files = vol.files
    for i, e in enumerate(files):
        if not quiet and i % 200 == 0:
            sys.stderr.write(f"\r  scanning {i + 1}/{len(files)}: {e.path[:60]:<60}")
            sys.stderr.flush()
        if e.size < 8 or e.size > limit_bytes:
            continue
        try:
            head = img.read(e.lba, 32)
        except ValueError:
            continue
        low = e.name.lower()
        is_prs = prs.looks_like_prs(e.name)
        kind = _classify(e.name, head)
        if not (kind or afs.is_afs(head) or is_prs):
            continue
        data = img.read(e.lba, e.size)
        directory = e.path.rsplit("/", 1)[0] if "/" in e.path else ""
        if afs.is_afs(data):
            try:
                entries = afs.parse(data)
            except ValueError:
                continue
            for ent in entries:
                blob = data[ent.offset : ent.offset + ent.size]
                if len(blob) < 8:
                    continue
                name = ent.name or f"{ent.index:04d}"
                comp = False
                if name.lower().endswith(".prs"):
                    try:
                        blob = prs.decompress(blob)
                        comp = True
                    except ValueError:
                        continue
                k = _classify(name, blob[:32])
                if not k:
                    continue
                out.append(
                    _File(
                        path=f"{e.path}/{name}",
                        data=blob,
                        kind=k,
                        stem=name.rsplit(".", 1)[0].lower(),
                        directory=e.path,
                        compressed=comp,
                    )
                )
            continue
        comp = False
        if is_prs and not kind:
            try:
                data = prs.decompress(data)
                comp = True
            except ValueError:
                continue
            kind = _classify(e.name, data[:32])
            if not kind:
                continue
        stem = low.rsplit(".", 1)[0]
        out.append(_File(e.path, data, kind, stem, directory, comp))
    if not quiet:
        sys.stderr.write("\n")
    return out


def _texture_index(files: list[_File]) -> dict[str, list[_TexSource]]:
    """lower-case texture name -> sources (PVM entries carry names; a standalone PVR is
    named after its file)."""
    index: dict[str, list[_TexSource]] = {}
    for f in files:
        if f.kind == "pvr":
            index.setdefault(f.stem, []).append(_TexSource(f.stem, f.path, f.data))
        elif f.kind == "pvm":
            try:
                for ent in pvr.parse_pvm(f.data):
                    name = ent.name.lower()
                    rec = f.data[ent.offset : ent.offset + ent.size]
                    index.setdefault(name, []).append(_TexSource(name, f"{f.path}/{ent.name}", rec))
            except (ValueError, IndexError):
                continue
    return index


def _pick_texture(
    name: str, model: _File, index: dict[str, list[_TexSource]]
) -> _TexSource | None:
    cands = index.get(name.lower())
    if not cands:
        return None
    # same directory + same-stem PVM first, then same directory, then anything
    def score(t: _TexSource) -> tuple:
        tdir = t.path.rsplit("/", 2)[0] if "/" in t.path else ""
        same_dir = tdir == model.directory or t.path.startswith(model.directory + "/")
        same_stem = f"/{model.stem}." in t.path.lower()
        return (not same_stem, not same_dir)

    return sorted(cands, key=score)[0]


def _pvm_by_index(model: _File, files: list[_File]) -> list[_TexSource]:
    """A model without its own NJTL uses texture ids into a list the game builds from a
    PVM: the same-stem PVM in the same directory is that list, in entry order."""
    best = None
    for f in files:
        if f.kind != "pvm" or f.directory != model.directory:
            continue
        if f.stem == model.stem:
            best = f
            break
        if model.stem.startswith(f.stem) and (best is None or len(f.stem) > len(best.stem)):
            best = f
    if best is None:
        return []
    try:
        ents = pvr.parse_pvm(best.data)
    except (ValueError, IndexError):
        return []
    return [
        _TexSource(e.name.lower(), f"{best.path}/{e.name}", best.data[e.offset : e.offset + e.size])
        for e in ents
    ]


def _motions_for(model: _File, motions: list[_File]) -> list[_File]:
    out = []
    for m in motions:
        if m.directory != model.directory:
            continue
        if m.stem == model.stem or m.stem.startswith(model.stem):
            out.append(m)
    return sorted(out, key=lambda m: m.stem)


def _game_folder(img: GdImage) -> str:
    h = img.header
    product = _safe_component(h.product) or "unknown"
    m = re.search(r"GD-ROM(\d+)/(\d+)", h.device)
    if m and int(m.group(2)) > 1:
        product += f"_d{m.group(1)}"
    return product


def rip(
    image_path: Path,
    out_root: Path,
    *,
    thumbnails: bool = True,
    quiet: bool = False,
    limit: int | None = None,
    path_filter: str | None = None,
    animations: bool = True,
    fps: float = 30.0,
    textures: bool = True,
) -> RipResult:
    t_start = time.monotonic()
    image_path, out_root = Path(image_path), Path(out_root)
    with GdImage(image_path) as img:
        game_id = _game_folder(img)
        game_dir = out_root / game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        result = RipResult(game_id=game_id, title=clean_title(img.header.title), out_dir=game_dir)
        _log(quiet, f"[1/3] walking {image_path.name} ({result.title}) ...")
        files = _expand(img, quiet)
        (game_dir / "disc_manifest.json").write_text(
            json.dumps(
                {
                    "image": {"filename": image_path.name, "size": image_path.stat().st_size},
                    "game": {
                        "id": game_id,
                        "product": img.header.product,
                        "title": result.title,
                        "company": img.header.company,
                        "region": img.header.region,
                        "date": img.header.date,
                    },
                    "files": [
                        {"path": f.path, "kind": f.kind, "size": len(f.data), "prs": f.compressed}
                        for f in files
                    ],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    models = [f for f in files if f.kind == "model"]
    motions = [f for f in files if f.kind == "motion"] if animations else []
    tex_index = _texture_index(files) if textures else {}
    if path_filter:
        models = [m for m in models if path_filter.lower() in m.path.lower()]
    if limit:
        models = models[:limit]
    _log(
        quiet,
        f"[2/3] {len(models)} models, {len(motions)} motions, "
        f"{sum(len(v) for v in tex_index.values())} textures",
    )
    seen: dict[str, str] = {}
    for i, f in enumerate(models):
        t0 = time.monotonic()
        sha = hashlib.sha1(f.data).hexdigest()
        r = ModelResult(path=f.path, out_rel=None, sha1=sha)
        result.models.append(r)
        if not quiet and (i % 10 == 0 or i == len(models) - 1):
            sys.stderr.write(f"\r  model {i + 1}/{len(models)}: {f.path[:70]:<70}")
            sys.stderr.flush()
        if sha in seen:
            r.duplicate_of = seen[sha]
            continue
        rel = Path(*[_safe_component(p) for p in f.path.split("/")])
        stem = rel.stem
        out_base = game_dir / rel.parent / stem
        try:
            mots = _motions_for(f, motions)
            nj = ninja.parse(f.data, motions=[m.data for m in mots])
            scene = ninja_eval.evaluate(nj, stem, fps=fps)
            for k, m in enumerate(mots):
                if k < len(scene.clips):
                    scene.clips[k].name = m.stem
            if nj.texlist:
                for name in nj.texlist.names:
                    src = _pick_texture(name, f, tex_index)
                    if src is not None:
                        try:
                            scene.textures[name] = src.image()
                        except (ValueError, IndexError) as ex:
                            scene.warnings.append(f"texture {name}: {ex}")
            else:
                by_index = _pvm_by_index(f, files)
                for m in scene.materials:
                    if m.texture and m.texture.startswith("tex"):
                        k = int(m.texture[3:])
                        if k < len(by_index):
                            try:
                                scene.textures[m.texture] = by_index[k].image()
                                m.name = by_index[k].name
                            except (ValueError, IndexError) as ex:
                                scene.warnings.append(f"texture {m.texture}: {ex}")
            st = gltf.export(scene, out_base)
            r.out_rel = str((rel.parent / f"{stem}.gltf").as_posix())
            r.triangles, r.vertices, r.joints = st.triangles, st.vertices, st.joints
            r.textures, r.materials = st.textures, st.materials
            r.skinned = st.joints > 1
            r.joint_names = [j.name for j in scene.joints]
            r.texture_files = st.texture_files
            r.animations = st.clip_names
            r.anim_sources = sorted({m.path.rsplit("/", 1)[-1] for m in mots})
            r.warnings = st.warnings
            if thumbnails:
                th = gltf.thumbnail(st, out_base)
                if th:
                    r.thumb = str((rel.parent / th.name).as_posix())
            seen[sha] = f.path
        except Exception as ex:  # noqa: BLE001
            r.error = f"{type(ex).__name__}: {ex}"
            if not quiet:
                sys.stderr.write(f"\n  ! {f.path}: {r.error}\n")
                if "--debug" in sys.argv:
                    traceback.print_exc()
        r.seconds = time.monotonic() - t0
    if not quiet:
        sys.stderr.write("\n")
    if textures:
        texs = [f for f in files if f.kind in ("pvr", "pvm")]
        _log(quiet, f"[3/3] {len(texs)} texture files")
        for f in texs:
            tr = TextureResult(path=f.path, out_rel=None)
            result.textures.append(tr)
            rel = Path(*[_safe_component(p) for p in f.path.split("/")])
            try:
                if f.kind == "pvr":
                    t = pvr.parse(f.data)
                    out = game_dir / rel.parent / f"{rel.stem}.png"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    png.write_rgba(out, t.decode())
                    tr.fmt, tr.width, tr.height = t.fmt_name, t.width, t.height
                    tr.out_rel = str((rel.parent / f"{rel.stem}.png").as_posix())
                else:
                    ents = pvr.parse_pvm(f.data)
                    folder = game_dir / rel.parent / rel.stem
                    n = 0
                    for ent in ents:
                        try:
                            t = pvr.parse(f.data[ent.offset : ent.offset + ent.size])
                            folder.mkdir(parents=True, exist_ok=True)
                            png.write_rgba(folder / f"{_safe_component(ent.name)}.png", t.decode())
                            tr.fmt, tr.width, tr.height = t.fmt_name, t.width, t.height
                            n += 1
                        except (ValueError, IndexError):
                            continue
                    if n:
                        first = _safe_component(ents[0].name)
                        tr.out_rel = str((rel.parent / rel.stem / f"{first}.png").as_posix())
                        tr.fmt = f"PVM x{n}"
            except Exception as ex:  # noqa: BLE001
                tr.error = f"{type(ex).__name__}: {ex}"
    result.seconds = time.monotonic() - t_start
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
