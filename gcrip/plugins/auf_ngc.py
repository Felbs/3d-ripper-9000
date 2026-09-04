"""007: Agent Under Fire ``maps/*.ngc`` (gcrip.formats.auf_ngc): the level's world geometry
as one Scene - a primitive per shader, textured from the map's own ``restxtrs`` chunk."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import auf_ngc
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "auf_ngc"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".ngc") and auf_ngc.is_map(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    m = auf_ngc.parse(data)
    if m is None or not m.surfaces:
        return []  # legitimate: a chunk file without an ngcsurfs lump (a sound or resource pack)
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "map"
    scene = Scene(name=stem)
    scene.warnings.extend(m.warnings)
    by_shader: dict[int, list[auf_ngc.Surface]] = {}
    for s in m.surfaces:
        by_shader.setdefault(s.shader, []).append(s)
    for shader, group in sorted(by_shader.items()):
        tex_id = m.shader_textures.get(shader)
        key = None
        if tex_id is not None and tex_id in m.textures:
            key = f"tex_{tex_id:08x}"
            if key not in scene.textures:
                rgba = auf_ngc.decode_texture(m, m.textures[tex_id])
                if rgba is not None:
                    scene.textures[key] = rgba
            if key not in scene.textures:
                key = None
        scene.materials.append(MaterialDef(name=key or f"shader_{shader}", texture=key))
        material = len(scene.materials) - 1
        pos, uv, idx = [], [], []
        base = 0
        for s in group:
            pos.append(s.positions)
            uv.append(s.uvs)
            idx.append(s.indices + base)
            base += len(s.positions)
        scene.primitives.append(
            Primitive(
                material=material,
                positions=np.concatenate(pos),
                indices=np.concatenate(idx).astype(np.uint32),
                uvs=np.concatenate(uv),
            )
        )
    scene.extras = {
        "format": "auf_ngc",
        "chunks": m.chunks,
        "surfaces": len(m.surfaces),
        "shaders": len(by_shader),
        "textures_in_map": len(m.textures),
    }
    return [scene]
