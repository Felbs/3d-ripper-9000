"""Paper Mario: The Thousand-Year Door map geometry (``m/<map>/d``) -> Model.

Layout (big-endian, verified on all 333 G8ME01 maps; matches noclip.website's
``PaperMarioTTYD/world.ts`` and the ``mapdata`` headers of the TTYD decompilation):

  0x00 u32 file size            0x04 u32 main-data size
  0x08 u32 pointer-fixup count  0x0C u32 named-chunk count (7 = ver1.00, 8 = ver1.02)
  0x20      main data (all "relative offsets" below are from here)
  +main     fixup table (u32 each), then named chunks (u32 offset, u32 name offset),
            then the chunk-name string table

Named chunks, in file order: animation_table, curve_table, fog_table, information,
light_table, material_name_table, texture_table, [vcd_table].

  information:   u32 version string, u32 scene-graph root, u32 S-node name, u32 A-node name
  texture_table: u32 count, then count x u32 name-string offsets - index-aligned with the
                 images of the sibling ``t`` TPL (``b/<map>.tpl`` holds the sky/background);
                 samplers reach textures by name through their own texture entries
  material_name_table: u32 count, then (u32 name, u32 material) pairs
  material: u32 name, u32 RGBA8 colour, u8 colour source, u8 pad, u8 layer (0 opaque,
            1 alpha-test, 2 blend), u8 sampler count, 8 x u32 sampler pointers (0x0C),
            8 x 7 floats texture transforms (0x2C: transS transT scaleS scaleT rot cS cT),
            u32 tev config pointer at 0x110 (first byte = tev mode)
  sampler:  u32 texture entry, u32 0, u8 wrapS, u8 wrapT, u8 layer
  texture entry: u32 name, u8 flags, ..., u16 width @0x08, u16 height @0x0A
  scene-graph node: u32 name, u32 type ("mesh"/"null"), u32 parent, u32 first child,
            u32 next sibling, u32 prev sibling, 3f scale, 3f rotation (degrees),
            3f translation, 6f bbox, u32 draw-mode struct @0x58 (byte 1 = cull mode:
            0 front, 1 back, 2/3 none), u32 part count @0x5C, then (material, mesh) pairs
  mesh:     byte 3 = packed flag, u32 display-list count @0x04, u32 vcd bits @0x08,
            u32 vcd table @0x0C, then (offset, size) pairs @0x10
  vcd_table: u32 pos, nrm, clr count, clr0, clr1, tex count, tex0..2 array pointers
            (each array = u32 count + data), pos shift @0x44, tex shifts @0x48/0x4C/0x50

Packed (ver1.02) meshes are GX display lists with INDEX16 for every attribute the vcd bits
name (POS s16 with the pos shift, NRM s16/14, CLR0 RGBA8, TEXn s16 with the tex shift).
Raw (ver1.00) meshes store per-vertex index tuples (12 x u16, 0xFFFF = absent) drawn as
one triangle strip per entry over f32 arrays.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.j3d import PRIM_TRISTRIP, triangulate

MAIN = 0x20
CHUNK_NAMES_102 = (
    "animation_table",
    "curve_table",
    "fog_table",
    "information",
    "light_table",
    "material_name_table",
    "texture_table",
    "vcd_table",
)

VCD_POS = 1 << 0
VCD_NRM = 1 << 1
VCD_CLR0 = 1 << 2
VCD_CLR1 = 1 << 3
VCD_TEX0 = 1 << 4


class TTYDMapError(Exception):
    pass


@dataclass
class Sampler:
    texture: int  # index into Model.texture_names
    wrap_s: int
    wrap_t: int
    layer: int


@dataclass
class TexXform:
    trans_s: float
    trans_t: float
    scale_s: float
    scale_t: float
    rotation: float
    center_s: float
    center_t: float


@dataclass
class Material:
    name: str
    color: tuple[int, int, int, int]
    color_src: int
    layer: int  # 0 opaque, 1 alpha test, 2 blend (max over material + samplers)
    samplers: list[Sampler]  # in table order (noclip: TEXMAP0 = last entry)
    xforms: list[TexXform]
    tev_mode: int


@dataclass
class Mesh:
    """One draw batch: indexed vertices resolved against the map's vertex arrays."""

    positions: np.ndarray  # (N,3) f32
    triangles: np.ndarray  # (T,3) int64 into the per-mesh vertex list
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None  # (N,4) f32
    uvs: list[np.ndarray | None] = field(default_factory=list)  # per tex set (N,2)


@dataclass
class Part:
    material: int
    mesh: Mesh


@dataclass
class Node:
    name: str
    type: str
    parent: int
    children: list[int]
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float]  # degrees, applied Z*Y*X (SRT)
    translation: tuple[float, float, float]
    cull: int  # 0 front, 1 back, 2/3 none
    draw_flags: int
    parts: list[Part]


@dataclass
class Model:
    version: str
    texture_names: list[str]
    materials: list[Material]
    nodes: list[Node]
    root: int
    s_node: str
    a_node: str
    warnings: list[str] = field(default_factory=list)


def looks_like_map(head: bytes, size: int) -> bool:
    if len(head) < 0x20 or size < 0x40:
        return False
    fs, ms, nfix, nchunk = struct.unpack_from(">IIII", head, 0)
    return fs == size and ms + 0x20 <= size and nchunk in (7, 8) and nfix * 4 + ms <= size


def _cstr(data: bytes, off: int, limit: int = 0x100) -> str:
    end = data.find(b"\0", off, off + limit)
    if end < 0:
        end = min(off + limit, len(data))
    return data[off:end].decode("shift_jis", "replace")


def _chunks(data: bytes) -> dict[str, int]:
    fs, ms, nfix, nchunk = struct.unpack_from(">IIII", data, 0)
    if fs != len(data):
        raise TTYDMapError(f"file size field {fs} != {len(data)}")
    table = MAIN + ms + nfix * 4
    strs = table + nchunk * 8
    out = {}
    for i in range(nchunk):
        off, name_off = struct.unpack_from(">II", data, table + i * 8)
        out[_cstr(data, strs + name_off, 0x40)] = MAIN + off
    return out


def _array(data: bytes, rel: int, dtype, cols: int) -> np.ndarray:
    if rel == 0:
        return np.zeros((0, cols), np.dtype(dtype).newbyteorder("="))
    off = MAIN + rel
    (count,) = struct.unpack_from(">I", data, off)
    item = np.dtype(dtype).itemsize * cols
    count = min(count, (len(data) - off - 4) // item)
    return np.frombuffer(data, dtype=dtype, count=count * cols, offset=off + 4).reshape(count, cols)


@dataclass
class _Vcd:
    pos: np.ndarray
    nrm: np.ndarray
    clr0: np.ndarray
    tex: list[np.ndarray]
    pos_shift: int
    tex_shift: list[int]


def _vcd(data: bytes, off: int, packed: bool) -> _Vcd:
    ptrs = struct.unpack_from(">9I", data, off)
    pos_shift, *tex_shift = struct.unpack_from(">4I", data, off + 0x44)
    if packed:
        pos = _array(data, ptrs[0], ">i2", 3)
        nrm = _array(data, ptrs[1], ">i2", 3)
        tex = [_array(data, ptrs[6 + i], ">i2", 2) for i in range(3)]
    else:
        pos = _array(data, ptrs[0], ">f4", 3)
        nrm = _array(data, ptrs[1], ">f4", 3)
        tex = [_array(data, ptrs[6 + i], ">f4", 2) for i in range(3)]
    clr0 = _array(data, ptrs[3], "u1", 4)
    return _Vcd(pos, nrm, clr0, tex, pos_shift, list(tex_shift))


def _material(data: bytes, off: int, tex_index: dict[str, int], warnings: list[str]) -> Material:
    name = _cstr(data, MAIN + struct.unpack_from(">I", data, off)[0])
    r, g, b, a, color_src, _pad, layer, n_samp = struct.unpack_from(">4B4B", data, off + 4)
    samplers = []
    xforms = []
    for i in range(min(n_samp, 8)):
        (srel,) = struct.unpack_from(">I", data, off + 0x0C + i * 4)
        soff = MAIN + srel
        (trel,) = struct.unpack_from(">I", data, soff)
        wrap_s, wrap_t, slayer = struct.unpack_from(">3B", data, soff + 8)
        layer = max(layer, slayer)
        tname = _cstr(data, MAIN + struct.unpack_from(">I", data, MAIN + trel)[0], 0x40)
        tex = tex_index.get(tname)
        if tex is None:
            warnings.append(f"material {name}: texture {tname!r} not in texture table")
            tex = -1
        samplers.append(Sampler(tex, wrap_s, wrap_t, slayer))
        xforms.append(TexXform(*struct.unpack_from(">7f", data, off + 0x2C + i * 0x1C)))
    (tev_rel,) = struct.unpack_from(">I", data, off + 0x110)
    tev_mode = data[MAIN + tev_rel] if tev_rel and MAIN + tev_rel < len(data) else 0
    return Material(name, (r, g, b, a), color_src, min(layer, 2), samplers, xforms, tev_mode)


def _packed_mesh(data: bytes, moff: int, vcd: _Vcd, warnings: list[str]) -> Mesh | None:
    n_dl, bits = struct.unpack_from(">II", data, moff + 4)
    fields = []
    if bits & VCD_POS:
        fields.append(("pos", ">u2"))
    if bits & VCD_NRM:
        fields.append(("nrm", ">u2"))
    if bits & VCD_CLR0:
        fields.append(("clr", ">u2"))
    if bits & VCD_CLR1:
        fields.append(("clr1", ">u2"))
    for t in range(8):
        if bits & (VCD_TEX0 << t):
            fields.append((f"tex{t}", ">u2"))
    if not fields or not (bits & VCD_POS):
        warnings.append(f"mesh @{moff:#x}: vcd bits {bits:#x} without positions")
        return None
    vdt = np.dtype(fields)
    stride = vdt.itemsize
    rows, tris = [], []
    base = 0
    for i in range(n_dl):
        rel, size = struct.unpack_from(">II", data, moff + 0x10 + i * 8)
        start = MAIN + rel
        dl = data[start : start + size]
        pos = 0
        while pos + 3 <= len(dl):
            op = dl[pos]
            if op == 0:
                break
            count = dl[pos + 1] << 8 | dl[pos + 2]
            pos += 3
            end = pos + count * stride
            if end > len(dl):
                break
            arr = np.frombuffer(dl, dtype=vdt, count=count, offset=pos)
            pos = end
            t = triangulate(op, count)
            if len(t):
                rows.append(arr)
                tris.append(t + base)
                base += count
    if not rows:
        return None
    verts = np.concatenate(rows)
    uniq, inverse = np.unique(verts, return_inverse=True)
    tri = inverse.reshape(-1)[np.concatenate(tris)]
    return _resolve(uniq, tri, vcd, fields, packed=True)


def _raw_mesh(data: bytes, moff: int, vcd: _Vcd) -> Mesh | None:
    (n_entries,) = struct.unpack_from(">I", data, moff + 4)
    rows, tris = [], []
    base = 0
    for i in range(n_entries):
        (rel,) = struct.unpack_from(">I", data, moff + 0x10 + i * 4)
        off = MAIN + rel
        (count,) = struct.unpack_from(">I", data, off)
        count = min(count, (len(data) - off - 4) // 0x18)
        arr = np.frombuffer(data, dtype=">u2", count=count * 12, offset=off + 4).reshape(count, 12)
        t = triangulate(PRIM_TRISTRIP, count)
        if len(t):
            rows.append(arr)
            tris.append(t + base)
            base += count
    if not rows:
        return None
    verts = np.concatenate(rows)
    uniq, inverse = np.unique(verts, axis=0, return_inverse=True)
    tri = inverse.reshape(-1)[np.concatenate(tris)]
    fields = [("pos", 0), ("nrm", 1), ("clr", 2), ("tex0", 4), ("tex1", 5), ("tex2", 6)]
    rec = np.zeros(len(uniq), dtype=[(f, ">u2") for f, _ in fields])
    for f, col in fields:
        rec[f] = uniq[:, col]
    return _resolve(rec, tri, vcd, [(f, ">u2") for f, _ in fields], packed=False)


def _gather(arr: np.ndarray, idx: np.ndarray) -> np.ndarray:
    if len(arr) == 0:
        return np.zeros((len(idx), arr.shape[1]), np.float32)
    return arr[np.minimum(idx.astype(np.int64), len(arr) - 1)]


def _resolve(rec, tri: np.ndarray, vcd: _Vcd, fields, packed: bool) -> Mesh:
    names = [f for f, _ in fields]
    pos = _gather(vcd.pos, rec["pos"]).astype(np.float32)
    if packed:
        pos = pos / float(1 << vcd.pos_shift)
    mesh = Mesh(pos, tri.astype(np.int64))
    if "nrm" in names and len(vcd.nrm):
        idx = rec["nrm"]
        ok = idx != 0xFFFF
        if ok.any():
            n = _gather(vcd.nrm, np.where(ok, idx, 0)).astype(np.float32)
            if packed:
                n = n / 16384.0
            mesh.normals = n
    if "clr" in names and len(vcd.clr0):
        idx = rec["clr"]
        c = _gather(vcd.clr0, np.where(idx != 0xFFFF, idx, 0)).astype(np.float32) / 255.0
        if not packed:
            c[idx == 0xFFFF] = 1.0
        mesh.colors = c
    for t in range(3):
        key = f"tex{t}"
        if key in names and len(vcd.tex[t]):
            idx = rec[key]
            uv = _gather(vcd.tex[t], np.where(idx != 0xFFFF, idx, 0)).astype(np.float32)
            if packed:
                uv = uv / float(1 << vcd.tex_shift[t])
            mesh.uvs.append(uv)
        else:
            mesh.uvs.append(None)
    return mesh


def parse(data: bytes) -> Model:
    if len(data) < 0x40:
        raise TTYDMapError("too small")
    chunks = _chunks(data)
    for need in ("information", "material_name_table", "texture_table"):
        if need not in chunks:
            raise TTYDMapError(f"missing chunk {need}")
    warnings: list[str] = []
    info = chunks["information"]
    ver_rel, root_rel, s_rel, a_rel = struct.unpack_from(">4I", data, info)
    version = _cstr(data, MAIN + ver_rel, 0x10)
    s_node = _cstr(data, MAIN + s_rel, 0x40) if s_rel else ""
    a_node = _cstr(data, MAIN + a_rel, 0x40) if a_rel else ""
    packed_version = version != "ver1.00"

    # textures: table order == TPL image order
    toff = chunks["texture_table"]
    (n_tex,) = struct.unpack_from(">I", data, toff)
    texture_names = []
    tex_index: dict[str, int] = {}
    for i in range(n_tex):
        (rel,) = struct.unpack_from(">I", data, toff + 4 + i * 4)
        name = _cstr(data, MAIN + rel, 0x40)
        tex_index.setdefault(name, i)
        texture_names.append(name)

    moff = chunks["material_name_table"]
    (n_mat,) = struct.unpack_from(">I", data, moff)
    materials: list[Material] = []
    mat_index: dict[int, int] = {}
    for i in range(n_mat):
        _nrel, rel = struct.unpack_from(">II", data, moff + 4 + i * 8)
        mat_index[MAIN + rel] = len(materials)
        materials.append(_material(data, MAIN + rel, tex_index, warnings))

    vcd_cache: dict[int, _Vcd] = {}
    mesh_cache: dict[int, Mesh | None] = {}

    def mesh_at(rel: int) -> Mesh | None:
        if rel in mesh_cache:
            return mesh_cache[rel]
        off = MAIN + rel
        packed = bool(data[off + 3]) if packed_version else False
        (vrel,) = struct.unpack_from(">I", data, off + 0x0C)
        if vrel not in vcd_cache:
            vcd_cache[vrel] = _vcd(data, MAIN + vrel, packed)
        vcd = vcd_cache[vrel]
        try:
            m = _packed_mesh(data, off, vcd, warnings) if packed else _raw_mesh(data, off, vcd)
        except (ValueError, struct.error) as ex:
            warnings.append(f"mesh @{off:#x}: {ex}")
            m = None
        mesh_cache[rel] = m
        return m

    nodes: list[Node] = []
    seen: set[int] = set()
    # iterative walk: wide levels would blow the recursion limit
    _index_of: dict[int, int] = {}
    _next_sib: dict[int, int] = {}

    def read_tree(rel: int, parent: int) -> None:
        stack = [(rel, parent)]
        while stack:
            r, p = stack.pop()
            off = MAIN + r
            if off in seen or off + 0x60 > len(data):
                continue
            i = _read_one(r, p)
            if i < 0:
                continue
            _index_of[off] = i
            _child_rel, sib_rel = struct.unpack_from(">II", data, off + 0x0C)
            _next_sib[i] = sib_rel
            if sib_rel:
                stack.append((sib_rel, p))
            if _child_rel:
                stack.append((_child_rel, i))

    def _read_one(rel: int, parent: int) -> int:
        off = MAIN + rel
        seen.add(off)
        name_rel, type_rel, _prel, _child, _sib, _prev = struct.unpack_from(">6I", data, off)
        sx, sy, sz, rx, ry, rz, tx, ty, tz = struct.unpack_from(">9f", data, off + 0x18)
        (dm_rel,) = struct.unpack_from(">I", data, off + 0x58)
        cull, draw_flags = 1, 0
        if dm_rel and MAIN + dm_rel + 3 <= len(data):
            cull = data[MAIN + dm_rel + 1]
            draw_flags = data[MAIN + dm_rel + 2]
        (n_parts,) = struct.unpack_from(">I", data, off + 0x5C)
        idx = len(nodes)
        node = Node(
            _cstr(data, MAIN + name_rel, 0x40),
            _cstr(data, MAIN + type_rel, 0x10),
            parent,
            [],
            (sx, sy, sz),
            (rx, ry, rz),
            (tx, ty, tz),
            cull,
            draw_flags,
            [],
        )
        nodes.append(node)
        if parent >= 0:
            nodes[parent].children.append(idx)
        for i in range(min(n_parts, 64)):
            mrel, merel = struct.unpack_from(">II", data, off + 0x60 + i * 8)
            if mrel == 0 or merel == 0:
                continue
            mat = mat_index.get(MAIN + mrel)
            if mat is None:
                warnings.append(f"node {node.name}: material @{mrel:#x} not in table")
                continue
            m = mesh_at(merel)
            if m is not None:
                node.parts.append(Part(mat, m))
        return idx

    read_tree(root_rel, -1)
    if not nodes:
        raise TTYDMapError("empty scene graph")
    return Model(version, texture_names, materials, nodes, 0, s_node, a_node, warnings)
