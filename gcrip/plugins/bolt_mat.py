"""Mass Media material lists (``.bmat`` members of ``BOLT`` archives) as standalone textures."""

from __future__ import annotations

import posixpath

from gcrip.formats import bolt_model
from gcrip.plugins.bolt_model import texture_key
from ripcore.scene import MaterialDef, Scene

NAME = "bolt_mat"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".bmat") and size > 16 and bolt_model.is_material_list(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    ml = bolt_model.parse_material_list(data)
    stem = posixpath.basename(path).split(".")[0]
    scene = Scene(name=f"{stem}_{ml.name}" if ml.name else stem)
    for i, tex in enumerate(ml.textures):
        key = texture_key(i, tex.name)
        try:
            scene.textures[key] = tex.decode()
        except (ValueError, bolt_model.BoltModelError) as e:
            scene.warnings.append(f"{tex.name}: {e}")
            continue
        scene.materials.append(MaterialDef(name=key, texture=key))
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True}
    return [scene]
