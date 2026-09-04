"""Batman: Rise of Sin Tzu ``geoobj.bin`` (gcrip.formats.ubi_geoobj): a Scene an object, a
primitive an element, named by the ``.gmt`` material file and material the element cites."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import ubi_geoobj
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ubi_geoobj"


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".tsd"):
        return ubi_geoobj.is_tsd(head, size)
    return low.endswith("geoobj.bin") and ubi_geoobj.is_geoobj(head, size)


def _texture_scene(data: bytes, path: str) -> list[Scene]:
    rgba = ubi_geoobj.tsd(data)
    if rgba is None:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name[:64]] = rgba
    scene.extras = {"textures_only": True, "format": "ubi_tsd"}
    return [scene]


def _stem(element: ubi_geoobj.Element) -> str:
    # "bat_cycle/bat_cycle.gmt^GameMaterial:Wheels" -> "bat_cycle"
    head = element.name.split("^", 1)[0]
    return posixpath.basename(head).rsplit(".", 1)[0] or "object"


def _picture(src, path: str, material: str, cache: dict) -> np.ndarray | None:
    """The sibling ``<material>.tsd`` of the same archive - Sin Tzu names its pictures after
    the materials that sample them (``bikeBody2`` -> ``bikebody2.tsd``)."""
    key = material.lower()
    if key in cache:
        return cache[key]
    rgba = None
    by_path = getattr(src, "by_path", None) or {}
    root = path.split("/binary/", 1)[0] if "/binary/" in path else posixpath.dirname(path)
    want = f"/{key}.tsd"
    for p in by_path:
        if p.startswith(root) and p.lower().endswith(want):
            try:
                rgba = ubi_geoobj.tsd(src.get(p))
            except Exception:  # noqa: BLE001 - the mesh is still worth having untextured
                rgba = None
            if rgba is not None:
                break
    cache[key] = rgba
    return rgba


def extract(data: bytes, path: str, src) -> list[Scene]:
    if path.lower().endswith(".tsd"):
        return _texture_scene(data, path)
    out = []
    seen: dict[str, int] = {}
    pictures: dict = {}
    for k, model in enumerate(ubi_geoobj.models(data)):
        if not model.elements:
            continue
        stem = _stem(model.elements[0])
        seen[stem] = seen.get(stem, 0) + 1
        name = stem if seen[stem] == 1 else f"{stem}_{seen[stem]}"
        scene = Scene(name=name)
        for e in model.elements:
            material = e.name.split(":")[-1] or "material"
            rgba = _picture(src, path, material, pictures) if src is not None else None
            texture = None
            if rgba is not None:
                texture = material.lower()[:64]
                scene.textures[texture] = rgba
            scene.materials.append(MaterialDef(name=material, texture=texture))
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=e.positions,
                    indices=e.indices,
                    normals=e.normals,
                    uvs=e.uvs,
                    colors=e.colors,
                )
            )
        scene.extras = {"format": "ubi_geoobj", "record": k, "elements": len(model.elements)}
        out.append(scene)
    return out
