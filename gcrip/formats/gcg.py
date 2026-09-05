"""Runecraft ``.gcg`` GameCube geometry (Mat Hoffman's Pro BMX 2, GMHE52) and its
``.gct`` textures / ``.gcm`` INI materials.

Every model, park chunk, rider and bike on the disc is a ``gcg\\0`` file - 4,730 of them,
50 MB.  Before this reader existed the ``gx`` fallback scanned them: it found the f32
position arrays (the extents looked right) but paired them with the wrong index words,
so 472 of 533 exported models were flagged in the quality audit (76-81% zero-length
edges on the park chunks, s16 ``+-32768`` clouds on the props).

Layout (big-endian throughout)::

    "gcg\\0"  u32 version(3)  u32 nnodes
    nnodes x node record (224 bytes):
        char name[64]  pad[64]  f32 matrix[16] (row-major, translation in row 3,
        parent-relative)  f32 pivot[3]  f32 maxabs[3]  f32 radius  s32 parent (-1 root)
    one mesh section:
        u32 nmat  nmat x char material[64]        # material = "<name>.gcm" text file
        u32 1  f32 lod_distance(FLT_MAX)  u32 nsub
        nsub x submesh:
            u32 material index (0xFFFFFFFF = none, e.g. collision-only `po_col*`)
            u8 flags (0x80 = explicit vertex format follows)  u8 attr mask
            u8 1  u8 0xFF  u8 0  f32 radius  u16 nverts
            [flags & 0x80: u32 pos comp type (3 s16 / 4 f32)  u8 pos frac
                           u32 nrm comp type  u8 nrm frac
                           u16 0  u8 uv comp type  u8 uv frac]
            u8 pos element size  nverts x position
            [mask & 2: u8 size  nverts x normal   (3 = s8/64, 12 = f32)]
            [mask & 4: u8 size  nverts x colour   (4 = RGBA8, 2 = RGB5A3)]
            [mask & 8: u8 size  nverts x uv       (2 = u8/2^frac, 4 = s16/2^frac, 8 = f32)]
            u32 nbatch  nbatch x u32 draw count  u32 dl_size  GX display list
    [nnodes > 1: u32 1  u32 n  u8 node order[n] (4-aligned)  u32 nnodes]

The display list is plain GX (``0x80`` quads / ``0x90`` tris / ``0x98`` strip / ``0xA0``
fan, u16 count) with one **u16 index per set attribute** per vertex, attribute order
pos, nrm, col, uv; 0x00 pads to 32 bytes.  s16 positions are ``value / 2**frac`` (the
node's ``maxabs`` then equals the largest |coordinate| exactly, which is how the frac was
pinned down: po_vdeck12 frac 11 -> 27368/2048 = 13.363 = maxabs.z).

Riders, bikes and multi-node props set attr-mask bit 0x40: the list then interleaves
``LOAD_INDX_A/B`` matrix loads (``0x20`` / ``0x28``, u16 node index, u16 addr|size) with
the draws, and every vertex begins with a direct u8 ``PNMTXIDX``.  Vertices are stored in
the space of the node they bind to (rigid binding, one node per vertex, no weights);
``world_matrices`` composes the node hierarchy so a reader can bake them.

Textures ``.gct``: ``u32 1  u32 paletted(0/1)  u32 nmips  u32 ncolors  u32 w  u32 h``,
then for paletted files ``ncolors`` RGB5A3 entries, then per mip level ``u32 w  u32 h
u32 size`` + tiled GX data (C8 when paletted, CMPR otherwise), smallest level first
(a 128x128 with 8 levels stores 1x1 .. 64x64 before the base image).  Materials ``.gcm`` are
INI text: ``[ShaderPass_1] TextureMap_1 = <stem>``; the texture is
``<stem>.gct`` next to the material (``TRACKS/<park>/textures/`` for park chunks,
``GLOBAL/riders/`` / ``GLOBAL/bikes/`` for characters).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

MAGIC = b"gcg\0"
NODE_SIZE = 224
PRIM_OPS = {0x80: "quads", 0x90: "tris", 0x98: "strip", 0xA0: "fan"}
NO_MATERIAL = 0xFFFFFFFF


class GcgError(ValueError):
    pass


@dataclass
class Submesh:
    material: int  # index into Node.materials, or NO_MATERIAL
    positions: np.ndarray  # (N,3) f32, node-local
    normals: np.ndarray | None
    colors: np.ndarray | None  # (N,4) u8
    uvs: np.ndarray | None  # (N,2) f32
    prims: list[tuple[int, np.ndarray]]  # (opcode, (count, nfields) u16 indices)
    binds: list[np.ndarray]  # per primitive: node index per vertex (-1 = rigid)
    radius: float = 0.0

    @property
    def skinned(self) -> bool:
        return any(len(b) and int(b.max()) >= 0 for b in self.binds)


@dataclass
class Node:
    name: str
    matrix: np.ndarray  # (4,4) f32 row-major, translation in row 3, parent-relative
    pivot: tuple[float, float, float]
    maxabs: tuple[float, float, float]
    radius: float
    parent: int


@dataclass
class Model:
    version: int
    nodes: list[Node]
    materials: list[str] = field(default_factory=list)
    submeshes: list[Submesh] = field(default_factory=list)
    order: list[int] = field(default_factory=list)  # multi-node trailer: node draw order
    end: int = 0  # byte offset the parse stopped at (== len(data) for a clean file)


def is_gcg(head: bytes) -> bool:
    return len(head) >= 12 and head[:4] == MAGIC and struct.unpack_from(">I", head, 8)[0] > 0


# -- vertex attribute decoders -----------------------------------------------------------


def _positions(data: bytes, at: int, n: int, size: int, comp: int, frac: int) -> np.ndarray:
    if size == 12:
        return np.frombuffer(data, ">f4", n * 3, at).reshape(n, 3).astype(np.float32)
    if size == 6:
        raw = np.frombuffer(data, ">i2", n * 3, at).reshape(n, 3).astype(np.float32)
        return raw / np.float32(1 << frac)
    raise GcgError(f"position element size {size}")


def _normals(data: bytes, at: int, n: int, size: int) -> np.ndarray:
    if size == 12:
        return np.frombuffer(data, ">f4", n * 3, at).reshape(n, 3).astype(np.float32)
    if size == 3:
        return np.frombuffer(data, np.int8, n * 3, at).reshape(n, 3).astype(np.float32) / 64.0
    if size == 6:
        return np.frombuffer(data, ">i2", n * 3, at).reshape(n, 3).astype(np.float32) / 16384.0
    raise GcgError(f"normal element size {size}")


def _colors(data: bytes, at: int, n: int, size: int) -> np.ndarray:
    if size == 4:
        return np.frombuffer(data, np.uint8, n * 4, at).reshape(n, 4).copy()
    if size == 2:
        v = np.frombuffer(data, ">u2", n, at).astype(np.uint16)
        return gx_texture._rgb5a3_to_rgba(v).reshape(n, 4)
    if size == 3:
        rgb = np.frombuffer(data, np.uint8, n * 3, at).reshape(n, 3)
        return np.concatenate([rgb, np.full((n, 1), 255, np.uint8)], axis=1)
    raise GcgError(f"colour element size {size}")


def _uvs(data: bytes, at: int, n: int, size: int, comp: int, frac: int) -> np.ndarray:
    if size == 8:
        return np.frombuffer(data, ">f4", n * 2, at).reshape(n, 2).astype(np.float32)
    if size == 4:
        dt = ">u2" if comp == 2 else ">i2"
        raw = np.frombuffer(data, dt, n * 2, at).reshape(n, 2).astype(np.float32)
        return raw / np.float32(1 << frac)
    if size == 2:
        dt = np.uint8 if comp == 0 else np.int8
        raw = np.frombuffer(data, dt, n * 2, at).reshape(n, 2).astype(np.float32)
        return raw / np.float32(1 << frac)
    raise GcgError(f"uv element size {size}")


# -- parsing -------------------------------------------------------------------------------


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin1")


def _display_list(
    dl: bytes, nfields: int, skinned: bool
) -> tuple[list[tuple[int, np.ndarray]], list[np.ndarray]]:
    """(opcode, (count, nfields) u16 indices) per primitive, plus the node index each
    vertex is bound to (-1 when the submesh is rigid).

    Skinned lists (mask 0x40) carry GX ``LOAD_INDX_A`` (0x20, position matrix) /
    ``LOAD_INDX_B`` (0x28, normal matrix) commands - ``u16 array index, u16 addr|size`` -
    that load node matrices into the ten position-matrix slots, and every vertex then
    starts with a direct u8 ``PNMTXIDX`` (slot * 3) picking one of them.  The array index
    is the node number, so the slot table maps each vertex back to its node."""
    prims = []
    binds = []
    slots: dict[int, int] = {}
    p = 0
    n = len(dl)
    vsize = nfields * 2 + (1 if skinned else 0)
    while p < n:
        op = dl[p]
        if op == 0:
            p += 1
            continue
        if op in (0x20, 0x28):
            if p + 5 > n:
                raise GcgError("truncated matrix load")
            index, addr = struct.unpack_from(">HH", dl, p + 1)
            if op == 0x20:
                slots[(addr & 0xFFF) // 12] = index
            p += 5
            continue
        if (op & 0xF8) not in PRIM_OPS or p + 3 > n:
            raise GcgError(f"bad display-list opcode {op:#x} at +{p:#x}")
        count = struct.unpack_from(">H", dl, p + 1)[0]
        need = count * vsize
        if p + 3 + need > n:
            raise GcgError("display list overruns its size")
        rows = np.frombuffer(dl, np.uint8, need, p + 3).reshape(count, vsize)
        if skinned:
            mtx = rows[:, 0].astype(np.int64) // 3
            bind = np.array([slots.get(int(s), -1) for s in mtx], np.int64)
            rows = rows[:, 1:]
        else:
            bind = np.full(count, -1, np.int64)
        idx = np.ascontiguousarray(rows).view(">u2").reshape(count, nfields).astype(np.uint16)
        prims.append((op & 0xF8, idx))
        binds.append(bind)
        p += 3 + need
    return prims, binds


def _submesh(data: bytes, q: int) -> tuple[Submesh, int]:
    n = len(data)
    if q + 15 > n:
        raise GcgError("truncated submesh header")
    material = struct.unpack_from(">I", data, q)[0]
    flags, mask = data[q + 4], data[q + 5]
    radius, nverts = struct.unpack_from(">fH", data, q + 9)
    q += 15
    pos_comp, pos_frac, uv_comp, uv_frac = 4, 0, 3, 0
    if flags & 0x80:
        if q + 14 > n:
            raise GcgError("truncated vertex format")
        pos_comp = struct.unpack_from(">I", data, q)[0]
        pos_frac = data[q + 4]
        uv_comp, uv_frac = data[q + 12], data[q + 13]
        q += 14
    if nverts == 0:
        raise GcgError("submesh without vertices")
    size = data[q]
    q += 1
    if q + nverts * size > n:
        raise GcgError("positions overrun the file")
    positions = _positions(data, q, nverts, size, pos_comp, pos_frac)
    q += nverts * size
    fields = 1
    normals = colors = uvs = None
    for bit in (2, 4, 8):
        if not mask & bit:
            continue
        size = data[q]
        q += 1
        if q + nverts * size > n:
            raise GcgError("vertex attribute overruns the file")
        if bit == 2:
            normals = _normals(data, q, nverts, size)
        elif bit == 4:
            colors = _colors(data, q, nverts, size)
        else:
            uvs = _uvs(data, q, nverts, size, uv_comp, uv_frac)
        q += nverts * size
        fields += 1
    if q + 4 > n:
        raise GcgError("truncated display-list header")
    # u32 nbatch, nbatch x u32 (draw counts), u32 dl_size - one display list
    nbatch = struct.unpack_from(">I", data, q)[0]
    q += 4
    if not 1 <= nbatch <= 64 or q + nbatch * 4 + 4 > n:
        raise GcgError(f"display list batch count {nbatch} not plausible")
    q += nbatch * 4
    dl_size = struct.unpack_from(">I", data, q)[0]
    q += 4
    if q + dl_size > n:
        raise GcgError(f"display list size {dl_size} overruns the file")
    skinned = bool(mask & 0x40)
    prims, binds = _display_list(data[q : q + dl_size], fields, skinned)
    q += dl_size
    for _, idx in prims:
        if len(idx) and int(idx.max()) >= nverts:
            raise GcgError("display-list index past the vertex count")
    return Submesh(material, positions, normals, colors, uvs, prims, binds, float(radius)), q


def parse(data: bytes) -> Model:
    if not is_gcg(data[:12]):
        raise GcgError("not a gcg file")
    version, nnodes = struct.unpack_from(">II", data, 4)
    if nnodes > 4096 or 12 + nnodes * NODE_SIZE > len(data):
        raise GcgError(f"{nnodes} nodes do not fit")
    nodes: list[Node] = []
    p = 12
    for _ in range(nnodes):
        name = _cstr(data[p : p + 64])
        matrix = np.frombuffer(data, ">f4", 16, p + 0x80).reshape(4, 4).astype(np.float32)
        bb = struct.unpack_from(">7f", data, p + 0xC0)
        parent = struct.unpack_from(">i", data, p + 0xDC)[0]
        nodes.append(Node(name, matrix, bb[0:3], bb[3:6], bb[6], parent))
        p += NODE_SIZE
    model = Model(version, nodes)
    if p + 4 > len(data):
        raise GcgError("truncated material table")
    nmat = struct.unpack_from(">I", data, p)[0]
    p += 4
    if nmat > 1024 or p + nmat * 64 + 12 > len(data):
        raise GcgError(f"{nmat} materials do not fit")
    model.materials = [_cstr(data[p + i * 64 : p + (i + 1) * 64]) for i in range(nmat)]
    p += nmat * 64
    _one, _lod, nsub = struct.unpack_from(">IfI", data, p)
    p += 12
    if nsub > 65536:
        raise GcgError(f"{nsub} submeshes not plausible")
    for _ in range(nsub):
        sub, p = _submesh(data, p)
        model.submeshes.append(sub)
    if nnodes > 1 and p + 12 <= len(data):
        # multi-node trailer: u32 1, u32 count, u8 node order[count] (4-aligned), u32 nnodes
        _one, count = struct.unpack_from(">II", data, p)
        padded = (count + 3) & ~3
        if p + 8 + padded + 4 <= len(data):
            model.order = list(data[p + 8 : p + 8 + count])
            p += 8 + padded + 4
    model.end = p
    return model


# -- geometry helpers ------------------------------------------------------------------


def triangulate(prims: list[tuple[int, np.ndarray]], column: int = 0) -> np.ndarray:
    """Triangle (M,3) index array from the display list, using index column *column*."""
    tris = []
    for op, idx in prims:
        v = idx[:, column].astype(np.uint32)
        n = len(v)
        if op == 0x90:
            tris.append(v[: n - n % 3].reshape(-1, 3))
        elif op == 0x98:
            if n >= 3:
                a, b, c = v[:-2], v[1:-1], v[2:]
                t = np.stack([a, b, c], axis=1)
                odd = np.arange(n - 2) % 2 == 1
                t[odd] = t[odd][:, [1, 0, 2]]
                tris.append(t)
        elif op == 0xA0:
            if n >= 3:
                tris.append(np.stack([np.full(n - 2, v[0]), v[1:-1], v[2:]], axis=1))
        elif op == 0x80:
            qd = v[: n - n % 4].reshape(-1, 4)
            tris.append(qd[:, [0, 1, 2]])
            tris.append(qd[:, [0, 2, 3]])
    if not tris:
        return np.zeros((0, 3), np.uint32)
    t = np.concatenate(tris).astype(np.uint32)
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    return t[keep]


def world_matrices(nodes: list[Node]) -> list[np.ndarray]:
    """Node -> world 4x4 (row-vector convention: world = local @ parent_world)."""
    out: list[np.ndarray | None] = [None] * len(nodes)

    def get(i: int) -> np.ndarray:
        m = out[i]
        if m is None:
            node = nodes[i]
            m = node.matrix.astype(np.float64)
            if 0 <= node.parent < len(nodes) and node.parent != i:
                m = m @ get(node.parent)
            out[i] = m
        return m

    return [get(i) for i in range(len(nodes))]


# -- textures / materials --------------------------------------------------------------


@dataclass
class Texture:
    width: int
    height: int
    paletted: bool
    rgba: np.ndarray  # (h, w, 4) u8, base level


def is_gct(head: bytes, size: int | None = None) -> bool:
    if len(head) < 36:
        return False
    one, pal, nmips, ncolors, w, h = struct.unpack_from(">6I", head, 0)
    if one != 1 or pal not in (0, 1) or not (1 <= nmips <= 16):
        return False
    if not (0 < w <= 4096 and 0 < h <= 4096):
        return False
    if pal and not (0 < ncolors <= 256):
        return False
    return pal or ncolors == 0


def decode_gct(data: bytes) -> Texture:
    if not is_gct(data[:36]):
        raise GcgError("not a gct texture")
    _one, pal, _nmips, ncolors, w, h = struct.unpack_from(">6I", data, 0)
    p = 24
    palette = None
    if pal:
        palette = gx_texture.decode_palette(2, data[p : p + ncolors * 2], ncolors)
        p += ncolors * 2
    # mip levels run smallest first (1x1, 2x2, ... w x h); the base level is the last
    fmt = 9 if pal else 14
    for _ in range(32):
        if p + 12 > len(data):
            raise GcgError("no mip level matches the header size")
        lw, lh, size = struct.unpack_from(">3I", data, p)
        p += 12
        if lw == w and lh == h:
            break
        if not (0 < lw <= w and 0 < lh <= h and size <= len(data) - p):
            raise GcgError("mip level chain not plausible")
        p += size
    else:
        raise GcgError("no mip level matches the header size")
    body = data[p : p + size]
    if len(body) < gx_texture.encoded_size(fmt, w, h):
        raise GcgError("texture data truncated")
    rgba = gx_texture.decode(fmt, w, h, body, palette)
    return Texture(w, h, bool(pal), rgba)


def material_texture(gcm_text: str) -> str | None:
    """The texture stem named by a ``.gcm`` INI material (``TextureMap_1 = name``)."""
    for line in gcm_text.splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower().startswith("texturemap_1"):
            value = value.strip()
            return value or None
    return None
