"""Krome ``GC01`` models (gcrip.formats.krome_gc01): Jimmy Neutron: Jet Fusion's ``.mdl`` +
``.mdg`` pairs, a Scene a model with a primitive per subobject material, textured by the
material's name against the archive's ``.tex`` files (gcrip.plugins.mdl2 decodes them)."""

from __future__ import annotations

import posixpath

from gcrip.formats import krome_gc01
from gcrip.plugins.mdl2 import _gtx_index, _texture
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "krome_gc01"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".mdl") and krome_gc01.is_gc01(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = path[:-4]
    mdg = None
    for cand in (stem + ".mdg", stem + ".MDG"):
        try:
            mdg = src.get(cand)
            break
        except Exception:  # noqa: BLE001 - the other case next
            continue
    if mdg is None:
        return []  # legitimate: the geometry file is not on the disc
    model = krome_gc01.parse(data, mdg)
    scene = Scene(name=posixpath.basename(stem))
    scene.warnings += model.warnings
    lookup = _gtx_index(src, ".tex")
    slots: dict[str, int] = {}
    for part in model.parts:
        if part.material not in slots:
            tex = _texture(src, scene, lookup, part.material)
            slots[part.material] = len(scene.materials)
            scene.materials.append(
                MaterialDef(name=part.material or part.subobject, texture=tex, double_sided=True)
            )
        scene.primitives.append(
            Primitive(
                material=slots[part.material],
                positions=part.positions,
                indices=part.indices,
                normals=part.normals,
                uvs=part.uvs,
                colors=part.colors,
            )
        )
    if not scene.primitives:
        return []  # legitimate: every list was refused, with a warning each
    scene.extras = {
        "format": "krome_gc01",
        "subobjects": sorted({p.subobject for p in model.parts}),
        "refpoints": model.refpoints,
    }
    return [scene]
