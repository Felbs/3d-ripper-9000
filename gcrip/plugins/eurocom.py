"""Eurocom EngineX discs (Sphinx and the Cursed Mummy, Spyro: A Hero's Tail, Batman Begins,
Buffy: Chaos Bleeds, Robots, Ice Age 2): ``Filelist.000`` is the container (its directory is
the sibling ``Filelist.bin``) and the ``GEOM`` ``.edb`` members hold the models and
textures (gcrip.formats.eurocom).  One Scene per mesh entity."""

from __future__ import annotations

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


def extract(data: bytes, path: str, src) -> list[Scene]:
    edb = eurocom.parse(data)
    stem = posixpath.basename(path)[:-4]
    decoded: dict[int, np.ndarray | None] = {}
    scenes = []
    for el in edb.entities:
        for m in eurocom.mesh_entity(edb, el):
            scene = Scene(name=f"{stem}_{m.hashcode:08x}")
            mats: dict[int, int] = {}
            for s in m.strips:
                if s.texture not in mats:
                    ti = m.textures[s.texture] if s.texture < len(m.textures) else s.texture
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
                    mats[s.texture] = len(scene.materials) - 1
                scene.primitives.append(
                    Primitive(
                        material=mats[s.texture],
                        positions=s.positions,
                        indices=s.indices,
                        normals=s.normals,
                        uvs=s.uvs,
                        colors=s.colors,
                    )
                )
            if scene.primitives:
                scene.extras = {
                    "format": "eurocom-edb",
                    "edb_version": edb.version,
                    "hashcode": f"{m.hashcode:08x}",
                    "strips": len(m.strips),
                }
                scenes.append(scene)
    return scenes
