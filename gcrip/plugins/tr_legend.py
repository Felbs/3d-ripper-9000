"""Tomb Raider: Legend DRM units (gcrip.formats.tr_legend) - the ``00 00 00 0e`` members
that ``cd_bigfile`` expands out of ``bigfile.dat``.  Members have no names, only hashes,
so the scenes are named by hash and model section."""

from __future__ import annotations

import posixpath

from gcrip.formats import tr_legend
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "tr_legend"


def detect(path: str, head: bytes, size: int) -> bool:
    return tr_legend.is_drm(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    secs = tr_legend.sections(data)
    if not secs:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "unit"
    scenes = []
    for m in tr_legend.models(data, secs):
        scene = Scene(name=f"{stem}_r{m.section}")
        scene.materials.append(MaterialDef(scene.name, None))
        scene.primitives.append(
            Primitive(
                material=0,
                positions=m.positions,
                indices=m.indices.reshape(-1),
                normals=m.normals,
                uvs=m.uvs,
                colors=m.colors,
            )
        )
        scene.extras = {
            "format": "tr_legend",
            "triangles": len(m.indices),
            "model_section": m.section,
            "declared_vertices": m.declared_vertices,
            "sections": len(secs),
            "uv_quantisation": "u8/255, unverified",
        }
        scenes.append(scene)
    return scenes
