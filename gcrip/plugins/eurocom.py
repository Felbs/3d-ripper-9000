"""Eurocom EngineX discs (Sphinx and the Cursed Mummy, Spyro: A Hero's Tail, Batman Begins,
Buffy: Chaos Bleeds, Robots, Ice Age 2): ``Filelist.000`` is the container (its directory is
the sibling ``Filelist.bin``) and the ``GEOM`` ``.edb`` members hold the models and
textures (gcrip.formats.eurocom).  One Scene per mesh entity."""

from __future__ import annotations

import math
import posixpath
import re
import struct

import numpy as np

from gcrip.formats import eurocom
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "eurocom"
NEEDS_SIBLING = True

_CONTAINER = re.compile(r"filelist\.000$", re.I)


def is_container(name: str, head: bytes) -> bool:
    return bool(_CONTAINER.search(name))


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return []


def expand_with(data: bytes, name: str, sibling) -> list[tuple[str, bytes]]:
    """Members of Filelist.000 using the directory in the sibling Filelist.bin."""
    try:
        listing = sibling("Filelist.bin")
    except Exception:  # noqa: BLE001
        return []
    if listing is None:
        return []
    out = []
    seen = set()
    for e in eurocom.filelist(listing):
        locs = [off for off, idx in e.locations if idx == 0]
        if not locs:
            continue
        off = locs[0]
        size = e.size
        if off + 0x18 <= len(data) and data[off : off + 4] == eurocom.GEOM:
            size = max(size, struct.unpack_from(">I", data, off + 0x14)[0])
        if size == 0 or off + size > len(data):
            continue
        member = eurocom.member_name(e)
        if member in seen:
            continue
        seen.add(member)
        out.append((member, data[off : off + size]))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".edb") and eurocom.is_edb(head)


_entity_index: dict[int, dict[int, str]] = {}
_edb_cache: dict[str, tuple] = {}


def _index(src):
    """hashcode -> EDB path for every entity on the disc (built once per source)."""
    key = id(src)
    idx = _entity_index.get(key)
    if idx is not None:
        return idx
    _entity_index.clear()
    _edb_cache.clear()
    idx = {}
    by_path = getattr(src, "by_path", None) or {}
    for path in by_path:
        if not path.lower().endswith(".edb"):
            continue
        try:
            blob = src.get(path)
            if not eurocom.is_edb(blob[:16]):
                continue
            edb = eurocom.parse(blob)
        except Exception:  # noqa: BLE001
            continue
        for el in edb.entities:
            idx.setdefault(el.hashcode, path)
    _entity_index[key] = idx
    return idx


def _foreign(src, path: str):
    """(Edb, {hashcode: element}, decoded-texture cache) of another EDB, LRU-cached."""
    hit = _edb_cache.get(path)
    if hit is not None:
        return hit
    try:
        blob = src.get(path)
        edb = eurocom.parse(blob)
    except Exception:  # noqa: BLE001
        return None
    entry = (edb, {el.hashcode: el for el in edb.entities}, {})
    _edb_cache[path] = entry
    while len(_edb_cache) > 4:
        _edb_cache.pop(next(iter(_edb_cache)))
    return entry


def _rotation(rot) -> np.ndarray:
    """Euler radians (X, then Y, then Z) as a row-vector rotation matrix."""
    cx, sx = math.cos(rot[0]), math.sin(rot[0])
    cy, sy = math.cos(rot[1]), math.sin(rot[1])
    cz, sz = math.cos(rot[2]), math.sin(rot[2])
    rx = np.array([[1, 0, 0], [0, cx, sx], [0, -sx, cx]], np.float64)
    ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]], np.float64)
    rz = np.array([[cz, sz, 0], [-sz, cz, 0], [0, 0, 1]], np.float64)
    return rx @ ry @ rz


def _entity_scene(edb, m, stem: str, decoded: dict) -> Scene | None:
    scene = Scene(name=f"{stem}_{m.hashcode:08x}")
    _add_strips(edb, m, scene, {}, decoded)
    if not scene.primitives:
        return None
    scene.extras = {
        "format": "eurocom-edb",
        "edb_version": edb.version,
        "hashcode": f"{m.hashcode:08x}",
        "strips": len(m.strips),
    }
    return scene


def _add_strips(edb, m, scene: Scene, mats: dict, decoded: dict, xform=None) -> None:
    """Append a mesh entity's strips to ``scene``; ``xform`` = (scale, rotation, translation)."""
    for s in m.strips:
        ti = m.textures[s.texture] if s.texture < len(m.textures) else s.texture
        key = ti
        if key not in mats:
            tex_key = None
            if 0 <= ti < len(edb.textures):
                if ti not in decoded:
                    decoded[ti] = eurocom.texture_rgba(edb, edb.textures[ti])
                if decoded[ti] is not None:
                    tex_key = f"{edb.textures[ti].hashcode:08x}"
                    scene.textures.setdefault(tex_key, decoded[ti])
            alpha = bool(tex_key) and bool(np.any(scene.textures[tex_key][..., 3] < 255))
            scene.materials.append(
                MaterialDef(
                    name=f"tex{ti}",
                    texture=tex_key,
                    alpha_blend=alpha or bool(s.transparency),
                    double_sided=True,
                )
            )
            mats[key] = len(scene.materials) - 1
        pos = s.positions
        nrm = s.normals
        if xform is not None:
            scale, rot, loc = xform
            pos = ((pos.astype(np.float64) * scale) @ rot + loc).astype(np.float32)
            if nrm is not None:
                n2 = nrm.astype(np.float64) @ rot
                ln = np.linalg.norm(n2, axis=1, keepdims=True)
                nrm = np.divide(n2, ln, out=np.zeros_like(n2), where=ln > 0).astype(np.float32)
        scene.primitives.append(
            Primitive(
                material=mats[key],
                positions=pos,
                indices=s.indices,
                normals=nrm,
                uvs=s.uvs,
                colors=s.colors,
            )
        )


def extract(data: bytes, path: str, src) -> list[Scene]:
    edb = eurocom.parse(data)
    stem = posixpath.basename(path)[:-4]
    decoded: dict[int, np.ndarray | None] = {}
    by_hash = {el.hashcode: el for el in edb.entities}
    scenes: list[Scene] = []
    placed: set[int] = set()
    for mp in eurocom.maps(edb):
        pls = eurocom.placements(edb, mp)
        if not pls:
            continue
        scene = Scene(name=f"{stem}_map")
        mats: dict[int, int] = {}
        used = missing = foreign = 0
        foreign_mats: dict[str, dict] = {}
        for pl in pls:
            xform = (np.array(pl.scale), _rotation(pl.rotation), np.array(pl.position))
            el = by_hash.get(pl.object_ref)
            if el is not None:
                for m in eurocom.mesh_entity(edb, el):
                    _add_strips(edb, m, scene, mats, decoded, xform)
                placed.add(pl.object_ref)
                used += 1
                continue
            other = None
            if src is not None:
                where = _index(src).get(pl.object_ref)
                other = _foreign(src, where) if where else None
            if other is None:
                missing += 1
                continue
            oedb, ohash, odec = other
            oel = ohash.get(pl.object_ref)
            if oel is None:
                missing += 1
                continue
            omats = foreign_mats.setdefault(id(oedb), {})
            for m in eurocom.mesh_entity(oedb, oel):
                _add_strips(oedb, m, scene, omats, odec, xform)
            used += 1
            foreign += 1
        if not scene.primitives:
            continue
        scene.extras = {
            "format": "eurocom-map",
            "edb_version": edb.version,
            "placements": used,
            "foreign": foreign,
            "missing": missing,
            "triangles": sum(len(p.indices) // 3 for p in scene.primitives),
        }
        scenes.append(scene)
    for el in edb.entities:
        if el.hashcode in placed:
            continue
        for m in eurocom.mesh_entity(edb, el):
            scene = _entity_scene(edb, m, stem, decoded)
            if scene is not None:
                scenes.append(scene)
    return scenes
