"""Avalanche Software DBL / DBU / MDB databases (Tak 1-3, Chicken Little, DBZ Sagas, Rugrats:
Royal Ransom): mesh records with embedded GX display lists, CI4 / CI8 / CMPR textures and
material lists (gcrip.formats.dbl_mesh)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import dbl, dbl_mesh
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "dbl"


def detect(path: str, head: bytes, size: int) -> bool:
    return size >= 0x100 and dbl.is_dbl(posixpath.basename(path), head)


def _texture_for(
    idx: int, model: dbl_mesh.Model, rgba: dict[str, np.ndarray]
) -> tuple[str, str | None]:
    """Material index -> (material name, texture name) for one model."""
    names = [t.name for t in model.textures if t.name in rgba]
    mat = model.materials[idx] if 0 <= idx < len(model.materials) else f"mat{idx:03d}"
    stem = mat.rsplit(".", 1)[0].lower()
    for n in names:
        if n.lower() == stem:
            return mat, n
    if 0 <= idx < len(names):
        return mat, names[idx]
    if len(names) == 1 and len(model.materials) <= 1:
        return mat, names[0]
    return mat, None


def extract(data: bytes, path: str, src) -> list[Scene]:
    base = posixpath.basename(path).rsplit(".", 1)[0]
    scenes: list[Scene] = []
    used: dict[str, int] = {}
    for model in dbl_mesh.models(data):
        rgba = {t.name: t.rgba for t in model.textures if t.rgba is not None}
        meshes = [m for rec in model.records for m in rec.meshes]
        one_based = bool(meshes) and all(m.material >= 1 for m in meshes)
        if not model.records and rgba:
            scene = Scene(name=f"{base}_textures")
            scene.textures.update(rgba)
            scene.extras = {"format": "avalanche-dbl", "textures_only": True}
            scenes.append(scene)
            continue
        for rec in model.records:
            name = rec.name if rec.name not in ("", "None") else base
            if name in used:
                used[name] += 1
                name = f"{name}_{used[name]}"
            else:
                used[name] = 0
            scene = Scene(name=name)
            mats: dict[int, int] = {}
            for m in rec.meshes:
                idx = m.material - 1 if one_based else m.material
                if idx not in mats:
                    mat, tex = _texture_for(idx, model, rgba)
                    blend = False
                    if tex is not None:
                        scene.textures.setdefault(tex, rgba[tex])
                        blend = bool(np.any(rgba[tex][..., 3] < 255))
                    scene.materials.append(
                        MaterialDef(name=mat, texture=tex, alpha_blend=blend, double_sided=True)
                    )
                    mats[idx] = len(scene.materials) - 1
                scene.primitives.append(
                    Primitive(
                        material=mats[idx],
                        positions=m.positions,
                        indices=m.indices.astype(np.uint32),
                        normals=m.normals,
                        uvs=m.uvs,
                    )
                )
            scene.extras = {
                "format": "avalanche-dbl",
                "display_lists": len(rec.meshes),
                "materials": len(model.materials),
                "textures": len(model.textures),
                "bones": len({b for m in rec.meshes for b in m.bones}),
            }
            scenes.append(scene)
    return scenes
