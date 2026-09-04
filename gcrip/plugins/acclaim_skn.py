"""Acclaim ``.SKN`` skinned characters (gcrip.formats.acclaim_skn) - All-Star Baseball
player bodies, hands and mascots.  One Scene a file, one primitive a geom, positions already
in model space (bind pose): the format stores no bone rest transforms - the runtime XF
matrices are ``boneWorld x inverseBind`` - so the baked pose is what there is, and the bone
names ride along in ``extras``.  Textures ship separately through ``plugins.asb_tex``."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import acclaim_skn
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "acclaim_skn"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".skn") and acclaim_skn.is_skn(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = acclaim_skn.model(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "skn"
    scene = Scene(name=model.name or stem)
    for i, name in enumerate(model.materials):
        scene.materials.append(MaterialDef(name=name or f"material{i}", texture=None))
    if not scene.materials:
        scene.materials.append(MaterialDef(name="material", texture=None))
    kinds: dict[str, int] = {}
    for mesh in acclaim_skn.meshes(data, model):
        material = mesh.material if 0 <= mesh.material < len(scene.materials) else 0
        kinds[mesh.kind] = kinds.get(mesh.kind, 0) + 1
        scene.primitives.append(
            Primitive(
                material=material,
                positions=np.ascontiguousarray(mesh.positions, dtype=np.float32),
                indices=np.asarray(mesh.indices, dtype=np.uint32).reshape(-1),
                normals=None if mesh.normals is None else np.asarray(mesh.normals, np.float32),
                uvs=None if mesh.uvs is None else np.asarray(mesh.uvs, np.float32),
            )
        )
    if not scene.primitives:
        raise acclaim_skn.SknError(f"{path}: no display list produced triangles")
    skipped = len(model.geoms) - len(scene.primitives)
    if skipped:
        total = len(model.geoms)
        scene.warnings.append(f"{skipped} of {total} geoms did not read (placeholders skipped)")
    scene.extras = {
        "format": "acclaim_skn",
        "bones": model.bones,
        "objects": [o.name for o in model.objects],
        "geom_kinds": kinds,
    }
    return [scene]
