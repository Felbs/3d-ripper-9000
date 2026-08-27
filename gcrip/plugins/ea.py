"""Electronic Arts formats on GameCube.

Containers: BIG/VIV archives (BIGF/BIG4/C0FB, RefPack members), Tiburon TERF archives
(Madden), and Black Box ZZDATA packs (Need for Speed - the members are recovered by
scanning for chunk streams, since ZDIR.BIN only carries name hashes).

Textures: EA shape files (SHPI/SHPS/SHPX/SHPG/SHPP), Tiburon MMAP, and Need for Speed
texture packs - exported as textures-only scenes.

Models: Need for Speed geometry chunks (0x80134000) with GX strips - one scene per LOD.
Textures for a model come from the packs in the same file, then from every texture pack
in the same ZZDATA packs (looked up by name hash through `src`).
"""

from __future__ import annotations

import re
import weakref
from pathlib import PurePosixPath

from gcrip.formats import ea_big, ea_nfs, ea_shape, ea_terf
from ripcore.scene import MaterialDef, Scene

NAME = "ea"

_PACK_RE = re.compile(r"^zzdata\d*\.bin$", re.IGNORECASE)


# ---------------------------------------------------------------- containers


def is_container(name: str, head: bytes) -> bool:
    if ea_big.is_big(head) or ea_terf.is_terf(head):
        return True
    return bool(_PACK_RE.match(name))


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if ea_big.is_big(data):
        return ea_big.expand(data)
    if ea_terf.is_terf(data):
        return ea_terf.expand(data)
    return [(m.name, data[m.start : m.end]) for m in ea_nfs.scan_pack(data)]


# ---------------------------------------------------------------- detection


def detect(path: str, head: bytes, size: int) -> bool:
    if size < 16:
        return False
    if ea_shape.is_shape(head) or ea_terf.is_mmap(head):
        return True
    if _PACK_RE.match(PurePosixPath(path).name):
        return False
    return ea_nfs.is_stream(head)


# ---------------------------------------------------------------- extraction


def _textures_only(name: str, textures: dict, warnings: list[str]) -> Scene:
    scene = Scene(name=name)
    scene.textures = textures
    scene.materials = [MaterialDef(name=k, texture=k) for k in textures]
    scene.extras = {"textures_only": True}
    scene.warnings = warnings
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = PurePosixPath(path).stem
    if ea_shape.is_shape(data):
        textures, warnings = {}, []
        for img in ea_shape.parse(data):
            warnings += img.warnings
            if img.rgba is not None:
                textures[img.name] = img.rgba
        return [_textures_only(stem, textures, warnings)] if textures else []
    if ea_terf.is_mmap(data):
        rgba, warnings = ea_terf.decode_mmap(data)
        return [_textures_only(stem, {stem: rgba}, warnings)]
    if not ea_nfs.is_stream(data):
        return []
    return _extract_nfs(data, path, src)


class _TexIndex:
    """Name hash -> decoded texture across every texture pack `src` can reach."""

    def __init__(self, src) -> None:
        self.src = src
        self.local: dict[int, tuple[bytes, ea_nfs.TpkTexture]] = {}
        self.remote: dict[int, tuple[str, ea_nfs.TpkTexture]] | None = None
        self.cache: dict[int, tuple[str, object] | None] = {}

    def add_local(self, data: bytes) -> None:
        for tpk in ea_nfs.parse_tpks(data):
            for h, t in tpk.textures.items():
                self.local.setdefault(h, (data, t))

    def _build_remote(self) -> None:
        self.remote = {}
        if self.src is None or not hasattr(self.src, "by_path"):
            return
        for p, e in self.src.by_path.items():
            cont = getattr(e, "container", None) or ""
            if not _PACK_RE.match(PurePosixPath(cont).name):
                continue
            if not p.lower().endswith((".tpk", ".bin")):
                continue
            try:
                blob = self.src.get(p)
            except Exception:  # noqa: BLE001
                continue
            if not ea_nfs.is_stream(blob[:8]):
                continue
            for tpk in ea_nfs.parse_tpks(blob):
                for h, t in tpk.textures.items():
                    self.remote.setdefault(h, (p, t))

    def __call__(self, h: int):
        if h in self.cache:
            return self.cache[h]
        hit = self.local.get(h)
        if hit is None:
            if self.remote is None:
                self._build_remote()
            r = self.remote.get(h)
            if r:
                p, t = r
                try:
                    hit = (self.src.get(p), t)
                except Exception:  # noqa: BLE001
                    hit = None
        out = None
        if hit is not None:
            try:
                out = ea_nfs.decode_tpk_texture(hit[0], hit[1])
            except (ValueError, struct_error):
                out = None
        self.cache[h] = out
        return out


struct_error = __import__("struct").error

_indexes: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _index_for(src) -> _TexIndex:
    if src is None:
        return _TexIndex(None)
    try:
        idx = _indexes.get(src)
    except TypeError:
        return _TexIndex(src)
    if idx is None:
        idx = _TexIndex(src)
        _indexes[src] = idx
    return idx


def _extract_nfs(data: bytes, path: str, src) -> list[Scene]:
    stem = PurePosixPath(path).stem
    index = _index_for(src)
    index.add_local(data)
    scenes: list[Scene] = []
    geos = ea_nfs.parse_geometry(data)
    if geos:
        scenes += ea_nfs.build_scenes(geos, stem, index)
    tpks = ea_nfs.parse_tpks(data)
    if tpks and not geos:
        textures, warnings = {}, []
        failed = 0
        for tpk in tpks:
            for h, t in tpk.textures.items():
                try:
                    name, rgba = ea_nfs.decode_tpk_texture(data, t)
                except (ValueError, struct_error) as e:
                    failed += 1
                    if failed <= 3:
                        warnings.append(f"texture {h:08x}: {e}")
                    continue
                key = name or f"tex_{h:08x}"
                if key in textures:
                    key = f"{key}_{h:08x}"
                textures[key] = rgba
        if failed > 3:
            warnings.append(f"{failed} textures failed to decode")
        if textures:
            name = tpks[0].name or stem
            scenes.append(_textures_only(name, textures, warnings))
    return scenes
