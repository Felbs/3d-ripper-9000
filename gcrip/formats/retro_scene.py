"""Retro model (CMDL / MREA world model) -> ripcore Scene: display lists become per-material
triangle primitives with deduplicated vertices; Z-up Retro coordinates become Y-up."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from gcrip.formats import retro_cmdl as cmdl
from gcrip.formats.j3d import triangulate
from ripcore.scene import MaterialDef, Primitive, Scene

TextureLookup = Callable[[int], np.ndarray | None]


def _z_up_to_y_up(a: np.ndarray) -> np.ndarray:
    out = np.empty_like(a)
    out[:, 0] = a[:, 0]
    out[:, 1] = a[:, 2]
    out[:, 2] = -a[:, 1]
    return out


def texture_key(txtr_id: int) -> str:
    return f"0x{txtr_id:08X}"


def diffuse_of(m: cmdl.Material, mset: cmdl.MaterialSet) -> tuple[int, int] | None:
    """(TXTR id, UV set) of the material's base-color stage, or None."""
    d = m.diffuse()
    if d is None or d[0] >= len(mset.texture_ids):
        return None
    return mset.texture_ids[d[0]], d[1]


def material_def(
    m: cmdl.Material, mset: cmdl.MaterialSet, index: int, has_texture: bool
) -> MaterialDef:
    d = diffuse_of(m, mset)
    tex = texture_key(d[0]) if d and has_texture else None
    return MaterialDef(
        name=f"mat{index:02d}" + (f"_{tex}" if tex else ""),
        texture=tex,
        alpha_blend=m.transparent,
        double_sided=False,
        unlit=not m.lit,
    )


def build_scene(
    model: cmdl.Model,
    name: str,
    lookup: TextureLookup,
    *,
    scene: Scene | None = None,
    material_set: int = 0,
    transform: np.ndarray | None = None,
    skin: tuple[np.ndarray, np.ndarray] | None = None,
    slots: dict[int, int] | None = None,
) -> Scene:
    """Append `model`'s geometry to `scene` (or a new one). `lookup(txtr_id)` returns a
    decoded RGBA texture or None. `transform` is a (3,4) or (4,4) matrix in Retro space.
    `skin` = per-position (joints (N,4) u16, weights (N,4) f32) from a CSKR. `slots` maps
    material index -> scene material slot, shared by callers that merge several models
    drawn with the same material set (MREA world models)."""
    scene = scene or Scene(name=name)
    scene.warnings += model.warnings
    if not model.material_sets:
        scene.warnings.append("no material set")
        return scene
    mset = model.material_sets[min(material_set, len(model.material_sets) - 1)]
    # fetch textures once per set
    for m in mset.materials:
        d = diffuse_of(m, mset)
        if d is None:
            continue
        key = texture_key(d[0])
        if key in scene.textures:
            continue
        try:
            img = lookup(d[0])
        except Exception as e:  # noqa: BLE001 - one bad texture must not kill the model
            scene.warnings.append(f"texture {key}: {type(e).__name__}: {e}")
            img = None
        if img is not None:
            scene.textures[key] = img
    positions = model.positions
    normals = model.normals
    if transform is not None:
        t = np.asarray(transform, np.float64)
        positions = positions @ t[:3, :3].T + t[:3, 3]
        normals = normals @ np.linalg.inv(t[:3, :3]).T if len(normals) else normals
    positions = _z_up_to_y_up(positions.astype(np.float32))
    normals = _z_up_to_y_up(normals.astype(np.float32)) if len(normals) else normals

    # per material: column stacks (pos, nrm, uv, col) + triangle indices
    buckets: dict[int, dict] = {}
    mat_slot: dict[int, int] = slots if slots is not None else {}
    n_pos, n_nrm, n_uv, n_suv, n_col = (
        len(positions),
        len(normals),
        len(model.uvs),
        len(model.short_uvs),
        len(model.colors),
    )
    bad = 0
    for si, surf in enumerate(model.surfaces):
        if surf.material >= len(mset.materials):
            scene.warnings.append(f"surface {si}: material {surf.material} out of range")
            continue
        m = mset.materials[surf.material]
        try:
            prims = cmdl.parse_display_list(surf.dl, m)
        except cmdl.CmdlError as e:
            scene.warnings.append(f"surface {si}: {e}")
            continue
        d = diffuse_of(m, mset)
        uv_set = d[1] if d else None
        b = buckets.setdefault(
            surf.material, {"cols": [], "tris": [], "n": 0, "uv": False, "col": False}
        )
        for _op, fmt, arr in prims:
            names = arr.dtype.names or ()
            count = len(arr)
            if count == 0 or "pos" not in names:
                continue
            pos_i = arr["pos"].astype(np.int64)
            nrm_i = arr["nrm"].astype(np.int64) if "nrm" in names else np.full(count, -1)
            uv_i = np.full(count, -1)
            uv_short = np.zeros(count, bool)
            if uv_set is not None and f"tex{uv_set}" in names:
                uv_i = arr[f"tex{uv_set}"].astype(np.int64)
                if uv_set == 0 and fmt == 2 and n_suv:
                    uv_short[:] = True
                b["uv"] = True
            col_i = arr["col0"].astype(np.int64) if "col0" in names else np.full(count, -1)
            if "col0" in names:
                b["col"] = True
            # range guards
            oob = pos_i >= n_pos
            if oob.any():
                bad += int(oob.sum())
                pos_i = np.where(oob, 0, pos_i)
            nrm_i = np.where(nrm_i >= n_nrm, -1, nrm_i)
            uv_lim = np.where(uv_short, n_suv, n_uv)
            uv_i = np.where(uv_i >= uv_lim, -1, uv_i)
            col_i = np.where(col_i >= n_col, -1, col_i)
            cols = np.stack([pos_i, nrm_i, uv_i, uv_short.astype(np.int64), col_i], axis=1)
            tris = triangulate_prim(_op, count)
            if len(tris) == 0:
                continue
            b["cols"].append(cols)
            b["tris"].append(tris + b["n"])
            b["n"] += count
    if bad:
        scene.warnings.append(f"{bad} vertex indices out of range (clamped)")

    for mi, b in buckets.items():
        if not b["cols"]:
            continue
        cols = np.concatenate(b["cols"])
        tris = np.concatenate(b["tris"])
        uniq, inv = np.unique(cols, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        indices = inv[tris.reshape(-1)].astype(np.uint32)
        pos = positions[uniq[:, 0]]
        nrm = None
        if n_nrm:
            nrm = np.where((uniq[:, 1] >= 0)[:, None], normals[np.maximum(uniq[:, 1], 0)], 0.0)
            nrm = nrm.astype(np.float32)
        uvs = None
        if b["uv"]:
            sel = np.maximum(uniq[:, 2], 0)
            f_uv = model.uvs[np.minimum(sel, max(n_uv - 1, 0))] if n_uv else np.zeros((len(sel), 2))
            s_uv = (
                model.short_uvs[np.minimum(sel, max(n_suv - 1, 0))]
                if n_suv
                else np.zeros((len(sel), 2))
            )
            uvs = np.where((uniq[:, 3] == 1)[:, None], s_uv, f_uv).astype(np.float32)
            uvs[uniq[:, 2] < 0] = 0.0
        colors = None
        if b["col"] and n_col:
            colors = model.colors[np.maximum(uniq[:, 4], 0)].astype(np.float32)
            colors[uniq[:, 4] < 0] = 1.0
        m = mset.materials[mi]
        slot = mat_slot.get(mi)
        if slot is None:
            d = diffuse_of(m, mset)
            has_tex = bool(d) and texture_key(d[0]) in scene.textures
            slot = len(scene.materials)
            mat_slot[mi] = slot
            scene.materials.append(material_def(m, mset, mi, has_tex))
        joints = weights = None
        if skin is not None:
            joints = skin[0][uniq[:, 0]]
            weights = skin[1][uniq[:, 0]]
        scene.primitives.append(
            Primitive(slot, pos, indices, nrm, uvs, colors, joints=joints, weights=weights)
        )
    return scene


def triangulate_prim(op: int, count: int) -> np.ndarray:
    tris = triangulate(op, count)
    # GX strips/fans wind clockwise-front in Retro's data; flip to glTF's CCW
    if len(tris):
        tris = tris[:, [0, 2, 1]]
    return tris
