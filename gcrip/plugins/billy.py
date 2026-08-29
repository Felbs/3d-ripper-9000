"""Billy Hatcher and the Giant Egg: ``.prd`` packages (container, gcrip.formats.prd) and
``.arc`` Ginja models with their embedded GVM textures (gcrip.formats.billy)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import billy, prd
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "billy"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".prd") and prd.is_prd(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    try:
        u = prd.unpack(data)
    except Exception:  # noqa: BLE001
        return []
    return [(m.name, u[m.offset : m.offset + m.size]) for m in prd.members(u)]


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".arc") and billy.is_arc(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    meshes, textures = billy.parse(data)
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    if not meshes:
        for i, t in enumerate(textures):
            if t.rgba is not None:
                scene.textures[f"{i}_{t.name}"] = t.rgba
        if not scene.textures:
            return []
        scene.extras = {"format": "billy-arc", "textures_only": True}
        return [scene]
    mats: dict[int, int] = {}
    for m in meshes:
        if m.texture not in mats:
            key = None
            if 0 <= m.texture < len(textures) and textures[m.texture].rgba is not None:
                key = f"{m.texture}_{textures[m.texture].name}"
                scene.textures.setdefault(key, textures[m.texture].rgba)
            alpha = bool(key) and bool(np.any(scene.textures[key][..., 3] < 255))
            scene.materials.append(
                MaterialDef(
                    name=f"tex{m.texture}", texture=key, alpha_blend=alpha, double_sided=True
                )
            )
            mats[m.texture] = len(scene.materials) - 1
        scene.primitives.append(
            Primitive(
                material=mats[m.texture],
                positions=m.positions,
                indices=m.indices,
                normals=m.normals,
                uvs=m.uvs,
            )
        )
    scene.extras = {"format": "billy-arc", "meshes": len(meshes), "textures": len(textures)}
    return [scene]
