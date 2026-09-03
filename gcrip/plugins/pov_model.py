"""Point of View's ``PHM`` models (Smashing Drive; gcrip.formats.pov_model): one Scene a
model with a primitive per mesh and material, textured from the ``TIM`` records of the same
``.wad`` (or any wad on the disc) by the texture-def names the materials map to."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import pov_model
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "pov_model"
_INDEX_ATTR = "_pov_tim_index"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".phm") and pov_model.is_model(head, size)


def _tim_index(src) -> dict[str, list[str]]:
    """upper-case record name -> TIM member paths, built once per source."""
    index = getattr(src, _INDEX_ATTR, None)
    if index is not None:
        return index
    index = {}
    for p in getattr(src, "by_path", {}) or {}:
        if p.lower().endswith(".tim"):
            stem = p.rsplit("/", 1)[-1][:-4].upper()
            index.setdefault(stem, []).append(p)
    with contextlib.suppress(Exception):
        setattr(src, _INDEX_ATTR, index)
    return index


def _texture(src, path: str, name: str, warnings: list[str]) -> np.ndarray | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    candidates = _tim_index(src).get(name.upper(), [])
    for p in sorted(candidates, key=lambda p: (posixpath.dirname(p) != folder, len(p))):
        try:
            for t in pov_model.parse_tim(src.get(p)):
                if t.rgba is not None:
                    return t.rgba
        except Exception as e:  # noqa: BLE001 - try the next copy
            warnings.append(f"{p}: {e}")
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = pov_model.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    materials: dict[int, int] = {}
    decoded: dict[str, str | None] = {}
    for mesh in model.meshes:
        for mi in np.unique(mesh.materials):
            mi = int(mi)
            if mi not in materials:
                key = None
                maps = model.materials[mi] if mi < len(model.materials) else []
                for ti in maps:
                    if ti >= len(model.texture_defs):
                        continue
                    name = model.texture_defs[ti]
                    if name not in decoded:
                        img = _texture(src, path, name, scene.warnings)
                        decoded[name] = None
                        if img is not None:
                            scene.textures[name] = img
                            decoded[name] = name
                    if decoded[name]:
                        key = decoded[name]
                        break
                materials[mi] = len(scene.materials)
                scene.materials.append(
                    MaterialDef(name=f"material_{mi}", texture=key, double_sided=True)
                )
            sel = mesh.materials == mi
            scene.primitives.append(
                Primitive(
                    material=materials[mi],
                    positions=model.positions,
                    indices=mesh.triangles[sel].reshape(-1).astype(np.uint32),
                    normals=model.normals,
                    uvs=model.uvs,
                    colors=model.colors,
                )
            )
    if not scene.primitives:
        if model.warnings:
            raise pov_model.PovError("; ".join(model.warnings[:3]))
        return []  # legitimate: a model with no strips (collision-only)
    scene.extras = {
        "format": "pov_model",
        "bones": len(model.bones),
        "meshes": [m.name for m in model.meshes],
    }
    return [scene]
