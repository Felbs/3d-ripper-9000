"""Pikmin 1 (GPIE01) ``.mod`` models -> Scene.  Format details in gcrip.formats.pikmin_mod.

Geometry is drawn per "matpoly" (material, mesh) pair hanging off a joint.  Vertices of a
rigid matrix (a joint index in the vertex-matrix table) are stored in that joint's space;
vertices of an envelope (weighted) matrix are stored in bind space.  Both become bind-space
positions with JOINTS/WEIGHTS here, so glTF skinning reproduces the game's rest pose.
"""

from __future__ import annotations

import math

import numpy as np

from gcrip.formats import pikmin_mod as pm
from gcrip.formats.j3d import triangulate
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "pikmin"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".mod") and size >= 0x60 and pm.looks_like_mod(head)


# --- math ---------------------------------------------------------------------------------


def _rot_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    """Matrix4f::makeSRT rotation part: Rz * Ry * Rx (radians)."""
    sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
    cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
    return np.array(
        [
            [cy * cz, sx * sy * cz - cx * sz, cx * cz * sy + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sz * sy - sx * cz],
            [-sy, sx * cy, cx * cy],
        ]
    )


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
    if i == 0:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if i == 1:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


def _joint_world(model: pm.Model) -> list[np.ndarray]:
    mats: list[np.ndarray] = []
    for j in model.joints:
        m = np.eye(4)
        m[:3, :3] = _rot_matrix(*j.rotation) @ np.diag(j.scale)
        m[:3, 3] = j.translation
        if 0 <= j.parent < len(mats):
            m = mats[j.parent] @ m
        mats.append(m)
    return mats


# --- materials / textures -----------------------------------------------------------------


def _tex_name(i: int) -> str:
    return f"tex{i:02d}"


def _material_def(model: pm.Model, idx: int, mat: pm.Material, double_sided: bool) -> MaterialDef:
    tex = None
    clamp_u = clamp_v = mirror_u = mirror_v = False
    ta = mat.tex_attr
    if 0 <= ta < len(model.tex_attrs):
        attr = model.tex_attrs[ta]
        if attr.image < len(model.textures):
            tex = _tex_name(attr.image)
        clamp_u = bool(attr.tiling & pm.TILE_CLAMP_S)
        clamp_v = bool(attr.tiling & pm.TILE_CLAMP_T)
        mirror_u = bool(attr.tiling & pm.TILE_MIRROR_S)
        mirror_v = bool(attr.tiling & pm.TILE_MIRROR_T)
    colour = mat.pvw_colour if mat.pvw_colour is not None else mat.colour
    base = tuple(c / 255.0 for c in colour)
    unlit = bool(mat.flags & pm.MATFLAG_PVW) and not (mat.lighting_flags & 1)
    return MaterialDef(
        name=f"mat{idx:02d}" + (f"_{tex}" if tex else ""),
        texture=tex,
        base_color=base,  # type: ignore[arg-type]
        alpha_blend=bool(mat.flags & pm.MATFLAG_ALPHA_BLEND),
        double_sided=double_sided,
        clamp_u=clamp_u,
        clamp_v=clamp_v,
        mirror_u=mirror_u,
        mirror_v=mirror_v,
        unlit=unlit,
    )


# --- geometry -----------------------------------------------------------------------------


def _uv_field(flags: int) -> str | None:
    for i in range(8):
        if flags & (pm.MESH_TEX0 << i):
            return f"tex{i}"
    return None


def _matpoly_primitive(
    model: pm.Model,
    world: list[np.ndarray],
    mat_index: int,
    mesh_index: int,
    owner_joint: int,
    warnings: list[str],
) -> Primitive | None:
    mesh = model.meshes[mesh_index]
    fields = [f for f, _ in pm.vertex_fields(mesh.flags)]
    uv_field = _uv_field(mesh.flags)
    keys_list, tri_list = [], []
    base = 0
    fallback_joint = mesh.parent_joint if mesh.parent_joint >= 0 else owner_joint
    for group in mesh.groups:
        # matrix slot -> vertex-matrix table index (-1 = rigid to the mesh's joint)
        slots = np.full(max(len(group.deps), 1) * 3 + 3, -1, np.int64)
        for k, dep in enumerate(group.deps):
            if dep >= 0:
                slots[k * 3] = dep
        for dl in group.lists:
            prims = pm.parse_display_list(dl.data, mesh.flags)
            for op, arr in prims:
                n = len(arr)
                if "mtx" in fields:
                    mtx = np.minimum(arr["mtx"].astype(np.int64), len(slots) - 1)
                    vm = slots[mtx]
                else:
                    vm = np.full(n, -1, np.int64)
                pos = arr["pos"].astype(np.int64)
                nrm = arr["nrm"].astype(np.int64)
                clr = arr["clr"].astype(np.int64) if "clr" in fields else np.full(n, -1)
                uv = arr[uv_field].astype(np.int64) if uv_field else np.full(n, -1)
                keys_list.append(np.stack([vm, pos, nrm, clr, uv], axis=1))
                tris = triangulate(op, n)
                if dl.cull == 1:
                    tris = tris[:, [0, 2, 1]]
                if len(tris):
                    tri_list.append(tris + base)
                base += n
    if not keys_list or not tri_list:
        return None
    keys = np.concatenate(keys_list)
    tris = np.concatenate(tri_list)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    indices = inverse.reshape(-1)[tris].reshape(-1).astype(np.uint32)
    nv = len(uniq)

    npos = len(model.positions)
    pos_idx = uniq[:, 1]
    bad = pos_idx >= npos
    if bad.any():
        warnings.append(f"mesh {mesh_index}: {int(bad.sum())} position indices out of range")
        pos_idx = np.where(bad, 0, pos_idx)
    positions = model.positions[pos_idx].astype(np.float64)

    normals = None
    use_nbt = bool(mesh.flags & pm.MESH_NBT) and len(model.nbt)
    nrm_src = model.nbt[:, 0, :] if use_nbt else model.normals
    if len(nrm_src):
        nrm_idx = np.minimum(uniq[:, 2], len(nrm_src) - 1)
        normals = nrm_src[nrm_idx].astype(np.float64)

    colors = None
    if "clr" in fields and len(model.colours):
        cidx = np.minimum(uniq[:, 3], len(model.colours) - 1)
        colors = model.colours[cidx].astype(np.float32) / 255.0

    uvs = None
    if uv_field:
        tc = model.texcoords[int(uv_field[3:])]
        if len(tc):
            uvs = tc[np.minimum(uniq[:, 4], len(tc) - 1)].astype(np.float32)

    # skinning: rigid vertices are in joint space -> bind space; envelopes already are
    joints = np.zeros((nv, 4), np.uint16)
    weights = np.zeros((nv, 4), np.float32)
    weights[:, 0] = 1.0
    vm_col = uniq[:, 0]
    for vmi in np.unique(vm_col):
        sel = vm_col == vmi
        entry = model.vtx_matrices[vmi] if 0 <= vmi < len(model.vtx_matrices) else fallback_joint
        if entry >= 0:
            j = entry if entry < len(world) else fallback_joint
            if j < 0 or j >= len(world):
                continue
            m = world[j]
            positions[sel] = positions[sel] @ m[:3, :3].T + m[:3, 3]
            if normals is not None:
                normals[sel] = normals[sel] @ m[:3, :3].T
            joints[sel, 0] = j
        else:
            env_i = -entry - 1
            if env_i >= len(model.envelopes):
                warnings.append(f"mesh {mesh_index}: envelope {env_i} missing")
                continue
            env = model.envelopes[env_i][:4]
            for k, (j, w) in enumerate(env):
                joints[sel, k] = min(j, max(len(world) - 1, 0))
                weights[sel, k] = w
            tot = weights[sel].sum(axis=1, keepdims=True)
            weights[sel] = np.where(tot > 0, weights[sel] / np.maximum(tot, 1e-6), weights[sel])
    if not model.joints:
        joints = weights = None
    return Primitive(
        material=mat_index,
        positions=positions.astype(np.float32),
        indices=indices,
        normals=normals.astype(np.float32) if normals is not None else None,
        uvs=uvs,
        colors=colors,
        joints=joints,
        weights=weights,
    )


def build_scene(model: pm.Model, name: str) -> Scene:
    scene = Scene(name=name, warnings=list(model.warnings))
    world = _joint_world(model)
    for i, j in enumerate(model.joints):
        rot = _quat(_rot_matrix(*j.rotation))
        scene.joints.append(
            Joint(
                name=j.name or f"joint{i:02d}",
                parent=j.parent if 0 <= j.parent < len(model.joints) and j.parent != i else None,
                translation=tuple(float(x) for x in j.translation),  # type: ignore[arg-type]
                rotation=tuple(float(x) for x in rot),  # type: ignore[arg-type]
                scale=tuple(float(x) for x in j.scale),  # type: ignore[arg-type]
            )
        )
    # which materials are drawn without culling anywhere
    double: set[int] = set()
    for j in model.joints:
        for mat_i, mesh_i in j.matpolys:
            if mesh_i < len(model.meshes) and any(
                dl.cull == 2 for g in model.meshes[mesh_i].groups for dl in g.lists
            ):
                double.add(mat_i)
    for i, mat in enumerate(model.materials):
        scene.materials.append(_material_def(model, i, mat, i in double))
    for i, tex in enumerate(model.textures):
        try:
            scene.textures[_tex_name(i)] = pm.decode_texture(tex)
        except Exception as ex:  # noqa: BLE001
            scene.warnings.append(f"texture {i}: {ex}")
    for ji, j in enumerate(model.joints):
        for mat_i, mesh_i in j.matpolys:
            if mat_i >= len(model.materials) or mesh_i >= len(model.meshes):
                scene.warnings.append(f"joint {ji}: matpoly ({mat_i}, {mesh_i}) out of range")
                continue
            if model.materials[mat_i].flags & pm.MATFLAG_SKIP:
                continue
            try:
                prim = _matpoly_primitive(model, world, mat_i, mesh_i, ji, scene.warnings)
            except pm.PikminError as ex:
                scene.warnings.append(f"mesh {mesh_i}: {ex}")
                continue
            if prim is not None:
                scene.primitives.append(prim)
    scene.extras = {
        "format": "pikmin_mod",
        "date": "{:04d}-{:02d}-{:02d}".format(*model.date),
        "shape_flags": model.shape_flags,
    }
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = pm.parse(data)
    stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    scene = build_scene(model, stem)
    if not scene.primitives:
        return []
    return [scene]
