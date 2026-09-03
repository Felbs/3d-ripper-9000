"""Nintendo SDK character-pipeline geometry palettes (``.gpl``, gcrip.formats.nin_gpl): one
Scene a palette, its display objects as primitives, textured from the ``.tpl`` the texture
header names - beside the palette (the same ``.arc``) first, then any file of that name."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import nin_gpl, tpl
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "nin_gpl"
_INDEX_ATTR = "_nin_gpl_basenames"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gpl") and nin_gpl.is_gpl(head, size)


def _basenames(src) -> dict[str, list[str]]:
    index = getattr(src, _INDEX_ATTR, None)
    if index is not None:
        return index
    index = {}
    for p in getattr(src, "by_path", {}) or {}:
        index.setdefault(p.lower().rsplit("/", 1)[-1], []).append(p)
    with contextlib.suppress(Exception):
        setattr(src, _INDEX_ATTR, index)
    return index


def _tpl_images(src, path: str, name: str, warnings: list[str]):
    """The decoded images of the named texture palette, nearest copy first."""
    if src is None or not hasattr(src, "by_path"):
        return []
    folder = posixpath.dirname(path)
    candidates = _basenames(src).get(name.lower(), [])
    candidates = sorted(candidates, key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in candidates:
        try:
            return tpl.parse(src.get(p))
        except Exception as e:  # noqa: BLE001 - try the next copy
            warnings.append(f"{p}: {e}")
    # Harvest Moon's characters name a palette that does not exist (ban_0.tpl) and ship the
    # images split over the .tpl files beside the model (ban_0_b0, ban_0_f0_e ...): the
    # texture indices count through those in name order
    stem = name.lower().rsplit(".", 1)[0]
    images = []
    for p in sorted(src.by_path):
        low = p.lower()
        if (
            posixpath.dirname(p) == folder
            and low.endswith(".tpl")
            and low.rsplit("/", 1)[-1].startswith(stem)
        ):
            with contextlib.suppress(Exception):
                images += tpl.parse(src.get(p))
    return images


def extract(data: bytes, path: str, src) -> list[Scene]:
    pal = nin_gpl.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += pal.warnings
    palettes: dict[str, list] = {}
    decoded: dict[tuple[str, int], str | None] = {}
    materials: dict[tuple[str | None, int | None], int] = {}
    for obj in pal.objects:
        for draw in obj.draws:
            key = (obj.tpl, draw.texture)
            if key not in materials:
                tex_key = None
                if obj.tpl and draw.texture is not None:
                    if obj.tpl not in palettes:
                        palettes[obj.tpl] = _tpl_images(src, path, obj.tpl, scene.warnings)
                    images = palettes[obj.tpl]
                    if key not in decoded:
                        decoded[key] = None
                        if draw.texture < len(images):
                            try:
                                rgba = images[draw.texture].decode()
                            except Exception as e:  # noqa: BLE001
                                scene.warnings.append(f"{obj.tpl}[{draw.texture}]: {e}")
                            else:
                                name = f"{obj.tpl.rsplit('.', 1)[0]}_{draw.texture:03d}"
                                scene.textures[name] = rgba
                                decoded[key] = name
                    tex_key = decoded[key]
                materials[key] = len(scene.materials)
                scene.materials.append(
                    MaterialDef(name=f"{obj.name}_{len(scene.materials)}", texture=tex_key)
                )
            scene.primitives.append(
                Primitive(
                    material=materials[key],
                    positions=np.ascontiguousarray(draw.positions, dtype=np.float32),
                    indices=draw.triangles.reshape(-1).astype(np.uint32),
                    normals=draw.normals,
                    uvs=draw.uvs,
                    colors=draw.colors,
                )
            )
    if not scene.primitives:
        if pal.warnings:
            raise nin_gpl.GplError("; ".join(pal.warnings[:3]))
        return []  # legitimate: an empty palette
    scene.extras = {"format": "nin_gpl", "objects": [o.name for o in pal.objects]}
    return [scene]
