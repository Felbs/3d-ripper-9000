"""Terminal Reality ``_smf`` static meshes (gcrip.formats.tr_smf): the geometry inside the
``.PKG`` packages of BloodRayne, Blowout and RoadKill.  Each display list becomes one
primitive; the texture is bound by the material record's ``.tif`` name, which is exactly the
name the package's ``1tex`` chunks carry, so the sibling textures resolve."""

from __future__ import annotations

import posixpath

from gcrip.formats import tr_smf
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "tr_smf"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".smf") and tr_smf.is_smf(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    parsed = tr_smf.parse(data)
    if parsed is None or not parsed.meshes:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    slots: dict[str, int] = {}
    for mesh in parsed.meshes:
        texture = mesh.material
        if texture not in slots:
            slots[texture] = len(scene.materials)
            stem = texture.rsplit(".", 1)[0] if texture else ""
            scene.materials.append(MaterialDef(name=stem or name, texture=stem or None))
        scene.primitives.append(
            Primitive(
                material=slots[texture],
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
            )
        )
    scene.extras = {"format": "tr_smf", "materials": parsed.materials}
    if len(set(parsed.materials)) > 1:
        scene.warnings.append(
            f"{len(parsed.materials)} texture records; per-primitive material binding "
            "is not resolved yet, so the primitives are left untextured"
        )
    return [scene]
