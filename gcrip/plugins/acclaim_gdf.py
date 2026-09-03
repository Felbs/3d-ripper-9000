"""Acclaim ``.GDF`` meshes (All-Star Baseball 2002/2003/2004) - one Scene a file, one
primitive a material group.  Textures already ship through ``plugins.asb_tex``."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import acclaim_gdf
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "acclaim_gdf"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith((".gdf", ".skn")) and acclaim_gdf.is_gdf(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = acclaim_gdf.model(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0] or model.name
    scene = Scene(name=model.name or stem)
    for name in model.materials or ["material"]:
        scene.materials.append(MaterialDef(name=name, texture=None))
    dropped: list[str] = []
    for mesh in model.meshes:
        try:
            pos = acclaim_gdf.positions(data, model, mesh)
        except acclaim_gdf.GdfError as exc:
            dropped.append(str(exc))
            continue
        for gi in range(mesh.first_group, min(mesh.first_group + mesh.groups, len(model.groups))):
            group = model.groups[gi]
            tris = acclaim_gdf.triangles(data, model, mesh, group)
            if not tris:
                continue
            material = group.material if 0 <= group.material < len(scene.materials) else 0
            scene.primitives.append(
                Primitive(
                    material=material,
                    positions=np.ascontiguousarray(pos, dtype=np.float32),
                    indices=np.asarray(tris, dtype=np.uint32).reshape(-1),
                )
            )
    if not scene.primitives:
        raise acclaim_gdf.GdfError(
            f"{path}: no triangles" + (f" ({dropped[0]})" if dropped else "")
        )
    if dropped:
        scene.warnings.append(f"{len(dropped)} meshes did not read: {dropped[0]}")
    return [scene]
