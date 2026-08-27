"""Paper Mario: The Thousand-Year Door (G8ME01) -> Scene.

Two formats, both undocumented by Nintendo and reverse-engineered by the noclip.website
TTYD renderer (``PaperMarioTTYD/world.ts``, ``AnimGroup.ts``) and the ``ttyd`` decompilation:

* ``m/<map>/d`` map geometry (``gcrip.formats.ttyd_map``) with its textures in the sibling
  ``m/<map>/t`` TPL.  The scene graph has an "S" subtree (visual) and an "A" subtree
  (collision / hit); only S is exported, each node's SRT baked into world space.
* ``a/<name>`` AnimGroup "paper" actors (``gcrip.formats.ttyd_agb``) with textures in the
  sibling ``a/<name>-`` TPL.  Groups become joints (rest pose), shapes rigid to their group.
"""

from __future__ import annotations

import math

import numpy as np

from gcrip.formats import gx_texture, tpl, ttyd_agb, ttyd_map
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "ttyd"

WRAP_CLAMP, WRAP_REPEAT, WRAP_MIRROR = 0, 1, 2


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def detect(path: str, head: bytes, size: int) -> bool:
    p = path.replace("\\", "/")
    name = _base(p)
    if name == "d" and "/m/" in f"/{p}":
        return ttyd_map.looks_like_map(head, size)
    if "/a/" in f"/{p}" and not name.endswith("-") and "." not in name:
        return ttyd_agb.looks_like_agb(head, size, name)
    return False


# --- shared ------------------------------------------------------------------------------


def _rot_zyx(rx: float, ry: float, rz: float) -> np.ndarray:
    """Rz * Ry * Rx for degrees (computeModelMatrixSRT order)."""
    rx, ry, rz = (math.radians(v) for v in (rx, ry, rz))
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


def _decode_tpl(blob: bytes, names: list[str], warnings: list[str]) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    try:
        images = tpl.parse(blob)
    except Exception as ex:  # noqa: BLE001
        warnings.append(f"texture TPL: {ex}")
        return out
    for i, img in enumerate(images):
        key = names[i] if i < len(names) and names[i] else f"image{i}"
        try:
            out[key] = img.decode()
        except Exception as ex:  # noqa: BLE001
            warnings.append(f"texture {key}: {ex}")
    return out


def _tex_has_alpha(blob: bytes | None) -> dict[int, bool]:
    if not blob:
        return {}
    try:
        return {
            i: gx_texture.has_alpha(t.fmt, t.palette_fmt) for i, t in enumerate(tpl.parse(blob))
        }
    except Exception:  # noqa: BLE001
        return {}


def _normalize(n: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.where(length > 1e-6, n / np.maximum(length, 1e-6), n).astype(np.float32)


def _sibling(src, path: str, name: str) -> bytes | None:
    if src is None:
        return None
    p = path.replace("\\", "/")
    target = p.rsplit("/", 1)[0] + "/" + name if "/" in p else name
    try:
        return src.get(target)
    except Exception:  # noqa: BLE001
        return None


# --- maps ---------------------------------------------------------------------------------


def _uv_matrix(x: ttyd_map.TexXform) -> np.ndarray:
    """noclip's calcTexMtx as a 3x3 acting on [s, t, 1]."""
    theta = math.radians(-x.rotation)
    c, s = math.cos(theta), math.sin(theta)
    rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    t0 = np.eye(3)
    t0[0, 2] = x.scale_s * (0.5 * x.center_s)
    t0[1, 2] = x.scale_t * (0.5 * x.center_t - 1.0)
    t1 = np.eye(3)
    t1[0, 2] = -t0[0, 2]
    t1[1, 2] = -t0[1, 2]
    sc = np.diag([x.scale_s, x.scale_t, 1.0])
    m = sc @ (t1 @ (rot @ t0))
    m[0, 2] += x.trans_s
    m[1, 2] += -x.trans_t
    return m


def _map_material(
    mat: ttyd_map.Material, model: ttyd_map.Model, alpha: dict[int, bool], double: bool
) -> tuple[MaterialDef, int, np.ndarray | None]:
    """MaterialDef plus (uv set index, uv matrix) of the base texture (TEXMAP0)."""
    tex = None
    uv_set = 0
    uv_mtx = None
    clamp_u = clamp_v = mirror_u = mirror_v = False
    has_alpha = False
    if mat.samplers:
        # the game binds samplers back to front: TEXMAP0 is the last table entry, using
        # TEX<n-1> with the first texture transform
        s = mat.samplers[-1]
        uv_set = len(mat.samplers) - 1
        if 0 <= s.texture < len(model.texture_names):
            tex = model.texture_names[s.texture] or f"image{s.texture}"
            has_alpha = alpha.get(s.texture, False)
        clamp_u, clamp_v = s.wrap_s == WRAP_CLAMP, s.wrap_t == WRAP_CLAMP
        mirror_u, mirror_v = s.wrap_s == WRAP_MIRROR, s.wrap_t == WRAP_MIRROR
        if mat.xforms:
            m = _uv_matrix(mat.xforms[0])
            if not np.allclose(m, np.eye(3), atol=1e-6):
                uv_mtx = m
    r, g, b, a = mat.color
    base = (1.0, 1.0, 1.0, 1.0) if mat.color_src == 1 else (r / 255, g / 255, b / 255, a / 255)
    return (
        MaterialDef(
            name=mat.name,
            texture=tex,
            base_color=base,  # type: ignore[arg-type]
            alpha_blend=mat.layer >= 1 and (has_alpha or tex is None),
            double_sided=double,
            clamp_u=clamp_u,
            clamp_v=clamp_v,
            mirror_u=mirror_u,
            mirror_v=mirror_v,
            unlit=True,
        ),
        uv_set,
        uv_mtx,
    )


def build_map_scene(model: ttyd_map.Model, name: str, tex_blob: bytes | None) -> Scene:
    scene = Scene(name=name, warnings=list(model.warnings))
    if tex_blob:
        scene.textures = _decode_tpl(tex_blob, model.texture_names, scene.warnings)
    alpha = _tex_has_alpha(tex_blob)

    # world matrices; only the S (visual) subtree is drawn
    world: list[np.ndarray | None] = [None] * len(model.nodes)
    visual: list[bool] = [False] * len(model.nodes)
    for i, n in enumerate(model.nodes):
        local = np.eye(4)
        local[:3, :3] = _rot_zyx(*n.rotation) @ np.diag(n.scale)
        local[:3, 3] = n.translation
        if n.parent >= 0 and world[n.parent] is not None:
            world[i] = world[n.parent] @ local
            visual[i] = visual[n.parent] or (n.parent == model.root and n.name == model.s_node)
        else:
            world[i] = local
            visual[i] = n.name == model.s_node
    if not any(visual):  # no S node named: draw everything that is not the A subtree
        for i, n in enumerate(model.nodes):
            visual[i] = not (
                n.name == model.a_node
                or (n.parent >= 0 and not visual[n.parent] and n.parent != model.root)
            )

    double: set[int] = set()
    for i, n in enumerate(model.nodes):
        if visual[i] and n.cull >= 2:
            double.update(p.material for p in n.parts)
    uv_info = []
    for i, mat in enumerate(model.materials):
        mdef, uv_set, uv_mtx = _map_material(mat, model, alpha, i in double)
        scene.materials.append(mdef)
        uv_info.append((uv_set, uv_mtx))

    for i, n in enumerate(model.nodes):
        if not visual[i] or not n.parts:
            continue
        m = world[i]
        assert m is not None
        flip = n.cull == 0
        for part in n.parts:
            mesh = part.mesh
            pos = mesh.positions @ m[:3, :3].T + m[:3, 3]
            tris = mesh.triangles[:, [0, 2, 1]] if flip else mesh.triangles
            uv_set, uv_mtx = uv_info[part.material]
            uvs = mesh.uvs[uv_set] if uv_set < len(mesh.uvs) else None
            if uvs is None and mesh.uvs and mesh.uvs[0] is not None:
                uvs = mesh.uvs[0]
            if uvs is not None and uv_mtx is not None:
                uvs = uvs @ uv_mtx[:2, :2].T + uv_mtx[:2, 2]
            normals = None
            if mesh.normals is not None:
                normals = _normalize(mesh.normals @ m[:3, :3].T)
            scene.primitives.append(
                Primitive(
                    material=part.material,
                    positions=pos.astype(np.float32),
                    indices=tris.reshape(-1).astype(np.uint32),
                    normals=normals,
                    uvs=uvs.astype(np.float32) if uvs is not None else None,
                    colors=mesh.colors,
                )
            )
    scene.extras = {
        "format": "ttyd_map",
        "version": model.version,
        "nodes": len(model.nodes),
        "s_node": model.s_node,
        "a_node": model.a_node,
    }
    return scene


# --- AnimGroup actors -----------------------------------------------------------------------


def _agb_material(
    agb: ttyd_agb.AnimGroup,
    draw: ttyd_agb.Draw,
    shape: ttyd_agb.Shape,
    alpha: dict[int, bool],
    key: tuple,
) -> MaterialDef:
    tex = None
    clamp_u = clamp_v = mirror_u = mirror_v = False
    has_alpha = False
    if draw.tex_ids:
        arc = ttyd_agb.texture_index(agb, draw.tex_ids[0])
        if arc is not None:
            tex = f"image{arc}"
            has_alpha = alpha.get(arc, False)
        base = agb.tex_base[draw.tex_ids[0]] if draw.tex_ids[0] < len(agb.tex_base) else None
        if base is not None and base.wrap_flags >= 0:
            f = base.wrap_flags
            mirror_u, mirror_v = bool(f & 4), bool(f & 8)
            clamp_u, clamp_v = not (f & 5), not (f & 0xA)
    return MaterialDef(
        name="_".join(str(k) for k in key),
        texture=tex,
        alpha_blend=shape.disp_mode in (0, 2, 3) and (has_alpha or tex is None),
        double_sided=shape.cull >= 2,
        clamp_u=clamp_u,
        clamp_v=clamp_v,
        mirror_u=mirror_u,
        mirror_v=mirror_v,
        unlit=True,
    )


def build_agb_scene(agb: ttyd_agb.AnimGroup, name: str, tex_blob: bytes | None) -> Scene:
    scene = Scene(name=name, warnings=list(agb.warnings))
    if tex_blob:
        names = [f"image{i}" for i in range(len(agb.textures) + 64)]
        scene.textures = _decode_tpl(tex_blob, names, scene.warnings)
    alpha = _tex_has_alpha(tex_blob)

    # groups -> joints, root last in the table; world matrices from the node floats
    order, parents = ttyd_agb.group_order(agb)
    joint_of: dict[int, int] = {}
    world: dict[int, np.ndarray] = {}
    for gi in order:
        g = agb.groups[gi]
        parent_gi = parents[gi]
        ssc_parent = agb.groups[parent_gi].node if (g.ssc and parent_gi >= 0) else -1
        local = ttyd_agb.node_matrix(agb.node, g.node, ssc_parent)
        pw = world[parent_gi] if parent_gi >= 0 else np.eye(4)
        world[gi] = pw @ local
        lin = local[:3, :3]
        sc = np.linalg.norm(lin, axis=0)
        sc = np.where(sc > 1e-8, sc, 1.0)
        rot = lin / sc
        if np.linalg.det(rot) < 0:
            sc = sc * np.array([-1.0, 1.0, 1.0])
            rot = lin / sc
        joint_of[gi] = len(scene.joints)
        scene.joints.append(
            Joint(
                name=g.name or f"group{gi}",
                parent=joint_of[parent_gi] if parent_gi >= 0 else None,
                translation=tuple(float(v) for v in local[:3, 3]),  # type: ignore[arg-type]
                rotation=_quat(rot),
                scale=tuple(float(v) for v in sc),  # type: ignore[arg-type]
            )
        )

    mat_index: dict[tuple, int] = {}
    for gi in order:
        g = agb.groups[gi]
        if g.shape < 0 or g.shape >= len(agb.shapes):
            continue
        if not agb.visible(g):
            continue
        shape = agb.shapes[g.shape]
        m = world[gi]
        ji = joint_of[gi]
        for draw in shape.draws:
            if draw.positions is None or len(draw.triangles) == 0:
                continue
            key = (shape.disp_mode, shape.cull, tuple(draw.tex_ids), draw.tev_mode)
            if key not in mat_index:
                mat_index[key] = len(scene.materials)
                scene.materials.append(_agb_material(agb, draw, shape, alpha, key))
            pos = draw.positions @ m[:3, :3].T + m[:3, 3]
            n = len(pos)
            joints = np.zeros((n, 4), np.uint16)
            joints[:, 0] = ji
            weights = np.zeros((n, 4), np.float32)
            weights[:, 0] = 1.0
            normals = None
            if draw.normals is not None:
                normals = _normalize(draw.normals @ m[:3, :3].T)
            uvs = draw.uvs[0] if draw.uvs and draw.uvs[0] is not None else None
            if uvs is not None and draw.tex_ids:
                tm = agb.tex_mtx[draw.tex_ids[0]] if draw.tex_ids[0] < len(agb.tex_mtx) else None
                if tm is not None:
                    uvs = ttyd_agb.apply_tex_mtx(uvs, tm)
            tris = draw.triangles[:, [0, 2, 1]] if shape.cull == 1 else draw.triangles
            scene.primitives.append(
                Primitive(
                    material=mat_index[key],
                    positions=pos.astype(np.float32),
                    indices=tris.reshape(-1).astype(np.uint32),
                    normals=normals,
                    uvs=uvs.astype(np.float32) if uvs is not None else None,
                    colors=draw.colors,
                    joints=joints,
                    weights=weights,
                )
            )
    scene.extras = {
        "format": "ttyd_agb",
        "anm": agb.anm_name,
        "tex": agb.tex_name,
        "built": agb.build_time,
        "animations": [a.name for a in agb.anims],
    }
    return scene


# --- entry --------------------------------------------------------------------------------


def extract(data: bytes, path: str, src) -> list[Scene]:
    p = path.replace("\\", "/")
    name = _base(p)
    if name == "d":
        model = ttyd_map.parse(data)
        stem = p.rsplit("/", 2)[-2] if p.count("/") >= 1 else "map"
        scene = build_map_scene(model, stem, _sibling(src, p, "t"))
    else:
        agb = ttyd_agb.parse(data)
        scene = build_agb_scene(agb, name, _sibling(src, p, name + "-"))
    if not scene.primitives:
        return []
    return [scene]
