"""Billy Hatcher and the Giant Egg: ``.prd`` packages (container, gcrip.formats.prd), ``.arc``
Ginja object trees with embedded or sibling GVM textures (gcrip.formats.billy) and ``.lnd``
stage terrain (gcrip.formats.billy_lnd)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import billy, billy_lnd, gvr, prd
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
    low = path.lower()
    if low.endswith(".lnd"):
        return billy_lnd.is_lnd(head, size)
    return low.endswith(".arc") and billy.is_arc(head, size)


def _terrain(data: bytes, name: str) -> list[Scene]:
    level = billy_lnd.parse(data)
    if not level.meshes:
        return []
    scene = Scene(name=name)
    rgba = [t.rgba for t in level.textures]
    mats: dict[tuple[int, bool], int] = {}
    groups: dict[int, list] = {}
    for m in level.meshes:
        key = (m.material, m.translucent)
        if key not in mats:
            ti = level.material_texture.get(m.material, -1)
            tex = None
            if 0 <= ti < len(rgba) and rgba[ti] is not None:
                tex = level.texnames[ti] if ti < len(level.texnames) else f"tex{ti:03d}"
                scene.textures.setdefault(tex, rgba[ti])
            scene.materials.append(
                MaterialDef(
                    name=f"mat{m.material:03d}" if tex is None else tex,
                    texture=tex,
                    alpha_blend=m.translucent,
                    double_sided=True,
                )
            )
            mats[key] = len(scene.materials) - 1
        groups.setdefault(mats[key], []).append(m)
    for mi, meshes in groups.items():
        base = 0
        idx = []
        for m in meshes:
            idx.append(m.indices + base)
            base += len(m.positions)
        has_nrm = all(m.normals is not None for m in meshes)
        has_col = all(m.colors is not None for m in meshes)
        has_uv = all(m.uvs is not None for m in meshes)
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=np.concatenate([m.positions for m in meshes]),
                indices=np.concatenate(idx).astype(np.uint32),
                normals=np.concatenate([m.normals for m in meshes]) if has_nrm else None,
                uvs=np.concatenate([m.uvs for m in meshes]) if has_uv else None,
                colors=np.concatenate([m.colors for m in meshes]) if has_col else None,
            )
        )
    scene.extras = {
        "format": "billy-lnd",
        "display_lists": len(level.meshes),
        "textures": len(level.textures),
    }
    return [scene]


def _sibling_gvm(src, path: str) -> list[gvr.Texture]:
    """``ar_ene_bee.arc`` draws with ``ene_bee.gvm`` from the same package."""
    by_path = getattr(src, "by_path", None) or {}
    folder, _, base = path.rpartition("/")
    stem = base.rsplit(".", 1)[0]
    stems = [stem, stem[3:] if stem.startswith("ar_") else stem]
    for st in stems:
        for cand in (f"{folder}/{st}.gvm" if folder else f"{st}.gvm", f"{path}.gvm"):
            if cand in by_path:
                try:
                    blob = src.get(cand)
                except Exception:  # noqa: BLE001
                    continue
                if gvr.is_gvm(blob[:4]):
                    return gvr.gvm_textures(blob)
    return []


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    if path.lower().endswith(".lnd"):
        return _terrain(data, name)
    scenes, textures = billy.scenes(data, name)
    if not textures and src is not None:
        textures = _sibling_gvm(src, path)
    rgba = {t.name: t.rgba for t in textures if t.rgba is not None}
    if not scenes:
        if not rgba:
            return []
        scene = Scene(name=name)
        scene.textures.update(rgba)
        scene.extras = {"format": "billy-arc", "textures_only": True}
        return [scene]
    for scene in scenes:
        for m in scene.materials:
            if m.texture and m.texture in rgba:
                scene.textures.setdefault(m.texture, rgba[m.texture])
                m.alpha_blend = m.alpha_blend or bool(np.any(rgba[m.texture][..., 3] < 255))
            elif m.texture:
                m.texture = None
    return scenes
