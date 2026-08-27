"""Evaluate a parsed HSD model into a Scene: JOBJs become joints in HSD traversal order,
every POBJ display list is decoded against its vertex attribute arrays, and vertices are
baked into world space the way the runtime's matrix setup does it - rigid POBJs use their
JOBJ's matrix (or the single bind JOBJ), envelope POBJs blend joint matrices through the
inverse bind matrices, single-weight envelopes use the joint matrix directly. Materials
come from the MOBJ (texture from the first UV-mapped TOBJ)."""

from __future__ import annotations

import math

import numpy as np

from gcrip.formats import hsd
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

_MAX_INFLUENCES = 4


class TextureCache:
    """Decoded textures for one archive, keyed by image + palette pointer."""

    def __init__(self, dat: hsd.DatFile, names: dict[int, str], prefix: str) -> None:
        self.dat = dat
        self.names = names
        self.prefix = prefix
        self.decoded: dict[tuple[int, int], tuple[str, np.ndarray] | None] = {}
        self.warnings: list[str] = []

    def get(self, t: hsd.Tobj) -> tuple[str, np.ndarray] | None:
        if t.image is None:
            return None
        key = (t.image.offset, t.tlut.offset if t.tlut else 0)
        if key in self.decoded:
            return self.decoded[key]
        base = self.names.get(t.image.offset) or f"{self.prefix}_{t.image.offset:06x}"
        if t.tlut and t.image.offset in self.names and t.tlut.offset not in self.names:
            base = f"{base}_{t.tlut.offset:x}"
        try:
            img = hsd.decode_texture(self.dat, t.image, t.tlut)
            entry: tuple[str, np.ndarray] | None = (base, img)
        except (hsd.HsdError, ValueError) as e:
            self.warnings.append(f"texture {base}: {e}")
            entry = None
        self.decoded[key] = entry
        return entry


def _pick_tobj(m: hsd.Mobj) -> hsd.Tobj | None:
    uv = [t for t in m.tobjs if t.flags & hsd.TEX_COORD_MASK == hsd.TEX_COORD_UV and t.image]
    for t in uv:
        cm = t.flags & hsd.TEX_COLORMAP_MASK
        if cm not in (hsd.TEX_COLORMAP_NONE, hsd.TEX_COLORMAP_ALPHA_MASK, hsd.TEX_COLORMAP_PASS):
            return t
    return uv[0] if uv else None


def _uv_transform(t: hsd.Tobj) -> np.ndarray | None:
    """HSD texture matrix: the inverse of the TOBJ's SRT, applied to (s, t, 1)."""
    sx, sy = t.scale[0], t.scale[1]
    if t.rotation == (0.0, 0.0, 0.0) and (sx, sy) == (1.0, 1.0) and t.translation[:2] == (0.0, 0.0):
        return None
    if abs(sx) < 1e-8 or abs(sy) < 1e-8:
        return None
    rz = t.rotation[2]
    c, s = math.cos(rz), math.sin(rz)
    tx, ty = t.translation[0], t.translation[1]
    m = np.array([[c * sx, -s * sy, tx], [s * sx, c * sy, ty], [0, 0, 1]])
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return None


class _Bucket:
    __slots__ = ("keys", "pos", "nrm", "uv", "col", "joints", "weights", "idx", "has_nrm",
                 "has_uv", "has_col")

    def __init__(self) -> None:
        self.keys: dict[tuple, int] = {}
        self.pos: list = []
        self.nrm: list = []
        self.uv: list = []
        self.col: list = []
        self.joints: list = []
        self.weights: list = []
        self.idx: list[int] = []
        self.has_nrm = self.has_uv = self.has_col = False


def evaluate(dat: hsd.DatFile, model: hsd.Model, name: str, textures: TextureCache) -> Scene:
    scene = Scene(name=name)
    scene.warnings += model.warnings
    order, world = hsd.world_matrices(model.roots)
    by_offset = {j.offset: j for j in order}
    for j in order:
        scene.joints.append(
            Joint(
                name=f"joint_{j.index:03d}",
                parent=j.parent,
                translation=tuple(float(x) for x in j.position),
                rotation=hsd.quat_from_matrix(hsd.rotation_matrix(j.rotation)),
                scale=tuple(float(x) for x in j.scale),
            )
        )
    reader = hsd.AttrReader(dat)
    mat_index: dict[tuple, int] = {}
    buckets: dict[int, _Bucket] = {}
    stats = {"hidden": 0, "shape": 0, "missing_joint": 0, "unknown_prim": 0}

    def skin_matrix(j: hsd.Jobj) -> np.ndarray:
        return world[j.index]

    def envelope_matrices(p: hsd.Pobj) -> list[tuple[np.ndarray, list[tuple[int, float]]]]:
        out = []
        for env in p.envelopes:
            m = np.zeros((4, 4))
            infl: list[tuple[int, float]] = []
            entries = [(by_offset.get(jo), w) for jo, w in env.entries]
            entries = [(jj, w) for jj, w in entries if jj is not None]
            if not entries:
                stats["missing_joint"] += 1
                out.append((np.eye(4), []))
                continue
            if len(entries) == 1 and entries[0][1] >= 1.0 - 1e-6:
                jj = entries[0][0]
                out.append((world[jj.index], [(jj.index, 1.0)]))
                continue
            for jj, w in entries:
                ib = jj.inv_bind if jj.inv_bind is not None else np.eye(4)
                m += w * (world[jj.index] @ ib)
                infl.append((jj.index, w))
            out.append((m, infl))
        return out

    def material_for(
        mobj: hsd.Mobj | None, p: hsd.Pobj
    ) -> tuple[int, hsd.Tobj | None, np.ndarray | None]:
        tobj = _pick_tobj(mobj) if mobj else None
        tex = textures.get(tobj) if tobj else None
        rm = mobj.rendermode if mobj else 0
        double = (p.flags & hsd.POBJ_CULL_MASK) == 0
        alpha = mobj.alpha if mobj else 1.0
        if tex:
            color = (1.0, 1.0, 1.0, alpha)
        elif mobj is not None:
            r, g, b, _ = mobj.diffuse
            color = (r, g, b, alpha)
        else:
            color = (1.0, 1.0, 1.0, 1.0)
        color = tuple(round(float(c), 4) for c in color)
        mdef = MaterialDef(
            name=tex[0] if tex else f"mat_{mobj.offset:x}" if mobj else "mat_none",
            texture=tex[0] if tex else None,
            base_color=color,
            alpha_blend=bool(rm & hsd.RENDER_XLU) or color[3] < 0.999,
            double_sided=double,
            clamp_u=bool(tobj and tobj.wrap_s == 0),
            clamp_v=bool(tobj and tobj.wrap_t == 0),
            mirror_u=bool(tobj and tobj.wrap_s == 2),
            mirror_v=bool(tobj and tobj.wrap_t == 2),
            unlit=not (rm & hsd.RENDER_DIFFUSE),
        )
        key = (mdef.texture, mdef.base_color, mdef.alpha_blend, mdef.double_sided, mdef.clamp_u,
               mdef.clamp_v, mdef.mirror_u, mdef.mirror_v, mdef.unlit)
        mi = mat_index.get(key)
        if mi is None:
            mi = len(scene.materials)
            mat_index[key] = mi
            if not tex:
                mdef.name = f"mat_{mi:02d}_" + "".join(f"{int(c * 255):02x}" for c in color[:3])
            else:
                scene.textures.setdefault(tex[0], tex[1])
            scene.materials.append(mdef)
        return mi, tobj, (_uv_transform(tobj) if tobj else None)

    def draw_pobj(j: hsd.Jobj, dobj: hsd.Dobj, p: hsd.Pobj) -> None:
        if p.ptype == hsd.POBJ_SHAPEANIM:
            stats["shape"] += 1
            return
        calls = hsd.parse_display_list(p.display, p.attrs)
        if not calls:
            return
        attrs = {a.attr: a for a in p.attrs if a.attr_type}
        if hsd.VA_POS not in attrs:
            return
        mi, tobj, uvm = material_for(dobj.mobj, p)
        uv_attr = hsd.VA_TEX0 + max(0, min(7, tobj.src - 4)) if tobj else None
        b = buckets.setdefault(mi, _Bucket())
        use_vertex_color = bool(dobj.mobj and dobj.mobj.rendermode & hsd.RENDER_VERTEX)
        # matrices available to PNMTXIDX
        if p.ptype == hsd.POBJ_ENVELOPE:
            table = envelope_matrices(p)
        else:
            table = [(skin_matrix(j), [(j.index, 1.0)])]
            sj = by_offset.get(p.skin_jobj) if p.skin_jobj else None
            if sj is not None:
                table.append((skin_matrix(sj), [(sj.index, 1.0)]))
            if p.skin_jobj and sj is None:
                stats["missing_joint"] += 1
        # per-attribute value tables (indexed) or direct decoders
        pos_a, nrm_a = attrs[hsd.VA_POS], attrs.get(hsd.VA_NRM) or attrs.get(hsd.VA_NBT)
        col_a = attrs.get(hsd.VA_CLR0) if use_vertex_color else None
        tex_a = attrs.get(uv_attr) if uv_attr is not None else None
        def values(call: hsd.DrawCall, a: hsd.VtxAttr | None) -> np.ndarray | None:
            if a is None or a.attr not in call.fields:
                return None
            f = call.fields[a.attr]
            if a.attr_type == hsd.GX_DIRECT:
                return reader.direct(a, f)
            return reader.array(a, int(f.max()) + 1)[f]

        def corner_key(call: hsd.DrawCall, a: hsd.VtxAttr | None, vals, k: int):
            """Index for indexed attributes, the value itself for direct ones."""
            if vals is None:
                return None
            if a.attr_type != hsd.GX_DIRECT:
                return int(call.fields[a.attr][k])
            return tuple(vals[k])

        known = (hsd.PRIM_TRIANGLES, hsd.PRIM_TRISTRIP, hsd.PRIM_TRIFAN, hsd.PRIM_QUADS)
        for call in calls:
            tri = hsd.triangulate(call.opcode, call.count)
            if len(tri) == 0:
                if call.opcode not in known:
                    stats["unknown_prim"] += 1
                continue
            n = call.count
            pv = values(call, pos_a)
            if pv is None:
                continue
            if pv.shape[1] == 2:
                pv = np.concatenate([pv, np.zeros((n, 1), np.float32)], axis=1)
            nv = values(call, nrm_a)
            if nv is not None and nv.shape[1] > 3:
                nv = nv[:, :3]
            cv = values(call, col_a)
            tv = values(call, tex_a)
            if tv is not None and tv.shape[1] == 1:
                tv = np.concatenate([tv, np.zeros((n, 1), np.float32)], axis=1)
            if tv is not None and uvm is not None:
                tv = (np.concatenate([tv, np.ones((n, 1), np.float32)], axis=1) @ uvm.T)[:, :2]
            if tv is not None and tobj is not None and (tobj.repeat_s > 1 or tobj.repeat_t > 1):
                tv = tv * np.array([tobj.repeat_s, tobj.repeat_t], np.float32)
            mtx_idx = call.fields.get(hsd.VA_PNMTXIDX)
            if mtx_idx is not None:
                mtx_idx = np.asarray(mtx_idx).reshape(n, -1)[:, 0].astype(np.int64) // 3
            else:
                mtx_idx = np.zeros(n, np.int64)
            # key per corner so identical corners are shared
            local: list[int] = []
            for k in range(n):
                mi_k = int(mtx_idx[k])
                if mi_k >= len(table):
                    mi_k = 0
                key = (
                    p.offset,
                    mi_k,
                    corner_key(call, pos_a, pv, k),
                    corner_key(call, nrm_a, nv, k),
                    corner_key(call, tex_a, tv, k),
                    corner_key(call, col_a, cv, k),
                )
                vi = b.keys.get(key)
                if vi is None:
                    vi = len(b.pos)
                    b.keys[key] = vi
                    m, infl = table[mi_k]
                    b.pos.append(m[:3, :3] @ pv[k] + m[:3, 3])
                    if nv is not None:
                        b.nrm.append(m[:3, :3] @ nv[k])
                        b.has_nrm = True
                    else:
                        b.nrm.append(None)
                    if tv is not None:
                        b.uv.append(tv[k])
                        b.has_uv = True
                    else:
                        b.uv.append(None)
                    if cv is not None:
                        b.col.append(cv[k])
                        b.has_col = True
                    else:
                        b.col.append(None)
                    b.joints.append(infl)
                local.append(vi)
            la = np.array(local, np.int64)
            b.idx.extend(la[tri].reshape(-1).tolist())

    for j in order:
        if j.hidden:
            stats["hidden"] += 1
            continue
        for dobj in j.dobjs:
            for p in dobj.pobjs:
                draw_pobj(j, dobj, p)

    for mi, b in buckets.items():
        n = len(b.pos)
        if n == 0 or not b.idx:
            continue
        pos = np.array(b.pos, np.float32).reshape(n, 3)
        nrm = None
        if b.has_nrm:
            nrm = np.array([v if v is not None else (0, 0, 1) for v in b.nrm], np.float32)
        uv = None
        if b.has_uv:
            uv = np.array([v if v is not None else (0, 0) for v in b.uv], np.float32)
        col = None
        if b.has_col:
            col = np.array([v if v is not None else (1, 1, 1, 1) for v in b.col], np.float32)
        joints = np.zeros((n, 4), np.uint16)
        weights = np.zeros((n, 4), np.float32)
        for vi, infl in enumerate(b.joints):
            infl = sorted(infl, key=lambda t: -t[1])[:_MAX_INFLUENCES]
            total = sum(w for _, w in infl) or 1.0
            for k, (ji, w) in enumerate(infl):
                joints[vi, k] = ji
                weights[vi, k] = w / total
            if not infl:
                weights[vi, 0] = 1.0
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=pos,
                indices=np.array(b.idx, np.uint32),
                normals=nrm,
                uvs=uv,
                colors=col,
                joints=joints,
                weights=weights,
            )
        )
    scene.warnings += textures.warnings
    textures.warnings = []
    if stats["shape"]:
        scene.warnings.append(f"{stats['shape']} shape-animation POBJs skipped")
    if stats["missing_joint"]:
        scene.warnings.append(
            f"{stats['missing_joint']} envelopes referenced joints outside the model"
        )
    if stats["unknown_prim"]:
        scene.warnings.append(f"{stats['unknown_prim']} non-triangle primitives skipped")
    scene.extras = {"hsd_hidden_joints": stats["hidden"], "hsd_version": dat.version}
    return scene
