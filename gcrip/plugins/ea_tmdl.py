"""EA Tiburon ``TMdl`` models (Madden NFL, NCAA Football, NFL Street, NASCAR Thunder) - one
Scene a file; textures from the model's own ``Text`` pack, matched by the material's
15-character texture name."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import ea_terf, ea_tmdl
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_tmdl"


def detect(path: str, head: bytes, size: int) -> bool:
    return ea_tmdl.is_tmdl(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = ea_tmdl.parse(data)
    if not model.meshes and model.texture_pack is None:
        return []  # locator / sun-position files carry no geometry
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    name = model.name.rsplit(".", 1)[0] if model.name else stem
    scene = Scene(name=name or stem)
    if model.texture_pack is not None:
        try:
            for tex_name, rgba, warnings in ea_terf.mmap_pack(model.texture_pack):
                scene.warnings += warnings
                if rgba is not None and tex_name:
                    scene.textures[tex_name] = rgba
        except ValueError as exc:
            scene.warnings.append(f"texture pack: {exc}")
    for i, m in enumerate(model.materials):
        texture = m.texture if m.texture in scene.textures else None
        scene.materials.append(MaterialDef(name=m.name or f"material_{i}", texture=texture))
    if not scene.materials:
        scene.materials.append(MaterialDef(name="material", texture=None))
    dropped: list[str] = []
    for mesh in model.meshes:
        try:
            md = ea_tmdl.mesh_data(data, model, mesh)
        except ea_tmdl.TmdlError as exc:
            dropped.append(str(exc))
            continue
        material = md.material if 0 <= md.material < len(scene.materials) else 0
        scene.primitives.append(
            Primitive(
                material=material,
                positions=md.positions,
                indices=md.indices,
                normals=None if md.normals is None else np.ascontiguousarray(md.normals, dtype=np.float32),
                uvs=None if md.uvs is None else np.ascontiguousarray(md.uvs, dtype=np.float32),
                colors=None if md.colors is None else np.ascontiguousarray(md.colors, dtype=np.uint8),
            )
        )
    if not scene.primitives:
        if scene.textures:
            scene.materials = [MaterialDef(name=k, texture=k) for k in scene.textures]
            scene.extras = {"textures_only": True}
            return [scene]
        raise ea_tmdl.TmdlError(f"{path}: no triangles" + (f" ({dropped[0]})" if dropped else ""))
    if dropped:
        scene.warnings.append(f"{len(dropped)} meshes did not read: {dropped[0]}")
    return [scene]
