"""Silicon Dreams / Gusto Games ``SDASSETF`` asset files (gcrip.formats.sdasset): Freestyle
Street Soccer's players (``Skins/<team>/<player>/<player>_Models.ast``, skinned over a
32-bone SKEL), whole teams (four players concatenated), crowd, stadiums
(``Stadiums/.../*_Models.ast``, 66 rigid models) and the ``*_textures.ast`` beside them.

One Scene per asset file segment: a team file yields four player scenes.  Textures come
from every ``*texture*.ast`` in the same directory (home kit first), matched by the
material's TEXTURED effect name, case-insensitively.  Texture files export as
textures-only scenes, which also keeps the ``gx`` fallback off them - unclaimed, both
kinds of file scanned as two-position noise meshes (the GUVE51 quality-audit finding).
"""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import sdasset
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "sdasset"
MAX_TEXTURE_FILES = 8


def detect(path: str, head: bytes, size: int) -> bool:
    return sdasset.is_sdasset(head)


def _sibling_textures(path: str, src) -> dict[str, np.ndarray]:
    """Decoded bitmaps from the texture files next to *path*, keyed by lower-case name."""
    out: dict[str, np.ndarray] = {}
    if src is None or not hasattr(src, "by_path"):
        return out
    folder = posixpath.dirname(path)
    names = [
        p
        for p in src.by_path
        if posixpath.dirname(p) == folder
        and p.lower().endswith(".ast")
        and "texture" in posixpath.basename(p).lower()
        and p != path
    ]
    # home kit before away kit, then whatever else is there
    names.sort(key=lambda p: ("home" not in p.lower(), p.lower()))
    for p in names[:MAX_TEXTURE_FILES]:
        try:
            data = src.get(p)
        except Exception:  # noqa: BLE001 - a missing sibling must not lose the model
            continue
        if not sdasset.is_sdasset(data[:8]):
            continue
        try:
            assets = sdasset.read(data)
        except sdasset.SdassetError:
            continue
        for asset in assets:
            for bm in asset.bitmaps:
                key = bm.name.lower()
                if key in out:
                    continue
                rgba = sdasset.decode_bitmap(bm)
                if rgba is not None:
                    out[key] = rgba
    return out


def _joints(skel: sdasset.Skeleton) -> list[Joint]:
    return [
        Joint(name, parent if 0 <= parent < len(skel.names) else None, t, r, s)
        for name, parent, (t, r, s) in zip(skel.names, skel.parents, skel.locals(), strict=True)
    ]


def _skin(weights: list, count: int, njoints: int) -> tuple[np.ndarray, np.ndarray]:
    joints = np.zeros((count, 4), np.uint16)
    w = np.zeros((count, 4), np.float32)
    for i, (bones, ws) in enumerate(weights[:count]):
        pairs = sorted(zip(ws, bones, strict=True), reverse=True)[:4]
        for k, (wk, bk) in enumerate(pairs):
            if 0 <= bk < njoints:
                joints[i, k] = bk
                w[i, k] = wk
    total = w.sum(axis=1, keepdims=True)
    fixed = np.where(total > 0, w / np.maximum(total, 1e-9), np.array([1.0, 0, 0, 0], np.float32))
    return joints, fixed.astype(np.float32)


def _scene(asset: sdasset.Asset, stem: str, textures: dict[str, np.ndarray]) -> Scene | None:
    scene = Scene(name=asset.name or stem)
    if asset.skeleton is not None:
        scene.joints = _joints(asset.skeleton)
    slots: dict[str | None, int] = {}

    def material(name: str) -> int:
        mat = asset.material(name)
        key = mat.texture.lower() if mat and mat.texture else None
        if key is not None and key not in textures:
            key = None
        if key in slots:
            return slots[key]
        tex = None
        if key is not None:
            tex = key[:64]
            scene.textures[tex] = textures[key]
        scene.materials.append(MaterialDef(name=name or "untextured", texture=tex))
        slots[key] = len(scene.materials) - 1
        return slots[key]

    total = 0
    skinned = 0
    for model in asset.models:
        for mesh in model.detail_meshes():
            vb = model.buffers.get(mesh.data_id)
            if vb is None or not mesh.strips:
                continue
            tri = sdasset.triangulate(mesh.strips)
            if not len(tri) or tri.max() >= len(vb.positions):
                continue
            used, inverse = np.unique(tri.reshape(-1), return_inverse=True)
            prim = Primitive(
                material=material(mesh.name),
                positions=np.ascontiguousarray(vb.positions[used]),
                indices=inverse.astype(np.uint32),
                normals=None if vb.normals is None else np.ascontiguousarray(vb.normals[used]),
                uvs=None if vb.uvs is None else np.ascontiguousarray(vb.uvs[used]),
                colors=None
                if vb.colors is None
                else np.ascontiguousarray(vb.colors[used].astype(np.float32) / 255.0),
            )
            weights = model.weights.get(mesh.data_id)
            if scene.joints and weights:
                joints, w = _skin(weights, len(vb.positions), len(scene.joints))
                prim.joints = np.ascontiguousarray(joints[used])
                prim.weights = np.ascontiguousarray(w[used])
                skinned += 1
            scene.primitives.append(prim)
            total += len(tri)
    if not scene.primitives:
        return None
    scene.extras = {
        "format": "sdasset",
        "models": [m.name for m in asset.models],
        "triangles": total,
        "skinned_meshes": skinned,
        "textures_bound": len(scene.textures),
        "note": "model space is Z-up as authored",
    }
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    try:
        assets = sdasset.read(data)
    except sdasset.SdassetError:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "asset"
    scenes: list[Scene] = []
    if any(a.models for a in assets):
        textures = _sibling_textures(path, src)
        for i, asset in enumerate(assets):
            if not asset.models:
                continue
            scene = _scene(asset, stem if len(assets) == 1 else f"{stem}#{i}", textures)
            if scene is not None:
                scenes.append(scene)
    else:
        pictures = Scene(name=stem)
        for asset in assets:
            for bm in asset.bitmaps:
                rgba = sdasset.decode_bitmap(bm)
                if rgba is not None:
                    pictures.textures[bm.name[:64] or f"tex{len(pictures.textures)}"] = rgba
        if pictures.textures:
            pictures.extras = {"textures_only": True, "format": "sdasset"}
            scenes.append(pictures)
    return scenes
