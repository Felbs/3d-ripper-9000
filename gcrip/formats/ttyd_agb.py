"""Paper Mario: The Thousand-Year Door AnimGroup actors (``a/<name>``) -> AnimGroup.

The "paper" characters, enemies and props: a group tree (joints) whose leaves reference
shapes made of triangle-fan draws over shared f32 vertex arrays, textured from the sibling
``a/<name>-`` TPL and animated by keyframed deltas on the node floats, vertices, texture
matrices and visibility.  Reverse-engineered by noclip.website (``PaperMarioTTYD/AnimGroup.ts``)
and verified here on the 658 G8ME01 actors.  All offsets are absolute file offsets.

  0x000 u32 size of the tables before the animation data
  0x004 char[0x40] .anm name   0x044 char[0x40] .tex name
  0x084 char[0x40] build time  0x0D0 6f bbox
  0x0E8 counts: shapes, draw calls, vtx pos, idx pos, vtx nrm, idx nrm, vtx clr, idx clr,
        idx tex[8], vtx tex, tex mtx, tex base, textures, draws, vis, node floats, groups,
        anims (u32 each, 0x0E8..0x148)
  0x14C the same 25 tables' offsets (u32 each, 0x14C..0x1AC)

  shape (0xA8): char[0x40] name, (first, count) pairs for pos/nrm/clr @0x40 and tex @0x58,
        draw start/count @0x98, display mode @0xA0 (0 alpha-test, 1 opaque, 2 alpha-test
        late, 3 blend), cull @0xA4 (0 back, 1 front, 2/3 none)
  draw (0x6C): u32 tex count, u32 tev mode @0x08, i32 tex id[8] @0x10, i8 tex array[8]
        @0x30, u32 draw-call start/count @0x38, index-buffer starts pos/nrm/clr @0x40,
        tex[8] @0x4C
  draw call (0x08): u32 first index, u32 vertex count - one GX triangle fan
  index buffers: u32 per vertex, per attribute, relative to the shape's first vertex
  vertex buffers: pos/nrm f32 x3, clr RGBA8, tex f32 x2
  tex mtx (0x18): u8 texture index add, f32 transS transT scaleS scaleT rotate(deg)
  tex base (0x08): u32 texture index base, i32 wrap flags (1 repeat S, 2 repeat T,
        4 mirror S, 8 mirror T, <0 = TPL default)
  texture (0x40): u32 ?, u32 TPL image index @0x04, u32 type @0x08, char[0x28] name @0x0C
  group (0x58): char[0x40] name, i32 next sibling, i32 first child, i32 shape, u32 vis
        index, u32 node index (into the float array), u32 segment-scale-compensate;
        the root group is the last one
  node floats (24 per group): translation, scale, rotation1 (half angles), rotation2,
        rotation centre, scale centre, rotation pivot, scale pivot
  anim table (0x40): char[0x3C] name, u32 data offset; data: sizes/counts + relative
        offsets of loop info (u32 loop, f32 start, f32 end) and keyframes
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.j3d import PRIM_TRIFAN, triangulate

HEADER_SIZE = 0x1B0


class AGBError(Exception):
    pass


@dataclass
class Draw:
    tex_ids: list[int]
    tev_mode: int
    positions: np.ndarray | None  # (N,3) f32 in shape/group space
    triangles: np.ndarray  # (T,3)
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: list[np.ndarray | None] = field(default_factory=list)


@dataclass
class Shape:
    name: str
    draws: list[Draw]
    disp_mode: int
    cull: int


@dataclass
class TexMtx:
    index_add: int
    trans_s: float
    trans_t: float
    scale_s: float
    scale_t: float
    rotate: float


@dataclass
class TexBase:
    index_base: int
    wrap_flags: int


@dataclass
class Texture:
    arc_index: int
    type: int
    name: str


@dataclass
class Group:
    name: str
    next_sibling: int
    first_child: int
    shape: int
    vis: int
    node: int
    ssc: bool


@dataclass
class Anim:
    name: str
    loop: bool
    start: float
    end: float
    frames: int


@dataclass
class AnimGroup:
    anm_name: str
    tex_name: str
    build_time: str
    shapes: list[Shape]
    tex_mtx: list[TexMtx]
    tex_base: list[TexBase]
    textures: list[Texture]
    groups: list[Group]
    node: np.ndarray  # float32 array
    vis: np.ndarray  # u8 array
    anims: list[Anim]
    warnings: list[str] = field(default_factory=list)

    def visible(self, g: Group) -> bool:
        return g.vis >= len(self.vis) or bool(self.vis[g.vis])


def looks_like_agb(head: bytes, size: int, name: str = "") -> bool:
    if len(head) < 0x20 or size < HEADER_SIZE:
        return False
    (fs,) = struct.unpack_from(">I", head, 0)
    if fs < HEADER_SIZE or fs > size:
        return False
    anm = head[4:0x44].split(b"\0", 1)[0]  # the rip sniffs 64 bytes: names may be cut
    if not anm or any(c < 0x20 or c > 0x7E for c in anm):
        return False
    text = anm.decode()
    return not name or text == name or name.startswith(text) or text.startswith(name)


def _cstr(data: bytes, off: int, limit: int) -> str:
    return data[off : off + limit].split(b"\0", 1)[0].decode("shift_jis", "replace")


def _f32(data: bytes, off: int, count: int, cols: int) -> np.ndarray:
    count = max(0, min(count, (len(data) - off) // (4 * cols)))
    return np.frombuffer(data, ">f4", count * cols, off).reshape(count, cols).astype(np.float32)


def parse(data: bytes) -> AnimGroup:
    if len(data) < HEADER_SIZE:
        raise AGBError("too small")
    (fs,) = struct.unpack_from(">I", data, 0)
    if fs < HEADER_SIZE or fs > len(data):
        raise AGBError(f"section size field {fs} does not fit {len(data)} bytes")
    warnings: list[str] = []
    anm_name = _cstr(data, 0x04, 0x40)
    tex_name = _cstr(data, 0x44, 0x40)
    build_time = _cstr(data, 0x84, 0x40)
    counts = struct.unpack_from(">25I", data, 0xE8)
    offs = struct.unpack_from(">25I", data, 0x14C)
    (
        n_shape,
        _n_dc,
        n_vpos,
        _n_ipos,
        n_vnrm,
        _n_inrm,
        n_vclr,
        _n_iclr,
        *_n_itex,
        n_vtex,
        n_texmtx,
        n_texbase,
        n_tex,
        n_draw,
        n_vis,
        n_node,
        n_group,
        n_anim,
    ) = counts
    (
        o_shape,
        o_dc,
        o_vpos,
        o_ipos,
        o_vnrm,
        o_inrm,
        o_vclr,
        o_iclr,
        *o_itex,
        o_vtex,
        o_texmtx,
        o_texbase,
        o_tex,
        o_draw,
        o_vis,
        o_node,
        o_group,
        o_anim,
    ) = offs
    for c, o in zip(counts, offs, strict=True):
        if c and o > len(data):  # unused tables (count 0) may carry junk offsets
            raise AGBError(f"table offset {o:#x} beyond file")

    vpos = _f32(data, o_vpos, n_vpos, 3)
    vnrm = _f32(data, o_vnrm, n_vnrm, 3)
    n_vclr = max(0, min(n_vclr, (len(data) - o_vclr) // 4))
    vclr = np.frombuffer(data, "u1", n_vclr * 4, o_vclr).reshape(n_vclr, 4)
    vtex = _f32(data, o_vtex, n_vtex, 2)

    def indices(off: int, start: int, count: int) -> np.ndarray:
        pos = off + start * 4
        count = max(0, min(count, (len(data) - pos) // 4))
        return np.frombuffer(data, ">u4", count, pos).astype(np.int64)

    shapes: list[Shape] = []
    for i in range(n_shape):
        so = o_shape + i * 0xA8
        if so + 0xA8 > len(data):
            break
        name = _cstr(data, so, 0x40)
        pos_first, pos_count, nrm_first, nrm_count, clr_first, clr_count = struct.unpack_from(
            ">6I", data, so + 0x40
        )
        tex_first, tex_count = struct.unpack_from(">II", data, so + 0x58)
        draw_start, draw_count, disp_mode, cull = struct.unpack_from(">4I", data, so + 0x98)
        draws: list[Draw] = []
        for d in range(min(draw_count, n_draw)):
            do = o_draw + (draw_start + d) * 0x6C
            if do + 0x6C > len(data):
                break
            (tex_n,) = struct.unpack_from(">I", data, do)
            (tev_mode,) = struct.unpack_from(">I", data, do + 8)
            tex_n = min(tex_n, 8)
            tex_ids = list(struct.unpack_from(f">{tex_n}i", data, do + 0x10)) if tex_n else []
            run_start, run_count, i_pos, i_nrm, i_clr = struct.unpack_from(">5I", data, do + 0x38)
            i_tex = struct.unpack_from(">8I", data, do + 0x4C)
            rows_pos, rows_nrm, rows_clr, tris = [], [], [], []
            rows_tex = [[] for _ in range(tex_n)]
            base = 0
            for r in range(run_count):
                co = o_dc + (run_start + r) * 8
                if co + 8 > len(data):
                    break
                first, count = struct.unpack_from(">II", data, co)
                if count < 3:
                    continue
                t = triangulate(PRIM_TRIFAN, count)
                ip = indices(o_ipos, first + i_pos, count)
                if len(ip) < count:
                    break
                rows_pos.append(ip)
                if nrm_count:
                    rows_nrm.append(indices(o_inrm, first + i_nrm, count))
                if clr_count:
                    rows_clr.append(indices(o_iclr, first + i_clr, count))
                for t_i in range(tex_n):
                    rows_tex[t_i].append(indices(o_itex[t_i], first + i_tex[t_i], count))
                tris.append(t + base)
                base += count
            if not rows_pos:
                continue
            ip = np.concatenate(rows_pos) + pos_first
            positions = vpos[np.minimum(ip, max(len(vpos) - 1, 0))] if len(vpos) else None
            draw = Draw(tex_ids, tev_mode, positions, np.concatenate(tris))
            if rows_nrm and len(vnrm):
                inr = np.concatenate(rows_nrm)
                if len(inr) == len(ip):
                    draw.normals = vnrm[np.minimum(inr + nrm_first, len(vnrm) - 1)]
            if rows_clr and len(vclr):
                ic = np.concatenate(rows_clr)
                if len(ic) == len(ip):
                    draw.colors = (
                        vclr[np.minimum(ic + clr_first, len(vclr) - 1)].astype(np.float32) / 255.0
                    )
            for t_i in range(tex_n):
                it = np.concatenate(rows_tex[t_i]) if rows_tex[t_i] else None
                if it is not None and len(it) == len(ip) and len(vtex):
                    draw.uvs.append(vtex[np.minimum(it + tex_first, len(vtex) - 1)])
                else:
                    draw.uvs.append(None)
            draws.append(draw)
        shapes.append(Shape(name, draws, disp_mode, cull))

    tex_mtx = []
    for i in range(n_texmtx):
        o = o_texmtx + i * 0x18
        if o + 0x18 > len(data):
            break
        add = data[o]
        tex_mtx.append(TexMtx(add, *struct.unpack_from(">5f", data, o + 4)))
    tex_base = []
    for i in range(n_texbase):
        o = o_texbase + i * 8
        if o + 8 > len(data):
            break
        tex_base.append(TexBase(*struct.unpack_from(">Ii", data, o)))
    textures = []
    for i in range(n_tex):
        o = o_tex + i * 0x40
        if o + 0x40 > len(data):
            break
        arc, typ = struct.unpack_from(">II", data, o + 4)
        textures.append(Texture(arc, typ, _cstr(data, o + 0x0C, 0x28)))
    groups = []
    for i in range(n_group):
        o = o_group + i * 0x58
        if o + 0x58 > len(data):
            break
        nxt, child, shape, vis, node, ssc = struct.unpack_from(">iiiIII", data, o + 0x40)
        groups.append(Group(_cstr(data, o, 0x40), nxt, child, shape, vis, node, bool(ssc)))
    node = _f32(data, o_node, n_node, 1).reshape(-1)
    n_vis = max(0, min(n_vis, len(data) - o_vis))
    vis = np.frombuffer(data, "u1", n_vis, o_vis)
    anims = []
    for i in range(n_anim):
        o = o_anim + i * 0x40
        if o + 0x40 > len(data):
            break
        name = _cstr(data, o, 0x3C)
        (doff,) = struct.unpack_from(">I", data, o + 0x3C)
        if not doff or doff + 0x40 > len(data):
            continue
        frames = struct.unpack_from(">I", data, doff + 8)[0]
        (loop_rel,) = struct.unpack_from(">I", data, doff + 0x24)
        lo = doff + loop_rel
        if lo + 12 > len(data):
            continue
        loop, start, end = struct.unpack_from(">Iff", data, lo)
        anims.append(Anim(name, bool(loop), start, end, frames))
    if not groups:
        raise AGBError("no groups")
    return AnimGroup(
        anm_name,
        tex_name,
        build_time,
        shapes,
        tex_mtx,
        tex_base,
        textures,
        groups,
        node,
        vis,
        anims,
        warnings,
    )


# --- evaluation helpers -----------------------------------------------------------------


def group_order(agb: AnimGroup) -> tuple[list[int], dict[int, int]]:
    """Depth-first group indices from the root (the last group) and each group's parent.
    Invisible groups hide their whole subtree, exactly like the game's draw walk."""
    order: list[int] = []
    parents: dict[int, int] = {}
    n = len(agb.groups)
    stack = [(n - 1, -1)]
    seen: set[int] = set()
    while stack:
        gi, parent = stack.pop()
        if gi < 0 or gi >= n or gi in seen:
            continue
        seen.add(gi)
        g = agb.groups[gi]
        order.append(gi)
        parents[gi] = parent
        if 0 <= g.next_sibling < n:
            stack.append((g.next_sibling, parent))
        if agb.visible(g) and 0 <= g.first_child < n:
            stack.append((g.first_child, gi))
    return order, parents


def _t(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _rx(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], float)


def _ry(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], float)


def _rz(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], float)


def node_matrix(node: np.ndarray, idx: int, ssc_parent: int = -1) -> np.ndarray:
    """The game's node matrix (noclip computeNodeMatrix) from 24 floats at ``idx``."""
    if idx < 0 or idx + 24 > len(node):
        return np.eye(4)
    v = node[idx : idx + 24].astype(float)
    t, s, r1, r2, rc, sc, rp, sp = (v[i : i + 3] for i in range(0, 24, 3))
    scale = _t(*(sc + sp)) @ np.diag([s[0], s[1], s[2], 1.0]) @ _t(*(-sc))
    rot = _rz(r2[2]) @ _ry(r2[1]) @ _rx(r2[0]) @ _rz(r1[2] * 2) @ _ry(r1[1] * 2) @ _rx(r1[0] * 2)
    rot = _t(*(rc + rp)) @ rot @ _t(*(-rc))
    if ssc_parent >= 0 and ssc_parent + 6 <= len(node):
        ps = node[ssc_parent + 3 : ssc_parent + 6].astype(float)
        ps = np.where(np.abs(ps) > 1e-8, ps, 1.0)
        rot = np.diag([1 / ps[0], 1 / ps[1], 1 / ps[2], 1.0]) @ rot
    return _t(*t) @ rot @ scale


def texture_index(agb: AnimGroup, tex_id: int) -> int | None:
    """TPL image index for a draw's texture id: base + the tex matrix's animated add."""
    if tex_id < 0 or tex_id >= len(agb.tex_base):
        return None
    add = agb.tex_mtx[tex_id].index_add if tex_id < len(agb.tex_mtx) else 0
    ti = agb.tex_base[tex_id].index_base + add
    if ti < 0 or ti >= len(agb.textures):
        return None
    return agb.textures[ti].arc_index


def apply_tex_mtx(uv: np.ndarray, tm: TexMtx) -> np.ndarray:
    """noclip computeTexMatrix: T(.5,.5) R(-rot) T(-.5,-.5) T(trans) S(scale)."""
    theta = math.radians(-tm.rotate)
    c, s = math.cos(theta), math.sin(theta)
    rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    m = np.eye(3)
    m[:2, 2] = (0.5, 0.5)
    m = m @ rot
    back = np.eye(3)
    back[:2, 2] = (-0.5, -0.5)
    trans = np.eye(3)
    trans[:2, 2] = (tm.trans_s, tm.trans_t)
    m = m @ back @ trans @ np.diag([tm.scale_s, tm.scale_t, 1.0])
    if np.allclose(m, np.eye(3), atol=1e-6):
        return uv
    return (uv @ m[:2, :2].T + m[:2, 2]).astype(np.float32)
