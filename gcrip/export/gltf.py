"""Export a parsed J3D model to glTF 2.0 (.gltf + .bin + PNG textures).

Vertex data is baked into model space at the bind pose. Rigidly bound vertices
(DRW1 non-weighted) are stored joint-local in the file and are pre-multiplied by
the joint's bind world matrix here; envelope-weighted vertices are already in
model space. The skin then uses inverse bind matrices computed from JNT1, so
everything is consistent at rest and poseable in Blender.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gcrip import rig
from gcrip.export import png
from gcrip.formats import j3d
from gcrip.formats import j3d_anim as ja

GL_ARRAY_BUFFER = 34962
GL_ELEMENT_ARRAY_BUFFER = 34963
GL_FLOAT = 5126
GL_UNSIGNED_SHORT = 5123
GL_UNSIGNED_INT = 5125
GL_UNSIGNED_BYTE = 5121
GL_NEAREST = 9728
GL_LINEAR = 9729
GL_LINEAR_MIPMAP_LINEAR = 9987
GL_REPEAT = 10497
GL_CLAMP = 33071
GL_MIRROR = 33648
_WRAP = {0: GL_CLAMP, 1: GL_REPEAT, 2: GL_MIRROR}


def _safe(name: str) -> str:
    name = re.sub(r"[^\w.\-]+", "_", name).strip("._")
    return name or "unnamed"


@dataclass
class ExportStats:
    shapes: int = 0
    triangles: int = 0
    vertices: int = 0
    joints: int = 0
    textures: int = 0
    materials: int = 0
    skinned: bool = False
    warnings: list[str] = field(default_factory=list)
    # for thumbnails: per shape (baked positions (N,3), triangles (T,3), material index)
    geometry: list[tuple[np.ndarray, np.ndarray, int | None]] = field(default_factory=list)
    # per shape: {uv set: (N,2)} matching `geometry` vertices
    uvs: list[dict[int, np.ndarray]] = field(default_factory=list)
    texture_colors: list[tuple[float, float, float]] = field(default_factory=list)
    texture_images: list[np.ndarray | None] = field(default_factory=list)  # decoded RGBA
    texture_files: list[str] = field(default_factory=list)
    variants: dict[str, str] = field(default_factory=dict)  # variant material -> base material
    animations: list[str] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)  # KHR_materials_variants names
    std_bones: dict[str, str] = field(default_factory=dict)  # joint name -> standard bone
    material_tex: list[tuple[int, int]] = field(default_factory=list)  # (glTF tex, uv set)


class _BufferBuilder:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def _align(self, n: int = 4) -> None:
        while len(self.data) % n:
            self.data.append(0)

    def add(
        self,
        arr: np.ndarray,
        component_type: int,
        acc_type: str,
        target: int | None,
        minmax: bool = False,
        normalized: bool = False,
    ) -> int:
        self._align()
        raw = np.ascontiguousarray(arr).tobytes()
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        self.data += raw
        self.views.append(view)
        acc = {
            "bufferView": len(self.views) - 1,
            "componentType": component_type,
            "count": int(arr.shape[0]),
            "type": acc_type,
        }
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"] = [float(x) for x in np.atleast_1d(arr.min(axis=0))]
            acc["max"] = [float(x) for x in np.atleast_1d(arr.max(axis=0))]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _safe_inv(m: np.ndarray) -> np.ndarray:
    """Inverse, falling back to pseudo-inverse for singular (zero-scale) matrices."""
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(m)


def _quat_from_matrix(r: np.ndarray) -> list[float]:
    m = r
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], dtype=np.float64)
    q /= np.linalg.norm(q)
    return [float(v) for v in q]


def _joint_trs(j: j3d.Joint) -> dict:
    rx, ry, rz = j.rotation
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    node: dict = {"name": j.name}
    if any(abs(v) > 1e-9 for v in j.translation):
        node["translation"] = [float(v) for v in j.translation]
    q = _quat_from_matrix(Rz @ Ry @ Rx)
    if abs(q[3] - 1.0) > 1e-9:
        node["rotation"] = q
    if any(abs(v - 1.0) > 1e-9 for v in j.scale):
        node["scale"] = [float(v) for v in j.scale]
    return node


def _write_textures(model: j3d.Model, tex_dir: Path, rel_prefix: str, stats: ExportStats):
    """Decode TEX1 textures to PNG. Returns (images, samplers, textures) glTF lists,
    aligned so glTF texture i == TEX1 texture i."""
    tex_dir.mkdir(parents=True, exist_ok=True)
    images, samplers, textures = [], [], []
    used_names: dict[str, int] = {}
    for i, t in enumerate(model.textures):
        base = _safe(t.name) or f"tex{i}"
        n = used_names.get(base, 0)
        used_names[base] = n + 1
        fname = f"{base}.png" if n == 0 else f"{base}_{n}.png"
        try:
            rgba = t.decode(0)
            png.write_rgba(tex_dir / fname, rgba)
            stats.texture_colors.append(
                tuple(float(v) for v in rgba[..., :3].mean(axis=(0, 1)) / 255.0)
            )
            stats.texture_images.append(rgba)
        except Exception as e:  # noqa: BLE001
            stats.texture_colors.append((1.0, 0.0, 1.0))
            stats.texture_images.append(None)
            stats.warnings.append(f"texture {t.name}: {e}")
            rgba = np.zeros((4, 4, 4), np.uint8)
            rgba[..., 3] = 255
            rgba[..., 0] = 255
            png.write_rgba(tex_dir / fname, rgba)
        images.append({"uri": f"{rel_prefix}/{fname}", "name": t.name})
        stats.texture_files.append(f"{rel_prefix}/{fname}")
        samplers.append(
            {
                "magFilter": GL_NEAREST if t.mag_filter == 0 else GL_LINEAR,
                "minFilter": GL_NEAREST if t.min_filter == 0 else GL_LINEAR_MIPMAP_LINEAR,
                "wrapS": _WRAP.get(t.wrap_s, GL_REPEAT),
                "wrapT": _WRAP.get(t.wrap_t, GL_REPEAT),
            }
        )
        textures.append({"source": i, "sampler": i, "name": t.name})
    stats.textures = len(textures)
    return images, samplers, textures


class _Composites:
    """Bakes two-layer materials (base x detail in the same UV space, e.g. Wind Waker's
    eye-white shape x pupil texture) into one PNG so the eyes are not blank in glTF."""

    def __init__(self, model, tex_dir, rel_prefix, images, samplers, textures, stats):
        self.model, self.tex_dir, self.rel = model, tex_dir, rel_prefix
        self.images, self.samplers, self.textures, self.stats = images, samplers, textures, stats
        self.cache: dict[tuple, int | None] = {}

    def bake(self, base: int, detail: int, mtx) -> int | None:
        mk = None if mtx is None else (mtx.center, mtx.scale, mtx.rotation, mtx.translation)
        key = (base, detail, mk)
        if key in self.cache:
            return self.cache[key]
        imgs = self.stats.texture_images
        a = imgs[base] if base < len(imgs) else None
        b = imgs[detail] if detail < len(imgs) else None
        out_idx = None
        if a is not None and b is not None and (min(b.shape[:2]) > 8 or b.shape == a.shape):
            h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
            v, u = np.mgrid[0:h, 0:w]
            uv = np.stack([(u + 0.5) / w, (v + 0.5) / h], axis=-1).reshape(-1, 2)
            uv2 = mtx.apply(uv) if mtx is not None else uv
            ta, tb = self.model.textures[base], self.model.textures[detail]

            def sample(img, uvs, wrap_s, wrap_t):
                ih, iw = img.shape[:2]
                x = uvs[:, 0] * iw
                y = uvs[:, 1] * ih
                x = np.mod(x, iw) if wrap_s == 1 else np.clip(x, 0, iw - 1)
                y = np.mod(y, ih) if wrap_t == 1 else np.clip(y, 0, ih - 1)
                return img[np.clip(y.astype(int), 0, ih - 1), np.clip(x.astype(int), 0, iw - 1)]

            pa = sample(a, uv, ta.wrap_s, ta.wrap_t).astype(np.float32) / 255
            pb = sample(b, uv2, tb.wrap_s, tb.wrap_t).astype(np.float32) / 255
            out = (pa * pb * 255 + 0.5).astype(np.uint8).reshape(h, w, 4)
            name = _safe(f"{ta.name}_x_{tb.name}")
            fname = f"{name}.png"
            png.write_rgba(self.tex_dir / fname, out)
            self.images.append({"uri": f"{self.rel}/{fname}", "name": name})
            self.samplers.append(self.samplers[base])
            self.textures.append(
                {"source": len(self.images) - 1, "sampler": len(self.samplers) - 1, "name": name}
            )
            self.stats.texture_images.append(out)
            mean = out[..., :3].mean(axis=(0, 1)) / 255.0
            self.stats.texture_colors.append(tuple(float(x) for x in mean))
            self.stats.texture_files.append(f"{self.rel}/{fname}")
            self.stats.textures = len(self.textures)
            out_idx = len(self.textures) - 1
        self.cache[key] = out_idx
        return out_idx


def _material(m: j3d.Material, model: j3d.Model, comps: _Composites | None = None) -> dict:
    mat: dict = {
        "name": m.name,
        "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
        "doubleSided": m.cull_mode == 0,
    }
    d = m.diffuse(model.textures)
    tex_alpha = False
    if d is not None and d[0] < len(model.textures):
        tex, uv = d
        det = m.detail(model.textures) if comps is not None else None
        if det is not None:
            baked = comps.bake(tex, det[0], det[2])
            if baked is not None:
                names = [model.textures[tex].name, model.textures[det[0]].name]
                mat["extras"] = {"gcrip_composite": names}
                tex_alpha = model.textures[tex].has_alpha or model.textures[det[0]].has_alpha
                tex = baked
        info: dict = {"index": tex}
        if uv:
            info["texCoord"] = uv
        mat["pbrMetallicRoughness"]["baseColorTexture"] = info
        tex_alpha = tex_alpha or (tex < len(model.textures) and model.textures[tex].has_alpha)
    if m.blend_type in (1, 3):
        mat["alphaMode"] = "BLEND"
    elif m.alpha_comp0 != 7 or m.alpha_comp1 != 7:
        # GX alpha test. Most common: GEQUAL ref, or (comp0 GREATER ref0) AND ...
        mat["alphaMode"] = "MASK"
        ref = m.alpha_ref0 if m.alpha_comp0 not in (7, 0) else m.alpha_ref1
        mat["alphaCutoff"] = round(max(1, ref) / 255.0, 4)
    elif tex_alpha:
        mat["alphaMode"] = "OPAQUE"
    return mat


def export(
    model: j3d.Model,
    out_path: Path,
    *,
    flip_winding: bool = True,
    animations: list[ja.Bck] | None = None,
    patterns: list[ja.Btp] | None = None,
    bone_names: str = "original",
    fps: float = 30.0,
) -> ExportStats:
    """Write `<out_path>.gltf`, `<out_path>.bin`, `<out_path>_tex/*.png`.

    animations: BCK clips (joint count must match) -> glTF animations.
    patterns: BTP texture-pattern clips -> KHR_materials_variants ("expressions").
    bone_names: "original" keeps J3D joint names (standard names go to node extras),
        "mixamo" renames recognised humanoid joints to mixamorig:* for retargeting.
    """
    out_path = Path(out_path)
    stem = out_path.name
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = ExportStats()

    images, samplers, textures = _write_textures(
        model, out_dir / f"{stem}_tex", f"{stem}_tex", stats
    )
    comps = _Composites(
        model, out_dir / f"{stem}_tex", f"{stem}_tex", images, samplers, textures, stats
    )
    materials = [_material(m, model, comps) for m in model.materials]
    stats.materials = len(materials)
    for mat in materials:
        bct = mat["pbrMetallicRoughness"].get("baseColorTexture")
        tc = (-1, 0) if bct is None else (bct["index"], bct.get("texCoord", 0))
        stats.material_tex.append(tc)

    buf = _BufferBuilder()
    joints = model.joints
    n_joints = len(joints)
    stats.joints = n_joints
    worlds = np.stack([j.world for j in joints]) if joints else np.eye(4)[None]
    normal_mats = np.stack([_safe_inv(w[:3, :3]).T for w in worlds])

    vd = model.vertices
    if vd.pos is None:
        raise j3d.J3DError("model has no positions")

    # Does the model need a skin?
    any_weighted = any(d.weighted for d in model.draw_matrices)
    use_skin = n_joints > 1 or any_weighted
    stats.skinned = use_skin

    primitives = []
    for shape in model.shapes:
        attrs = dict(shape.attributes)
        has_pn = j3d.VA_PNMTXIDX in attrs
        running_table: list[int] = []
        # per-shape accumulators
        keys_cols: list[np.ndarray] = []
        tri_list: list[np.ndarray] = []
        base = 0
        for pkt in shape.packets:
            if not running_table:
                running_table = list(pkt.matrix_table)
            else:
                for k, v in enumerate(pkt.matrix_table):
                    if v != 0xFFFF:
                        if k < len(running_table):
                            running_table[k] = v
                        else:
                            running_table.append(v)
            table = running_table
            for pr in pkt.primitives:
                if not pr.attrs:
                    continue
                n = len(next(iter(pr.attrs.values())))
                if n == 0:
                    continue
                cols = []
                if has_pn:
                    slot = pr.attrs[j3d.VA_PNMTXIDX] // 3
                    slot = np.clip(slot, 0, max(0, len(table) - 1))
                    drw = np.array([table[s] if table else 0 for s in slot], dtype=np.int64)
                else:
                    drw = np.full(n, table[0] if table else 0, dtype=np.int64)
                cols.append(drw)
                for a in (
                    j3d.VA_POS,
                    j3d.VA_NRM,
                    j3d.VA_CLR0,
                    j3d.VA_CLR1,
                    *range(j3d.VA_TEX0, j3d.VA_TEX7 + 1),
                ):
                    cols.append(pr.attrs[a] if a in pr.attrs else np.full(n, -1, dtype=np.int64))
                keys = np.stack(cols, axis=1)  # (n, 13)
                keys_cols.append(keys)
                tris = j3d.triangulate(pr.opcode, n)
                if len(tris):
                    tri_list.append(tris + base)
                base += n
        if not keys_cols or not tri_list:
            continue
        all_keys = np.concatenate(keys_cols, axis=0)
        all_tris = np.concatenate(tri_list, axis=0)
        uniq, inverse = np.unique(all_keys, axis=0, return_inverse=True)
        inverse = inverse.reshape(-1)
        indices = inverse[all_tris]  # (T,3)
        if flip_winding:
            indices = indices[:, [0, 2, 1]]
        nv = len(uniq)

        drw_idx = uniq[:, 0]
        pos_idx = uniq[:, 1]
        nrm_idx = uniq[:, 2]
        clr_idx = uniq[:, 3:5]
        tex_idx = uniq[:, 5:13]

        # skinning per unique vertex
        jw = np.zeros((nv, 4), np.int64)
        ww = np.zeros((nv, 4), np.float32)
        rigid_joint = np.full(nv, -1, np.int64)
        for vi in range(nv):
            d = int(drw_idx[vi])
            dm = (
                model.draw_matrices[d]
                if 0 <= d < len(model.draw_matrices)
                else j3d.DrawMatrix(False, 0)
            )
            if dm.weighted and dm.index < len(model.envelopes):
                env = model.envelopes[dm.index]
                pairs = sorted(zip(env.weights, env.joints, strict=False), reverse=True)[:4]
                total = sum(w for w, _ in pairs) or 1.0
                for k, (w, jn) in enumerate(pairs):
                    jw[vi, k] = min(jn, n_joints - 1)
                    ww[vi, k] = w / total
            else:
                jn = min(dm.index, n_joints - 1) if n_joints else 0
                jw[vi, 0] = jn
                ww[vi, 0] = 1.0
                rigid_joint[vi] = jn

        # positions
        pos = vd.pos[np.clip(pos_idx, 0, len(vd.pos) - 1)].astype(np.float64)
        rigid = rigid_joint >= 0
        if rigid.any():
            W = worlds[rigid_joint[rigid]]  # (k,4,4)
            p = pos[rigid]
            pos[rigid] = np.einsum("kij,kj->ki", W[:, :3, :3], p) + W[:, :3, 3]
        prim_attrs = {
            "POSITION": buf.add(
                pos.astype(np.float32), GL_FLOAT, "VEC3", GL_ARRAY_BUFFER, minmax=True
            )
        }

        if vd.nrm is not None and (nrm_idx >= 0).all():
            nrm = vd.nrm[np.clip(nrm_idx, 0, len(vd.nrm) - 1)].astype(np.float64)
            if rigid.any():
                NM = normal_mats[rigid_joint[rigid]]
                nrm[rigid] = np.einsum("kij,kj->ki", NM, nrm[rigid])
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            ln[ln == 0] = 1
            nrm = nrm / ln
            prim_attrs["NORMAL"] = buf.add(
                nrm.astype(np.float32), GL_FLOAT, "VEC3", GL_ARRAY_BUFFER
            )

        for c in range(2):
            arr = vd.clr[c]
            if arr is not None and (clr_idx[:, c] >= 0).all():
                col = arr[np.clip(clr_idx[:, c], 0, len(arr) - 1)]
                prim_attrs[f"COLOR_{c}"] = buf.add(
                    col.astype(np.float32), GL_FLOAT, "VEC4", GL_ARRAY_BUFFER
                )

        shape_uvs: dict[int, np.ndarray] = {}
        for t in range(8):
            arr = vd.tex[t]
            if arr is not None and (tex_idx[:, t] >= 0).all():
                uv = arr[np.clip(tex_idx[:, t], 0, len(arr) - 1)]
                shape_uvs[t] = uv.astype(np.float32)
                prim_attrs[f"TEXCOORD_{t}"] = buf.add(
                    uv.astype(np.float32), GL_FLOAT, "VEC2", GL_ARRAY_BUFFER
                )

        if use_skin:
            prim_attrs["JOINTS_0"] = buf.add(
                jw.astype(np.uint16), GL_UNSIGNED_SHORT, "VEC4", GL_ARRAY_BUFFER
            )
            prim_attrs["WEIGHTS_0"] = buf.add(
                ww.astype(np.float32), GL_FLOAT, "VEC4", GL_ARRAY_BUFFER
            )

        flat = indices.reshape(-1)
        if nv < 65536:
            idx_acc = buf.add(
                flat.astype(np.uint16), GL_UNSIGNED_SHORT, "SCALAR", GL_ELEMENT_ARRAY_BUFFER
            )
        else:
            idx_acc = buf.add(
                flat.astype(np.uint32), GL_UNSIGNED_INT, "SCALAR", GL_ELEMENT_ARRAY_BUFFER
            )
        prim = {"attributes": prim_attrs, "indices": idx_acc, "mode": 4}
        if shape.material is not None and shape.material < len(materials):
            prim["material"] = shape.material
        primitives.append((shape, prim))
        stats.geometry.append((pos.astype(np.float32), indices, shape.material))
        stats.uvs.append(shape_uvs)
        stats.shapes += 1
        stats.triangles += len(indices)
        stats.vertices += nv

    if not primitives:
        raise j3d.J3DError("no drawable geometry")

    # nodes: joints first (index == joint index), then one mesh node per shape,
    # named after its material, so alternate face/expression meshes are separate
    # objects in Blender. Detected variants go under a "<model>_variants" node and
    # are flagged hidden (KHR_node_visibility; ignored by older importers).
    nodes = [_joint_trs(j) for j in joints]
    std = rig.standard_bones(joints)
    stats.std_bones = {joints[i].name: n for i, n in std.items()}
    for j in joints:
        if j.children:
            nodes[j.index]["children"] = list(j.children)
        if j.index in std:
            std_name = rig.MIXAMO_PREFIX + std[j.index]
            if bone_names == "mixamo":
                nodes[j.index]["name"] = std_name
                nodes[j.index]["extras"] = {"gcrip_joint": j.name}
            else:
                nodes[j.index]["extras"] = {"gcrip_std_bone": std_name}
    scene_nodes = list(model.root_joints) if joints else []
    variant_of = detect_variants(model)
    stats.variants = {
        model.materials[k].name: model.materials[v].name for k, v in variant_of.items()
    }
    gltf: dict = {
        "asset": {"version": "2.0", "generator": "gcrip"},
        "scene": 0,
        "scenes": [{"name": model.name or stem, "nodes": scene_nodes}],
        "nodes": nodes,
        "meshes": [],
        "materials": materials,
    }
    if use_skin:
        ibm = np.stack([_safe_inv(w) for w in worlds]).transpose(0, 2, 1)  # column-major
        ibm_acc = buf.add(ibm.reshape(n_joints, 16).astype(np.float32), GL_FLOAT, "MAT4", None)
        gltf["skins"] = [
            {
                "name": f"{model.name or stem}_skin",
                "joints": list(range(n_joints)),
                "inverseBindMatrices": ibm_acc,
                "skeleton": model.root_joints[0] if model.root_joints else 0,
            }
        ]
    used_names: dict[str, int] = {}
    root_children: list[int] = []
    variant_children: list[int] = []
    face = _FaceSwitches(model, materials, patterns or [], stats, comps)
    for shape, prim in primitives:
        mat_name = (
            model.materials[shape.material].name
            if shape.material is not None and shape.material < len(model.materials)
            else f"shape{shape.index}"
        )
        n = used_names.get(mat_name, 0)
        used_names[mat_name] = n + 1
        node_name = mat_name if n == 0 else f"{mat_name}.{n:03d}"
        gltf["meshes"].append({"name": node_name, "primitives": [prim]})
        node: dict = {"name": node_name, "mesh": len(gltf["meshes"]) - 1}
        if use_skin:
            node["skin"] = 0
        is_variant = shape.material in variant_of
        if is_variant:
            node["extras"] = {"gcrip_variant_of": model.materials[variant_of[shape.material]].name}
            node["extensions"] = {"KHR_node_visibility": {"visible": False}}
        nodes.append(node)
        (variant_children if is_variant else root_children).append(len(nodes) - 1)
        # texture-switch clones of face meshes (one hidden mesh per alternate texture)
        for alt_mat, tex_name in face.alternates(shape.material):
            clone = dict(prim)
            clone["material"] = alt_mat
            clone.pop("extensions", None)
            cname = f"{node_name}@{tex_name}"
            gltf["meshes"].append({"name": cname, "primitives": [clone]})
            cnode: dict = {
                "name": cname,
                "mesh": len(gltf["meshes"]) - 1,
                "extras": {"gcrip_variant_of": mat_name, "gcrip_texture": tex_name},
                "extensions": {"KHR_node_visibility": {"visible": False}},
            }
            if use_skin:
                cnode["skin"] = 0
            nodes.append(cnode)
            variant_children.append(len(nodes) - 1)
    ext_used: set[str] = set()
    group: dict = {"name": model.name or stem, "children": root_children}
    if variant_children:
        nodes.append({"name": f"{model.name or stem}_variants", "children": variant_children})
        group["children"] = root_children + [len(nodes) - 1]
        ext_used.add("KHR_node_visibility")
    nodes.append(group)
    scene_nodes.append(len(nodes) - 1)
    if face.presets(gltf, primitives):
        ext_used.add("KHR_materials_variants")
        group["extras"] = {"gcrip_expressions": stats.expressions}
    stats.materials = len(materials)
    if animations:
        _add_animations(gltf, buf, model, animations, fps, stats)
    if ext_used:
        gltf["extensionsUsed"] = sorted(ext_used)
    if images:
        gltf["images"] = images
        gltf["samplers"] = samplers
        gltf["textures"] = textures
    gltf["buffers"] = [{"uri": f"{stem}.bin", "byteLength": len(buf.data)}]
    gltf["bufferViews"] = buf.views
    gltf["accessors"] = buf.accessors

    (out_dir / f"{stem}.bin").write_bytes(bytes(buf.data))
    (out_dir / f"{stem}.gltf").write_text(json.dumps(gltf, separators=(",", ":")), encoding="utf-8")
    return stats


_DUP_SUFFIX = re.compile(r"^\(\d+\)$")


def detect_variants(model: j3d.Model) -> dict[int, int]:
    """Find alternate/expression meshes: shapes on the same joint whose material
    name extends another shape's material name by a short suffix (eyeL ->
    eyeLdamA, mayuR -> mayuRdamB) and whose bounding boxes overlap. J3D's "(2)"
    duplicate-name suffixes don't count. Returns {variant material: base material}."""
    by_joint: dict[int | None, list[j3d.Shape]] = {}
    for sh in model.shapes:
        by_joint.setdefault(sh.joint, []).append(sh)

    def overlaps(a: j3d.Shape, b: j3d.Shape) -> bool:
        amin, amax = np.array(a.bbox_min), np.array(a.bbox_max)
        bmin, bmax = np.array(b.bbox_min), np.array(b.bbox_max)
        if not (np.isfinite(amin).all() and np.isfinite(bmin).all()):
            return True
        if np.all(amax == amin) or np.all(bmax == bmin):
            return True  # no bbox info
        pad = 0.25 * np.maximum(amax - amin, bmax - bmin)
        return bool(np.all(amax + pad >= bmin) and np.all(bmax + pad >= amin))

    out: dict[int, int] = {}
    for shapes in by_joint.values():
        first: dict[str, j3d.Shape] = {}
        for sh in shapes:
            if sh.material is None or sh.material >= len(model.materials):
                continue
            first.setdefault(model.materials[sh.material].name, sh)
        for name, sh in first.items():
            for base, bsh in first.items():
                if base == name or not name.startswith(base) or len(base) < 3:
                    continue
                suffix = name[len(base) :]
                if _DUP_SUFFIX.match(suffix) or len(suffix) > 4 or suffix[0] == "_":
                    continue
                if bsh.material in out or not overlaps(sh, bsh):
                    continue
                out[sh.material] = bsh.material
                break
    return out


def winding_agreement(model: j3d.Model) -> float | None:
    """Fraction of triangles whose geometric normal (as triangulated, unflipped)
    agrees with the stored vertex normals. ~1.0 => keep, ~0.0 => flip. Used to
    calibrate `flip_winding` empirically."""
    vd = model.vertices
    if vd.pos is None or vd.nrm is None:
        return None
    agree = total = 0
    for shape in model.shapes:
        for pkt in shape.packets:
            for pr in pkt.primitives:
                if j3d.VA_POS not in pr.attrs or j3d.VA_NRM not in pr.attrs:
                    continue
                n = len(pr.attrs[j3d.VA_POS])
                tris = j3d.triangulate(pr.opcode, n)
                if not len(tris):
                    continue
                p = vd.pos[np.clip(pr.attrs[j3d.VA_POS], 0, len(vd.pos) - 1)]
                nn = vd.nrm[np.clip(pr.attrs[j3d.VA_NRM], 0, len(vd.nrm) - 1)]
                a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
                fn = np.cross(b - a, c - a)
                vn = nn[tris[:, 0]] + nn[tris[:, 1]] + nn[tris[:, 2]]
                d = np.einsum("ij,ij->i", fn, vn)
                agree += int((d > 0).sum())
                total += int((d != 0).sum())
    return agree / total if total else None


__all__ = ["ExportStats", "export", "winding_agreement"]


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _diffuse_slot(m: j3d.Material, textures: list) -> int | None:
    """Which of the 8 texture slots the exported base-color texture came from."""
    d = m.diffuse(textures)
    if d is None:
        return None
    for slot, t in enumerate(m.tex_slots):
        if t == d[0]:
            return slot
    return None


class _FaceSwitches:
    """Facial expressions from BTP texture-pattern animations.

    J3D characters change expression by swapping the eye/mouth/brow textures of a
    few materials per frame. We expose that two ways:
      * alternates(material): every alternate texture any BTP assigns to that
        material -> a duplicate glTF material; export() clones the face mesh once per
        texture as a hidden node ("eyeL@eyeh.3") so switching an expression in
        Blender is just toggling visibility, no add-on settings needed.
      * presets(): the distinct multi-material states the BTPs actually reach
        (e.g. "link_freez", "talk#4") as KHR_materials_variants.
    """

    def __init__(self, model, materials, patterns, stats, comps=None):
        self.model = model
        self.materials = materials
        self.stats = stats
        self.comps = comps
        self.mat_index = {m.name: m.index for m in model.materials}
        self.slot_of = {m.index: _diffuse_slot(m, model.textures) for m in model.materials}
        self.alt_mat: dict[tuple[int, int], int] = {}  # (base material, tex) -> material
        self.by_material: dict[int, list[int]] = {}  # base material -> textures (ordered)
        self.states: list[tuple[str, dict[int, int]]] = []
        self._canon: dict[int, int] = {}
        self._by_image: dict[tuple, int] = {}
        seen: dict[tuple, int] = {}
        # single-state BTPs are named expressions - keep them first
        for btp in sorted(patterns, key=lambda b: len(b.states()) > 1):
            sts = btp.states()
            multi = len(sts) > 1
            for frame, key in sts:
                state: dict[int, int] = {}
                for mat_name, slot, tex in key:
                    mi = self.mat_index.get(mat_name)
                    if mi is None or slot != self.slot_of.get(mi):
                        continue
                    if not 0 <= tex < len(model.textures):
                        continue
                    tex = self._canonical(tex)
                    default = self._canonical(model.materials[mi].tex_slots[slot])
                    if tex != default and self._plausible(default, tex):
                        state[mi] = tex
                        lst = self.by_material.setdefault(mi, [])
                        if tex not in lst:
                            lst.append(tex)
                if not state:
                    continue
                sig = tuple(sorted(state.items()))
                if sig in seen or len(self.states) >= 256:
                    continue
                seen[sig] = len(self.states)
                self.states.append((f"{btp.name}#{frame}" if multi else btp.name, state))
        if len(seen) >= 256:
            stats.warnings.append("more than 256 expression presets; extra ones dropped")

    def _canonical(self, tex: int) -> int:
        """TEX1 often holds the same image twice under one name; treat them as one."""
        if tex not in self._canon:
            t = self.model.textures[tex]
            key = (t.fmt, t.width, t.height, t.data)
            self._canon[tex] = self._by_image.setdefault(key, tex)
        return self._canon[tex]

    def _plausible(self, default: int, tex: int) -> bool:
        """BTPs from other archives may index a differently ordered TEX1; only accept
        swaps to a texture of the same size/format and name family (eyeh.1 -> eyeh.3)."""
        a, b = self.model.textures[default], self.model.textures[tex]
        if (a.width, a.height, a.fmt) != (b.width, b.height, b.fmt):
            return False
        pa = re.match(r"[A-Za-z]*", a.name).group(0).lower()
        pb = re.match(r"[A-Za-z]*", b.name).group(0).lower()
        return not (pa and pb and pa != pb)

    def _alt(self, mi: int, tex: int) -> int:
        k = (mi, tex)
        if k not in self.alt_mat:
            m = json.loads(json.dumps(self.materials[mi]))
            m["name"] = f"{self.model.materials[mi].name}@{self.model.textures[tex].name}"
            gl_tex = tex
            det = (
                self.model.materials[mi].detail(self.model.textures)
                if self.comps is not None
                else None
            )
            if det is not None:
                baked = self.comps.bake(tex, det[0], det[2])
                if baked is not None:
                    gl_tex = baked
            m["pbrMetallicRoughness"]["baseColorTexture"]["index"] = gl_tex
            self.materials.append(m)
            self.alt_mat[k] = len(self.materials) - 1
        return self.alt_mat[k]

    def alternates(self, mi: int | None) -> list[tuple[int, str]]:
        """[(glTF material index, texture name)] for a shape's material."""
        if mi is None or mi not in self.by_material:
            return []
        texs = sorted(self.by_material[mi], key=lambda t: _natural(self.model.textures[t].name))
        return [(self._alt(mi, t), self.model.textures[t].name) for t in texs]

    def presets(self, gltf: dict, primitives) -> bool:
        if not self.states:
            return False
        for shape, prim in primitives:
            mi = shape.material
            if mi is None:
                continue
            by_mat: dict[int, list[int]] = {}
            for vi, (_, state) in enumerate(self.states):
                if mi in state:
                    by_mat.setdefault(self._alt(mi, state[mi]), []).append(vi)
            if by_mat:
                prim.setdefault("extensions", {})["KHR_materials_variants"] = {
                    "mappings": [{"material": m, "variants": v} for m, v in by_mat.items()]
                }
        gltf.setdefault("extensions", {})["KHR_materials_variants"] = {
            "variants": [{"name": n} for n, _ in self.states]
        }
        self.stats.expressions = [n for n, _ in self.states]
        return True


class _ClipBuilder:
    def __init__(self, buf: _BufferBuilder, full_in: int, const_in: int):
        self.buf, self.full_in, self.const_in = buf, full_in, const_in
        self.samplers: list[dict] = []
        self.channels: list[dict] = []

    def channel(self, node: int, path: str, data: np.ndarray, full: bool, acc_type: str) -> None:
        if full:
            inp = self.full_in
            arr = data.astype(np.float32)
        else:
            inp = self.const_in
            arr = np.stack([data, data]).astype(np.float32)
        outp = self.buf.add(arr, GL_FLOAT, acc_type, None)
        self.samplers.append({"input": inp, "output": outp, "interpolation": "LINEAR"})
        self.channels.append(
            {"sampler": len(self.samplers) - 1, "target": {"node": node, "path": path}}
        )


def _add_animations(gltf, buf, model, animations, fps, stats) -> None:
    joints = model.joints
    n = len(joints)
    rest_t = np.array([j.translation for j in joints], np.float64)
    rest_r = np.degrees(np.array([j.rotation for j in joints], np.float64))
    rest_s = np.array([j.scale for j in joints], np.float64)
    out = []
    time_cache: dict[int, int] = {}
    used_names: dict[str, int] = {}

    def times(count: int) -> int:
        if count not in time_cache:
            t = np.arange(count, dtype=np.float32) / fps
            time_cache[count] = buf.add(t, GL_FLOAT, "SCALAR", None, minmax=True)
        return time_cache[count]

    def const_or_rest(tracks: list[ja.Track], rest: np.ndarray) -> np.ndarray:
        return np.array(
            [t.sample(0.0) if len(t.keys) else rest[k] for k, t in enumerate(tracks)],
            np.float64,
        )

    for bck in animations:
        if bck.joint_count != n:
            stats.warnings.append(
                f"animation {bck.name}: {bck.joint_count} joints, model has {n}; skipped"
            )
            continue
        nf = max(1, bck.duration) + 1
        frames = np.arange(nf, dtype=np.float64)
        end_t = (nf - 1) / fps
        const_in = buf.add(
            np.array([0.0, end_t], np.float32), GL_FLOAT, "SCALAR", None, minmax=True
        )
        clip = _ClipBuilder(buf, times(nf), const_in)
        channel = clip.channel

        for ji, jt in enumerate(bck.joints):
            if any(not t.constant for t in jt.rotation):
                eul = np.stack([t.sample_frames(frames) for t in jt.rotation], axis=1)
                q = np.array([ja.euler_xyz_to_quat(*e) for e in eul])
                for k in range(1, len(q)):  # keep quaternion continuity for interpolation
                    if np.dot(q[k], q[k - 1]) < 0:
                        q[k] = -q[k]
                channel(ji, "rotation", q, True, "VEC4")
            else:
                e = const_or_rest(jt.rotation, rest_r[ji])
                channel(ji, "rotation", ja.euler_xyz_to_quat(*e), False, "VEC4")
            if any(not t.constant for t in jt.translation):
                tr = np.stack([t.sample_frames(frames) for t in jt.translation], axis=1)
                channel(ji, "translation", tr, True, "VEC3")
            else:
                channel(ji, "translation", const_or_rest(jt.translation, rest_t[ji]), False, "VEC3")
            if any(not t.constant for t in jt.scale):
                sc = np.stack([t.sample_frames(frames) for t in jt.scale], axis=1)
                channel(ji, "scale", sc, True, "VEC3")
            else:
                v = const_or_rest(jt.scale, rest_s[ji])
                if not np.allclose(v, 1.0):
                    channel(ji, "scale", v, False, "VEC3")
        k = used_names.get(bck.name, 0)
        used_names[bck.name] = k + 1
        out.append(
            {
                "name": bck.name if k == 0 else f"{bck.name}.{k}",
                "samplers": clip.samplers,
                "channels": clip.channels,
                "extras": {
                    "gcrip_loop": bck.loops,
                    "gcrip_loop_mode": ja.LOOP_NAMES.get(bck.loop_mode, str(bck.loop_mode)),
                    "gcrip_frames": bck.duration,
                    "gcrip_fps": fps,
                },
            }
        )
        stats.animations.append(out[-1]["name"])
    if out:
        gltf["animations"] = out
