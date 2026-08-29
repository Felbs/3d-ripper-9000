"""Radical Entertainment Pure3D (``.p3d``) files as shipped on GameCube (Simpsons Hit &
Run, Simpsons Road Rage, Hulk, The Incredible Hulk, Crash Tag Team Racing, Dark Summit,
Monsters Inc, ...): little-endian chunk trees (``P3D\\xff``, 12-byte header, chunks of
``u32 id | u32 header size | u32 total size``), optionally wrapped in ``P3DZ`` (LZR).

The GameCube prim groups keep their geometry as GX memory images: ``0x10014`` lists the
vertex attributes (``attr, ?, ?, ?, frac bits, stride, u16 BE count, u32 BE end``) inside the
``0x10012`` vertex buffer (big-endian, fixed point) and ``0x10013`` is the display list
(strips of u8/u16 indices in GX order, a matrix index first for skins).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import lzr

MAGIC = b"P3D\xff"
MAGIC_BE = b"\xffD3P"

MESH, SKIN, PRIMGROUP, PRIMGROUP2 = 0x10000, 0x10001, 0x10002, 0x10020
BBOX, BSPHERE = 0x10003, 0x10004
POSITION_LIST, NORMAL_LIST, UV_LIST, COLOUR_LIST = 0x10005, 0x10006, 0x10007, 0x10008
INDEX_LIST, MATRIX_LIST, WEIGHT_LIST, MATRIX_PALETTE = 0x1000A, 0x1000B, 0x1000C, 0x1000D
GX_VERTEX, GX_INDEX, GX_DESC = 0x10012, 0x10013, 0x10014
SKELETON, SKELETON_JOINT = 0x4500, 0x4501
SHADER, SHADER_TEX_PARAM = 0x11000, 0x11002
TEXTURE, IMAGE, IMAGE_DATA = 0x19000, 0x19001, 0x19002
COMPOSITE_DRAWABLE = 0x4512

PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}
GX_POS, GX_NRM, GX_CLR0, GX_TEX0, GX_MTX = 9, 10, 11, 13, 0xFF


class P3dError(ValueError):
    pass


@dataclass
class Chunk:
    id: int
    start: int  # file offset of the chunk
    body: bytes  # header payload (without the 12-byte chunk header)
    children: list[Chunk] = field(default_factory=list)
    e: str = "<"  # struct endian prefix of the file ("<" or ">")

    def u32(self, off: int) -> int:
        return struct.unpack_from(self.e + "I", self.body, off)[0]


def is_p3d(head: bytes) -> bool:
    return head[:4] in (MAGIC, MAGIC_BE) or lzr.is_p3dz(head)


def _str(b: bytes, o: int) -> tuple[str, int]:
    n = b[o]
    return b[o + 1 : o + 1 + n].split(b"\0")[0].decode("latin-1"), o + 1 + n


def parse(data: bytes) -> list[Chunk]:
    """Top-level chunks (children parsed recursively)."""
    if lzr.is_p3dz(data):
        data = lzr.decompress_p3dz(data)
    if data[:4] == MAGIC:
        e = "<"
    elif data[:4] == MAGIC_BE:
        e = ">"
    else:
        raise P3dError("not a Pure3D file")
    return _walk(data, 12, len(data), 0, e)


def _walk(d: bytes, o: int, end: int, depth: int, e: str) -> list[Chunk]:
    out = []
    while o + 12 <= end:
        cid, hs, cs = struct.unpack_from(e + "III", d, o)
        if cs < 12 or hs < 12 or hs > cs or o + cs > end + 4:
            break
        ch = Chunk(cid, o, d[o + 12 : o + hs], e=e)
        if hs < cs and depth < 16:
            ch.children = _walk(d, o + hs, min(o + cs, end), depth + 1, e)
        out.append(ch)
        o += cs
    return out


def iter_chunks(chunks: list[Chunk], cid: int):
    for c in chunks:
        if c.id == cid:
            yield c
        yield from iter_chunks(c.children, cid)


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------


@dataclass
class PrimGroup:
    shader: str
    positions: np.ndarray  # (N,3) f32
    indices: np.ndarray  # (M,) u32 triangles
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    colors: np.ndarray | None = None
    joints: np.ndarray | None = None  # (N,4) u16 skeleton joint indices
    weights: np.ndarray | None = None


@dataclass
class Mesh:
    name: str
    groups: list[PrimGroup]
    skeleton: str | None = None  # Skin chunks name their skeleton


def _triangulate(prims, idx: np.ndarray) -> np.ndarray:
    from gcrip.formats.eagl import _triangulate as tri

    return tri(prims, idx)


def _descriptors(body: bytes) -> list[tuple[int, int, int, int, int]]:  # noqa: D417
    """(attr, frac, stride, count, end) records of a 0x10014 chunk; the last record may be
    truncated to 8 bytes (its end is the buffer end)."""
    out = []
    o = 16
    while o + 8 <= len(body):
        attr, _a, _b, _c, frac, stride = body[o : o + 6]
        count = struct.unpack_from(">H", body, o + 6)[0]
        end = struct.unpack_from(">I", body, o + 8)[0] if o + 12 <= len(body) else -1
        out.append((attr, frac, stride, count, end))
        o += 12
    return out


def _gx_group(pg: Chunk, shader: str) -> PrimGroup | None:
    desc = next((c for c in pg.children if c.id == GX_DESC), None)
    vert = next((c for c in pg.children if c.id == GX_VERTEX), None)
    dl = next((c for c in pg.children if c.id == GX_INDEX), None)
    if desc is None or vert is None or dl is None:
        return None
    recs = _descriptors(desc.body)
    vb = vert.body[12:]
    ib = dl.body[12:]
    # attribute arrays: consecutive in the vertex buffer, in record order
    arrays: dict[int, np.ndarray] = {}
    start = 0
    widths: list[tuple[int, int]] = []  # (attr, index width) in GX order
    for attr, frac, stride, count, end in recs:
        n = count
        if stride <= 0 and n > 0 and end > start:
            stride = (end - start) // n
        if end < 0:
            end = start + n * stride
        # every attribute the descriptor lists has an index column in the display list,
        # even when its array is empty (normals the shader does not need)
        widths.append((attr, 1 if (attr == GX_MTX or n <= 256) else 2))
        if n <= 0 or stride <= 0 or start + n * stride > len(vb):
            start = max(start, end)
            continue
        raw = vb[start : start + n * stride]
        scale = 1.0 / (1 << frac) if frac < 32 else 1.0
        if attr == GX_MTX:
            arrays[attr] = np.frombuffer(raw, np.uint8).reshape(n, stride)
        elif stride == 12:
            arrays[attr] = np.frombuffer(raw, ">f4").reshape(n, 3).astype(np.float32)
        elif stride == 6:
            arrays[attr] = np.frombuffer(raw, ">i2").reshape(n, 3).astype(np.float32) * scale
        elif stride == 3:
            arrays[attr] = np.frombuffer(raw, np.int8).reshape(n, 3).astype(np.float32) * scale
        elif stride == 8 and attr == GX_TEX0:
            arrays[attr] = np.frombuffer(raw, ">f4").reshape(n, 2).astype(np.float32)
        elif stride == 4 and attr == GX_TEX0:
            arrays[attr] = np.frombuffer(raw, ">i2").reshape(n, 2).astype(np.float32) * scale
        elif stride == 2 and attr == GX_TEX0:
            arrays[attr] = np.frombuffer(raw, np.int8).reshape(n, 2).astype(np.float32) * scale
        elif stride == 4 and attr == GX_CLR0:
            arrays[attr] = np.frombuffer(raw, np.uint8).reshape(n, 4).astype(np.float32) / 255.0
        else:
            arrays[attr] = np.frombuffer(raw, np.uint8).reshape(n, stride)
        start = end
    if GX_POS not in arrays:
        return None
    # the display list: every stride that chains through the buffer is tried with every
    # column layout (0 / 1 / 2 bytes per attribute, GX order); index ranges and triangle
    # compactness pick the winner (zero padding lets wrong strides chain too)
    order = {GX_MTX: 0, GX_POS: 1, GX_NRM: 2, GX_CLR0: 3, GX_TEX0: 4}
    attrs = sorted({a for a, _ in widths}, key=lambda a: order.get(a, 9))
    counts = {a: (len(arrays[a]) if a in arrays else 0) for a in attrs}
    best = None
    for stride in range(1, 12):
        prims = _chain(ib, stride)
        if not prims:
            continue
        rows = np.concatenate(
            [np.frombuffer(ib, np.uint8, cnt * stride, o).reshape(cnt, stride)
             for _, cnt, o in prims]
        )
        found = _best_layout(rows, stride, attrs, counts, arrays[GX_POS], prims)
        if found is not None and (best is None or found[0] < best[0]):
            best = (found[0], found[1], prims)
    if best is None:
        return None
    _score, cols, prims = best
    pos = arrays[GX_POS]
    pidx = cols[GX_POS]
    if pidx.max() >= len(pos):
        return None
    tri = _triangulate(prims, pidx)
    if len(tri) < 3:
        return None
    nv = len(pos)

    def per_vertex(attr: int, width: int) -> np.ndarray | None:
        arr = arrays.get(attr)
        idx = cols.get(attr)
        if arr is None or idx is None or idx.max() >= len(arr) or arr.shape[1] < width:
            return None
        out = np.zeros((nv, width), np.float32)
        out[pidx] = arr[idx][:, :width]
        return out

    group = PrimGroup(
        shader, pos, tri, per_vertex(GX_NRM, 3), per_vertex(GX_TEX0, 2), per_vertex(GX_CLR0, 4)
    )
    mtx = arrays.get(GX_MTX)
    if mtx is not None and mtx.shape[1] >= 8:
        midx = cols.get(GX_MTX)
        if midx is not None and midx.max() < len(mtx):
            rows_m = mtx[midx]
            joints = np.zeros((nv, 4), np.uint16)
            weights = np.zeros((nv, 4), np.float32)
            joints[pidx] = rows_m[:, :4]
            w = rows_m[:, 4:8].astype(np.float32)
            tot = w.sum(1, keepdims=True)
            tot[tot == 0] = 1.0
            weights[pidx] = w / tot
            palette = next((c for c in pg.children if c.id == MATRIX_PALETTE), None)
            if palette is not None:
                n = palette.u32(0)
                pal = np.frombuffer(palette.body, palette.e + "u4", n, 4)
                safe = pal[np.minimum(joints, len(pal) - 1)]
                joints = np.where(joints < len(pal), safe, 0).astype(np.uint16)
            group.joints, group.weights = joints, weights
    return group


def _chain(ib: bytes, stride: int):
    prims = []
    p = 0
    while p + 3 <= len(ib):
        op = ib[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        cnt = (ib[p + 1] << 8) | ib[p + 2]
        if cnt == 0 or p + 3 + cnt * stride > len(ib):
            break
        prims.append((op & 0xF8, cnt, p + 3))
        p += 3 + cnt * stride
    return prims


def _best_layout(rows, stride, attrs, counts, pos, prims):
    """Column (byte offset, width) per attribute: every assignment of 0/1/2-byte columns
    in GX order that fills the stride, scored by in-range indices and mesh compactness."""
    import itertools

    options = []
    for a in attrs:
        n = counts[a]
        if a == GX_MTX or n == 0:
            options.append([0, 1])
        elif n <= 256:
            options.append([1, 2])
        else:
            options.append([2])
    best = None
    for widths in itertools.product(*options):
        if sum(widths) != stride:
            continue
        cols = {}
        k = 0
        ok = True
        for a, w in zip(attrs, widths, strict=True):
            if w == 0:
                continue
            v = _column(rows, k, w)
            k += w
            n = counts[a]
            if a != GX_MTX and n and v.max() >= n:
                ok = False
                break
            cols[a] = v
        if not ok or GX_POS not in cols:
            continue
        pidx = cols[GX_POS]
        tri = _triangulate(prims, pidx).reshape(-1, 3)
        if len(tri) == 0:
            continue
        e = np.linalg.norm(pos[tri[:, 1]] - pos[tri[:, 0]], axis=1).mean()
        diag = np.linalg.norm(pos.max(0) - pos.min(0)) or 1.0
        score = e / diag - 0.001 * len(cols)
        if best is None or score < best[0]:
            best = (score, cols)
    return best


def _column(rows: np.ndarray, off: int, width: int) -> np.ndarray:
    if width == 2:
        return (rows[:, off].astype(np.uint32) << 8) | rows[:, off + 1]
    return rows[:, off].astype(np.uint32)


def _list_group(pg: Chunk, shader: str) -> PrimGroup | None:
    """PC-style prim group with explicit position / normal / uv / index lists."""
    by = {c.id: c for c in pg.children}
    if POSITION_LIST not in by or INDEX_LIST not in by:
        return None
    e = pg.e
    n = by[POSITION_LIST].u32(0)
    pos = np.frombuffer(by[POSITION_LIST].body, e + "f4", n * 3, 4).reshape(n, 3).astype(np.float32)
    m = by[INDEX_LIST].u32(0)
    idx = np.frombuffer(by[INDEX_LIST].body, e + "u4", m, 4)
    ptype = pg.u32(4 + 1 + pg.body[4]) if len(pg.body) > 5 else 0
    tri = _triangulate([(0x98 if ptype == 1 else 0x90, m, 0)], idx.astype(np.uint32))
    normals = uvs = None
    if NORMAL_LIST in by:
        nb = by[NORMAL_LIST].body
        normals = np.frombuffer(nb, e + "f4", n * 3, 4).reshape(n, 3).astype(np.float32)
    if UV_LIST in by:
        uvs = np.frombuffer(by[UV_LIST].body, e + "f4", n * 2, 8).reshape(n, 2).astype(np.float32)
    return PrimGroup(shader, pos, tri, normals, uvs)


def meshes(chunks: list[Chunk]) -> list[Mesh]:
    out = []
    for c in list(iter_chunks(chunks, MESH)) + list(iter_chunks(chunks, SKIN)):
        name, o = _str(c.body, 0)
        skel = None
        if c.id == SKIN:
            o += 4  # version
            skel, o = _str(c.body, o)
        groups = []
        for pg in c.children:
            if pg.id not in (PRIMGROUP, PRIMGROUP2):
                continue
            shader, _ = _str(pg.body, 4)
            g = _gx_group(pg, shader) or _list_group(pg, shader)
            if g is not None:
                groups.append(g)
        if groups:
            out.append(Mesh(name, groups, skel))
    return out


# ---------------------------------------------------------------------------
# skeletons, shaders, textures
# ---------------------------------------------------------------------------


@dataclass
class Joint:
    name: str
    parent: int | None
    rest: np.ndarray  # (4,4) f32, row-major with translation in row 3 (parent-relative)


def skeletons(chunks: list[Chunk]) -> dict[str, list[Joint]]:
    out = {}
    for c in iter_chunks(chunks, SKELETON):
        name, _ = _str(c.body, 0)
        joints = []
        for j in c.children:
            if j.id != SKELETON_JOINT:
                continue
            jname, o = _str(j.body, 0)
            parent = j.u32(o)
            rest = np.frombuffer(j.body, j.e + "f4", 16, o + 24).reshape(4, 4).astype(np.float32)
            idx = len(joints)
            joints.append(Joint(jname, parent if parent != idx and parent < 4096 else None, rest))
        out[name] = joints
    return out


def shader_textures(chunks: list[Chunk]) -> dict[str, str]:
    """shader name -> texture name (the TEX parameter)."""
    out = {}
    for c in iter_chunks(chunks, SHADER):
        name, _ = _str(c.body, 0)
        for p in c.children:
            if p.id == SHADER_TEX_PARAM and p.body[:3] == b"TEX":
                out[name], _ = _str(p.body, 4)
    return out


def textures(chunks: list[Chunk]) -> dict[str, np.ndarray]:
    """texture name -> RGBA (h,w,4) u8 (DDS DXT1/3/5 or PNG image data)."""
    from gcrip.formats import dds

    out: dict[str, np.ndarray] = {}
    for c in iter_chunks(chunks, TEXTURE):
        name, _ = _str(c.body, 0)
        img = next((i for i in c.children if i.id == IMAGE), None)
        if img is None:
            continue
        data = next((i for i in img.children if i.id == IMAGE_DATA), None)
        if data is None:
            continue
        n = data.u32(0)
        raw = data.body[4 : 4 + n]
        try:
            if raw[:4] == b"DDS ":
                out[name] = dds.decode(raw)
            elif raw[:8] == b"\x89PNG\r\n\x1a\n":
                import io

                from PIL import Image

                out[name] = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))
        except Exception:  # noqa: BLE001
            continue
    return out
