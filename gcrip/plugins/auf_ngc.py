"""007: Agent Under Fire ``maps/*.ngc`` (gcrip.formats.auf_ngc): the level's world geometry
as one Scene - a primitive per shader - and every ``.gcm`` model of its ``restable`` (heads,
weapons, props) as a Scene of its own, all textured from the map's ``restxtrs`` chunk."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import auf_ngc
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "auf_ngc"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".ngc") and auf_ngc.is_map(head, size)


def _bind(scene: Scene, m: auf_ngc.Map, tex_id: int | None, fallback: str) -> None:
    key = None
    if tex_id is not None and tex_id in m.textures:
        key = f"tex_{tex_id:08x}"
        if key not in scene.textures:
            rgba = auf_ngc.decode_texture(m, m.textures[tex_id])
            if rgba is not None:
                scene.textures[key] = rgba
        if key not in scene.textures:
            key = None
    scene.materials.append(MaterialDef(name=key or fallback, texture=key))


def _models(m: auf_ngc.Map) -> list[Scene]:
    out = []
    for name, at, size in auf_ngc.resources(m.resource_chunk):
        if not name.lower().endswith(".gcm"):
            continue
        mdl = auf_ngc.model(m.resource_chunk[at : at + size], name)
        if mdl is None or not mdl.batches:
            continue
        scene = Scene(name=posixpath.basename(name).rsplit(".", 1)[0])
        scene.warnings.extend(mdl.warnings)
        for b in mdl.batches:
            _bind(scene, m, auf_ngc.shader_by_id(m, b.shader_id), f"shader_{b.shader_id:08x}")
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=b.positions,
                    indices=b.indices,
                    normals=b.normals,
                    uvs=b.uvs,
                )
            )
        scene.extras = {"format": "auf_ngc", "kind": "model", "resource": name}
        out.append(scene)
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    m = auf_ngc.parse(data)
    if m is None:
        return []
    models = _models(m)
    if not m.surfaces:
        return models  # legitimate when empty: a chunk file with neither world nor models
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "map"
    scene = Scene(name=stem)
    scene.warnings.extend(m.warnings)
    by_shader: dict[int, list[auf_ngc.Surface]] = {}
    for s in m.surfaces:
        by_shader.setdefault(s.shader, []).append(s)
    for shader, group in sorted(by_shader.items()):
        _bind(scene, m, m.shader_textures.get(shader), f"shader_{shader}")
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
        "models": len(models),
    }
    return [scene, *models]
