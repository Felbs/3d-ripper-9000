"""Luigi's Mansion (GLME01): ``.mdl`` characters (gcrip.formats.lm_mdl) and ``.bin`` rooms /
furniture (gcrip.formats.lm_bin) -> Scene.

.mdl: every node is a joint whose *inverse* bind matrix is in the file; vertices on a rigid
matrix slot are stored in that joint's space (moved to bind space here, weight 1), vertices
on a weight entry are already in bind space and carry that entry's joint/weight list.
.bin: the scene graph nodes become joints (scale / rotation in degrees / translation);
batch vertices are in node space and are bound to their node with weight 1.
"""

from __future__ import annotations

import math

import numpy as np

from gcrip.formats import lm_bin, lm_mdl
from gcrip.formats.j3d import triangulate
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "lm"


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".mdl"):
        return lm_mdl.looks_like_mdl(head)
    if low.endswith(".bin"):
        return lm_bin.looks_like_bin(head, size)
    return False


# --- math ---------------------------------------------------------------------------------


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


def _decompose(m: np.ndarray) -> tuple[tuple, tuple, tuple]:
    """4x4 affine -> (translation, quaternion, scale); rotation left orthonormal."""
    t = tuple(float(x) for x in m[:3, 3])
    r = m[:3, :3].astype(np.float64)
    s = np.linalg.norm(r, axis=0)
    s = np.where(s > 1e-9, s, 1.0)
    rn = r / s
    if np.linalg.det(rn) < 0:
        s[0] = -s[0]
        rn[:, 0] = -rn[:, 0]
    return t, tuple(float(x) for x in _quat(rn)), tuple(float(x) for x in s)


def _rot_deg(rx: float, ry: float, rz: float) -> np.ndarray:
    """Rz * Ry * Rx from degrees."""
    rx, ry, rz = (math.radians(a) for a in (rx, ry, rz))
    sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
    cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
    return np.array(
        [
            [cy * cz, sx * sy * cz - cx * sz, cx * cz * sy + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sz * sy - sx * cz],
            [-sy, sx * cy, cx * cy],
        ]
    )


def _safe_inv(m: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(m)


# --- shared geometry assembly -------------------------------------------------------------


def _assemble(
    keys: np.ndarray,
    tris: np.ndarray,
    material: int,
    positions: np.ndarray,
    normals: np.ndarray | None,
    colors: np.ndarray | None,
    uvs: np.ndarray | None,
    binding,
    warnings: list[str],
    label: str,
) -> Primitive | None:
    """keys: (N, 5) [matrix key, pos, nrm, clr, uv] per display-list vertex; tris (T,3) into
    keys.  `binding(mkey) -> (world 4x4 or None, [(joint, weight), ...])`."""
    if not len(keys) or not len(tris):
        return None
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    indices = inverse.reshape(-1)[tris].reshape(-1).astype(np.uint32)
    nv = len(uniq)
    pidx = uniq[:, 1]
    bad = pidx >= len(positions)
    if bad.any():
        warnings.append(f"{label}: {int(bad.sum())} position indices out of range")
        pidx = np.where(bad, 0, pidx)
    pos = positions[pidx].astype(np.float64)
    nrm = None
    if normals is not None and len(normals):
        nrm = normals[np.minimum(uniq[:, 2], len(normals) - 1)].astype(np.float64)
    clr = None
    if colors is not None and len(colors):
        clr = colors[np.minimum(uniq[:, 3], len(colors) - 1)].astype(np.float32) / 255.0
    uv = None
    if uvs is not None and len(uvs):
        uv = uvs[np.minimum(uniq[:, 4], len(uvs) - 1)].astype(np.float32)
    joints = np.zeros((nv, 4), np.uint16)
    weights = np.zeros((nv, 4), np.float32)
    weights[:, 0] = 1.0
    for mk in np.unique(uniq[:, 0]):
        sel = uniq[:, 0] == mk
        world, infl = binding(int(mk))
        if world is not None:
            pos[sel] = pos[sel] @ world[:3, :3].T + world[:3, 3]
            if nrm is not None:
                nrm[sel] = nrm[sel] @ world[:3, :3].T
        if infl:
            infl = infl[:4]
            weights[sel] = 0
            for k, (j, w) in enumerate(infl):
                joints[sel, k] = j
                weights[sel, k] = w
            tot = weights[sel].sum(axis=1, keepdims=True)
            weights[sel] = np.where(tot > 0, weights[sel] / np.maximum(tot, 1e-6), weights[sel])
    return Primitive(
        material=material,
        positions=pos.astype(np.float32),
        indices=indices,
        normals=nrm.astype(np.float32) if nrm is not None else None,
        uvs=uv,
        colors=clr,
        joints=joints,
        weights=weights,
    )


def _wrap_flags(wrap_u: int, wrap_v: int) -> dict:
    return {
        "clamp_u": wrap_u == 0,
        "clamp_v": wrap_v == 0,
        "mirror_u": wrap_u == 2,
        "mirror_v": wrap_v == 2,
    }


# --- .mdl ---------------------------------------------------------------------------------


def _mdl_scene(model: lm_mdl.Model, name: str) -> Scene:
    scene = Scene(name=name, warnings=list(model.warnings))
    nj = model.joint_count
    # the file stores inverse bind matrices (world -> joint); invert for the rest pose
    world = [_safe_inv(model.matrices[i].astype(np.float64)) for i in range(nj)]
    for i in range(nj):
        parent = model.nodes[i].parent if i < len(model.nodes) else -1
        if not (0 <= parent < i):
            parent = -1
        local = world[i] if parent < 0 else _safe_inv(world[parent]) @ world[i]
        t, r, s = _decompose(local)
        scene.joints.append(Joint(f"node{i:02d}", parent if parent >= 0 else None, t, r, s))

    for i, tex in enumerate(model.textures):
        try:
            scene.textures[f"tex{i:02d}"] = lm_mdl.decode_texture(tex)
        except Exception as ex:  # noqa: BLE001
            scene.warnings.append(f"texture {i}: {ex}")

    for i, mat in enumerate(model.materials):
        tex = None
        wrap: dict = {}
        for si in mat.samplers[: max(mat.tev_count, 1)]:
            if si < len(model.samplers) and model.samplers[si].texture < len(model.textures):
                smp = model.samplers[si]
                tex = f"tex{smp.texture:02d}"
                wrap = _wrap_flags(smp.wrap_u, smp.wrap_v)
                break
        scene.materials.append(
            MaterialDef(
                name=f"mat{i:02d}" + (f"_{tex}" if tex else ""),
                texture=tex,
                base_color=tuple(c / 255.0 for c in mat.color),  # type: ignore[arg-type]
                alpha_blend=bool(mat.alpha_flags),
                **wrap,
            )
        )

    def binding(mk: int):
        if mk < 0:
            return None, []
        if mk < nj:
            return world[mk], [(mk, 1.0)]
        wi = mk - nj
        if wi < len(model.weights):
            return None, [(min(j, nj - 1), w) for j, w in model.weights[wi]]
        return None, []

    seen_draw: set[int] = set()
    for nd in model.nodes:
        for de in range(nd.draw_start, nd.draw_start + nd.draw_count):
            if de in seen_draw or de >= len(model.draw_elements):
                continue
            seen_draw.add(de)
            mat_i, shape_i = model.draw_elements[de]
            if shape_i >= len(model.shapes) or mat_i >= len(model.materials):
                scene.warnings.append(f"draw element {de}: out of range")
                continue
            shape = model.shapes[shape_i]
            fields = lm_mdl.vertex_fields(model, shape)
            names = [f for f, _ in fields]
            keys_list, tri_list, base = [], [], 0
            for pi in range(shape.packet_start, shape.packet_start + shape.packet_count):
                if pi >= len(model.packets):
                    break
                pk = model.packets[pi]
                try:
                    prims = lm_mdl.parse_display_list(pk.data, fields)
                except lm_mdl.LMError as ex:
                    scene.warnings.append(f"shape {shape_i} packet {pi}: {ex}")
                    continue
                slots = np.array([m if m != 0xFFFF else -1 for m in pk.matrices] or [-1])
                for op, arr in prims:
                    n = len(arr)
                    slot = np.clip(arr["mtx"].astype(np.int64) // 3, 0, len(slots) - 1)
                    mk = np.where(arr["mtx"] < 0, -1, slots[slot])
                    col = {
                        f: arr[f].astype(np.int64) if f in names else np.full(n, -1)
                        for f in ("pos", "nrm", "clr0", "tex0")
                    }
                    keys_list.append(
                        np.stack([mk, col["pos"], col["nrm"], col["clr0"], col["tex0"]], 1)
                    )
                    tris = triangulate(op, n)
                    if len(tris):
                        tri_list.append(tris + base)
                    base += n
            if not keys_list or not tri_list:
                continue
            prim = _assemble(
                np.concatenate(keys_list),
                np.concatenate(tri_list),
                mat_i,
                model.positions,
                model.normals,
                model.colors,
                model.texcoords,
                binding,
                scene.warnings,
                f"shape {shape_i}",
            )
            if prim is not None:
                if not scene.joints:
                    prim.joints = prim.weights = None
                scene.primitives.append(prim)
    scene.extras = {"format": "lm_mdl", "faces": model.face_count}
    return scene


# --- .bin ---------------------------------------------------------------------------------


def _bin_scene(model: lm_bin.Model, name: str) -> Scene:
    scene = Scene(name=model.name or name, warnings=list(model.warnings))
    world: list[np.ndarray] = []
    for i, nd in enumerate(model.nodes):
        local = np.eye(4)
        local[:3, :3] = _rot_deg(*nd.rotation) @ np.diag(nd.scale)
        local[:3, 3] = nd.translation
        parent = nd.parent if 0 <= nd.parent < i else -1
        world.append(world[parent] @ local if parent >= 0 else local)
        rot = _quat(_rot_deg(*nd.rotation))
        scene.joints.append(
            Joint(
                f"node{i:02d}",
                parent if parent >= 0 else None,
                tuple(float(x) for x in nd.translation),  # type: ignore[arg-type]
                tuple(float(x) for x in rot),  # type: ignore[arg-type]
                tuple(float(x) for x in nd.scale),  # type: ignore[arg-type]
            )
        )
    for i, tex in enumerate(model.textures):
        try:
            scene.textures[f"tex{i:02d}"] = lm_bin.decode_texture(tex)
        except Exception as ex:  # noqa: BLE001
            scene.warnings.append(f"texture {i}: {ex}")

    # materials: one per (shader, node render flags) actually used
    mat_index: dict[tuple[int, int], int] = {}

    def material_for(shader_i: int, flags: int) -> int:
        key = (shader_i, flags & 0x48)
        if key in mat_index:
            return mat_index[key]
        sh = model.shaders[shader_i]
        tex = None
        wrap: dict = {}
        for si in sh.samplers:
            if 0 <= si < len(model.samplers):
                smp = model.samplers[si]
                if 0 <= smp.texture < len(model.textures):
                    tex = f"tex{smp.texture:02d}"
                    wrap = _wrap_flags(smp.wrap_u, smp.wrap_v)
                break
        scene.materials.append(
            MaterialDef(
                name=f"shader{shader_i:02d}" + (f"_{tex}" if tex else ""),
                texture=tex,
                base_color=tuple(c / 255.0 for c in sh.tint),  # type: ignore[arg-type]
                alpha_blend=bool(flags & 0x08),
                unlit=bool(flags & 0x40),
                **wrap,
            )
        )
        mat_index[key] = len(scene.materials) - 1
        return mat_index[key]

    for ni, nd in enumerate(model.nodes):
        for shader_i, batch_i in nd.parts:
            if shader_i >= len(model.shaders) or batch_i not in model.batches:
                scene.warnings.append(f"node {ni}: part ({shader_i}, {batch_i}) out of range")
                continue
            batch = model.batches[batch_i]
            fields = lm_bin.vertex_fields(batch)
            names = [f for f, _ in fields]
            if "pos" not in names:
                continue
            try:
                prims = lm_bin.parse_display_list(batch.data, fields)
            except lm_bin.LMBinError as ex:
                scene.warnings.append(f"batch {batch_i}: {ex}")
                continue
            keys_list, tri_list, base = [], [], 0
            for op, arr in prims:
                n = len(arr)
                col = {
                    f: arr[f].astype(np.int64) if f in names else np.full(n, -1)
                    for f in ("pos", "nrm", "clr0", "tex0")
                }
                keys_list.append(
                    np.stack([np.full(n, ni), col["pos"], col["nrm"], col["clr0"], col["tex0"]], 1)
                )
                tris = triangulate(op, n)
                if len(tris):
                    tri_list.append(tris + base)
                base += n
            if not keys_list or not tri_list:
                continue
            prim = _assemble(
                np.concatenate(keys_list),
                np.concatenate(tri_list),
                material_for(shader_i, nd.render_flags),
                model.positions,
                model.normals if batch.use_normals else None,
                model.colors[0],
                model.texcoords[0],
                lambda mk: (world[mk], [(mk, 1.0)]),
                scene.warnings,
                f"batch {batch_i}",
            )
            if prim is not None:
                scene.primitives.append(prim)
    scene.extras = {"format": "lm_bin"}
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if path.lower().endswith(".mdl"):
        scene = _mdl_scene(lm_mdl.parse(data), stem)
    else:
        scene = _bin_scene(lm_bin.parse(data), stem)
    return [scene] if scene.primitives else []
