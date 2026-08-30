"""Traveller's Tales NU2 ``.hgo`` characters and ``.nus`` levels on GameCube (Crash Bandicoot:
The Wrath of Cortex, Finding Nemo): the NU2 chunk tree with REVERSED 4CC tags and big-endian
sizes (``FOGH`` = HGOF, ``0CSG`` = GSC0, ``LBTN`` = NTBL, ``0TST`` = TST0, ``0MXT`` = TXM0,
``00SM`` = MS00 / ``30SM`` = MS03, ``0OGH`` = HGO0, ``0TSG`` = GST0, ``TSNI`` = INST).

NTBL: ``u32 bytes | C strings`` (node / mesh names in order).  TST0 > TSH0 (``u32 count``) +
TXM0 per texture: ``u32 code | u32 w | u32 h | u32 bytes | GX pixels`` (0x80 = CMPR, 0x81 =
RGB5A3; otherwise by bytes per pixel).  MS00: ``u32 count`` + 84-byte materials: ``s32 | u32
flags | u32 x3 | f32 rgb | u32 x4 | f32 x2 | s32 texture | ...``.
Meshes (inside HGO0 after the variable node records, or inside GST0 after ``u32 count``):
``u32 1 | u32 x4 | u32 blocks | u32 material | u32 vertex count | vertices | index groups |
skin`` and further blocks of the same mesh as ``u32 0 | u32 0 | u32 material | count ...``.
Vertices are ``f32 xyz | [f32 normal] | RGBA8 | [f32 uv]`` (16 / 24 / 28 / 36 bytes,
big-endian; the Nemo levels drop the normals), index
groups ``u32 | u32 | u32 prim (5 list / 6 strip) | u32 count | u16 indices`` 4-aligned (the
Finding Nemo levels use a raw GX display list instead), and a
skinned mesh ends with ``u16 0x0101`` + per-vertex ``f32 w0 w1 w2 | u8 bone[4]``.  Vertices are
in model space (bind pose); meshes are located by scanning for plausible vertex blocks so the
node records need not be walked.  INST: ``u32 count`` + 80-byte records ``f32 4x4 (row vector
convention, translation in row 3) | u32 x4`` = one placement per GST0 mesh in order.
"""

from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

MAGIC_HGO = b"FOGH"
MAGIC_GSC = b"0CSG"
_CP_POS_BASE = bytes((0x08, 0xA0))  # CP load of the position array base


@dataclass
class Texture:
    name: str
    width: int
    height: int
    code: int
    rgba: np.ndarray | None


@dataclass
class Material:
    texture: int
    color: tuple[float, float, float]
    flags: int


@dataclass
class Mesh:
    material: int
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray
    indices: np.ndarray
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None
    group: int = 0  # mesh number (a mesh = one or more vertex blocks)


@dataclass
class Model:
    kind: str = ""
    names: list[str] = field(default_factory=list)
    node_count: int = 0
    textures: list[Texture] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    meshes: list[Mesh] = field(default_factory=list)
    instances: list[np.ndarray] = field(default_factory=list)


def is_hgo(head: bytes) -> bool:
    return head[:4] in (MAGIC_HGO, MAGIC_GSC) and len(head) >= 12 and head[8:12] == b"LBTN"


def chunks(d: bytes, p: int, end: int) -> list[tuple[bytes, int, int]]:
    """(tag, body start, chunk end) for the chunk run ``p:end``."""
    out = []
    while p + 8 <= end:
        tag = d[p : p + 4][::-1]
        size = struct.unpack_from(">I", d, p + 4)[0]
        if size < 8 or p + size > end + 8:
            break
        out.append((tag, p + 8, min(p + size, end)))
        p += size
    return out


def _names(d: bytes, s: int, e: int) -> list[str]:
    n = struct.unpack_from(">I", d, s)[0]
    raw = d[s + 4 : min(s + 4 + n, e)]
    return [x.decode("latin-1", "replace") for x in raw.split(b"\0") if x]


def _textures(d: bytes, s: int, e: int) -> list[Texture]:
    out = []
    for tag, ts, te in chunks(d, s, e):
        if tag != b"TXM0" or te - ts < 16:
            continue
        code, w, h, size = struct.unpack_from(">4I", d, ts)
        tex = Texture(f"tex{len(out):03d}", w, h, code, None)
        out.append(tex)
        if not (0 < w <= 2048 and 0 < h <= 2048) or size <= 0 or ts + 16 + size > te + 8:
            continue
        pix = d[ts + 16 : ts + 16 + size]
        bpp = size / (w * h)
        if code == 0x80 or bpp <= 0.5:
            fmt = 14
        elif code == 0x81 or bpp <= 2:
            fmt = 5
        else:
            fmt = 6
        with contextlib.suppress(ValueError):
            tex.rgba = gx_texture.decode(fmt, w, h, pix)
    return out


def _materials(d: bytes, s: int, e: int) -> list[Material]:
    n = struct.unpack_from(">I", d, s)[0]
    out = []
    p = s + 4
    for _ in range(min(n, 4096)):
        if p + 84 > e:
            break
        flags = struct.unpack_from(">I", d, p + 4)[0]
        rgb = struct.unpack_from(">3f", d, p + 20)
        tex = struct.unpack_from(">i", d, p + 56)[0]
        out.append(Material(tex, tuple(float(min(max(c, 0.0), 1.0)) for c in rgb), flags))
        p += 84
    return out


def _instances(d: bytes, s: int, e: int) -> list[np.ndarray]:
    n = struct.unpack_from(">I", d, s)[0]
    out = []
    p = s + 4
    for _ in range(min(n, 100000)):
        if p + 80 > e:
            break
        m = np.frombuffer(d, ">f4", 16, p).reshape(4, 4).astype(np.float64)
        out.append(m if np.isfinite(m).all() else np.eye(4))
        p += 80
    return out


# (stride, normals, uvs): position f32[3] | [normal f32[3]] | RGBA8 | [uv f32[2]]
LAYOUTS = ((36, True, True), (28, True, False), (24, False, True), (16, False, False))


def _fields(rec: np.ndarray, layout) -> tuple:
    """(positions, normals or None, colours, uvs or None) of raw vertex records."""
    _stride_, has_nrm, has_uv = layout
    n = len(rec)
    pos = rec[:, :12].copy().view(">f4").reshape(n, 3)
    p = 12
    nrm = None
    if has_nrm:
        nrm = rec[:, p : p + 12].copy().view(">f4").reshape(n, 3)
        p += 12
    colors = rec[:, p : p + 4]
    p += 4
    uv = rec[:, p : p + 8].copy().view(">f4").reshape(n, 2) if has_uv else None
    return pos, nrm, colors, uv


def _layout(b: bytes, off: int, n: int):
    """Vertex layout of a plausible block at ``off`` (``u32 count`` there) or None.  Layouts
    without normals need a valid index group behind the vertices to be believed."""
    for layout in LAYOUTS:
        stride = layout[0]
        if off + 4 + n * stride > len(b):
            continue
        rec = np.frombuffer(b, np.uint8, n * stride, off + 4).reshape(n, stride)
        pos, nrm, _colors, uv = _fields(rec, layout)
        if not np.isfinite(pos).all() or (np.abs(pos) >= 10000).any():
            continue
        if nrm is not None:
            if not np.isfinite(nrm).all():
                continue
            ln = np.linalg.norm(nrm, axis=1)
            if np.abs(ln - 1.0).max() >= 0.05:
                continue
        if uv is not None and (not np.isfinite(uv).all() or (np.abs(uv) >= 512).any()):
            continue
        if nrm is None and not _believable(b, off + 4 + n * stride, n):
            continue
        return layout
    return None


def _believable(b: bytes, q: int, n: int) -> bool:
    """A normal-less vertex block needs indices behind it: an index group or a GX list."""
    if _has_group(b, q, n):
        return True
    tris, _end = _gx_lists(b, q, n)
    return bool(tris)


def _has_group(b: bytes, q: int, n: int) -> bool:
    if q + 16 > len(b):
        return False
    a, bb, prim, ic = struct.unpack_from(">4I", b, q)
    return (
        a < 16 and bb < 64 and prim in (4, 5, 6) and 3 <= ic <= 200000 and q + 16 + ic * 2 <= len(b)
    )


def _gx_lists(b: bytes, start: int, nverts: int) -> tuple[list, int]:
    """GX FIFO after a vertex block (Finding Nemo levels): a ``u32 size | u8`` prelude, then CP
    array-base / stride loads (``08 a0+i <u32 base>`` / ``08 b0+i <u32 stride>``) name the
    indexed attributes, then primitives (``0x98`` strip, ``0x90`` list, ``0xa0`` fan) carry one
    index per attribute in GX order - u8 while the array fits in a byte, u16 above that.
    Returns (triangle arrays over the position column, end offset)."""
    n = len(b)
    head = b.find(_CP_POS_BASE, start, min(start + 256, n))
    if head < 0:
        return [], start
    best: tuple[list, int] = ([], start)
    best_score = (0, 0)
    for width in (1, 2):
        tris, end = _gx_walk(b, head, nverts, width)
        score = (sum(len(t) for t in tris), end - head)
        if score > best_score:
            best, best_score = (tris, end), score
    return best


def _gx_walk(b: bytes, head: int, nverts: int, width: int) -> tuple[list, int]:
    n = len(b)
    cols = 0
    tris = []
    i = head
    while i < n:
        op = b[i]
        if op == 0:
            i += 1
        elif op == 0x08 and i + 6 <= n:
            if 0xA0 <= b[i + 1] <= 0xA7:
                cols += 1
            i += 6
        elif op == 0x10 and i + 5 <= n:
            i += 5 + 4 * (struct.unpack_from(">H", b, i + 1)[0] + 1)
        elif op in (0x61, 0x20, 0x28, 0x30, 0x38) and i + 5 <= n:
            i += 5
        elif op & 0xF8 in (0x80, 0x90, 0x98, 0xA0) and cols and i + 3 <= n:
            count = struct.unpack_from(">H", b, i + 1)[0]
            i += 3
            row = cols * width
            if count == 0 or i + count * row > n:
                break
            if width == 1:
                idx = np.frombuffer(b, np.uint8, count * cols, i).reshape(count, cols)[:, 0]
            else:
                idx = np.frombuffer(b, ">u2", count * cols, i).reshape(count, cols)[:, 0]
            idx = idx.astype(np.uint32)
            i += count * row
            if int(idx.max()) >= nverts:
                continue  # a strip of a later block in the same mesh
            prim = op & 0xF8
            if prim == 0x98:
                t = [
                    (idx[k], idx[k + 1], idx[k + 2])
                    if k % 2 == 0
                    else (idx[k], idx[k + 2], idx[k + 1])
                    for k in range(count - 2)
                ]
            elif prim == 0x90:
                t = list(idx[: count // 3 * 3].reshape(-1, 3))
            elif prim == 0xA0:
                t = [(idx[0], idx[k], idx[k + 1]) for k in range(1, count - 1)]
            else:
                t = []
            if t:
                tris.append(np.array(t, np.uint32).reshape(-1, 3))
        else:
            break
    return tris, i


def _mesh(b: bytes, off: int, n: int, layout, nmat: int) -> tuple[Mesh | None, int]:
    stride = layout[0]
    rec = np.frombuffer(b, np.uint8, n * stride, off + 4).reshape(n, stride)
    pos, nrm, colors, uv = _fields(rec, layout)
    q = off + 4 + n * stride
    tris = []
    while q + 16 <= len(b):
        a, bb, prim, ic = struct.unpack_from(">4I", b, q)
        if not (a < 16 and bb < 64 and prim in (4, 5, 6) and 1 <= ic <= 200000):
            break
        if q + 16 + ic * 2 > len(b):
            break
        idx = np.frombuffer(b, ">u2", ic, q + 16).astype(np.uint32)
        if prim == 5:
            tris.append(idx[: len(idx) // 3 * 3].reshape(-1, 3))
        else:
            t = [
                (idx[k], idx[k + 1], idx[k + 2]) if k % 2 == 0 else (idx[k], idx[k + 2], idx[k + 1])
                for k in range(len(idx) - 2)
            ]
            if t:
                tris.append(np.array(t, np.uint32))
        q += 16 + ic * 2
        q += (-q) % 4
    if not tris:
        gx, q2 = _gx_lists(b, q, n)
        if gx:
            tris = gx
            q = q2
    mat = struct.unpack_from(">I", b, off - 4)[0] if off >= 4 else 0
    mesh = None
    if tris:
        tri = np.concatenate(tris)
        tri = tri[(tri < n).all(axis=1)]
        tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
        if len(tri):
            mesh = Mesh(
                mat if mat < nmat else 0,
                pos.astype(np.float32),
                nrm.astype(np.float32) if nrm is not None else None,
                uv.astype(np.float32) if uv is not None else None,
                colors.copy(),
                tri.reshape(-1),
            )
    # skin: u16 0x0101 (after 4-alignment) then n x (f32 w0 w1 w2 | u8 bone[4])
    for pad in (0, 2):
        r = q + pad
        if r + 2 + 16 * n <= len(b) and b[r : r + 2] == b"":
            srec = np.frombuffer(b, np.uint8, 16 * n, r + 2).reshape(n, 16)
            w = srec[:, :12].copy().view(">f4").reshape(n, 3).astype(np.float32)
            if np.isfinite(w).all() and (w >= -0.01).all() and (w <= 1.01).all():
                w4 = np.clip(1.0 - w.sum(axis=1, keepdims=True), 0.0, 1.0)
                weights = np.concatenate([w, w4], axis=1)
                weights[weights < 0] = 0
                if mesh is not None:
                    mesh.joints = srec[:, 12:16].astype(np.uint16)
                    mesh.weights = weights
                q = r + 2 + 16 * n
            break
    return mesh, q


def scan_meshes(b: bytes, start: int, nmat: int) -> list[Mesh]:
    """Vertex blocks in ``b`` from ``start``; a block whose header word (``u32`` before the
    material) is non-zero starts a new mesh of that many blocks, continuation blocks carry 0."""
    out = []
    p = start
    group = -1
    while p + 40 < len(b):
        n = struct.unpack_from(">I", b, p)[0]
        layout = _layout(b, p, n) if 3 <= n <= 65535 else None
        if layout is not None:
            blocks = struct.unpack_from(">I", b, p - 8)[0] if p >= 8 else 0
            if blocks or group < 0:
                group += 1
            mesh, q = _mesh(b, p, n, layout, max(nmat, 1))
            if mesh is not None:
                mesh.group = group
                out.append(mesh)
            p = max(q, p + 4 + n * layout[0])
        else:
            p += 1
    return out


def parse(d: bytes) -> Model:
    model = Model()
    top = chunks(d, 0, len(d))
    if not top or top[0][0] not in (b"HGOF", b"GSC0"):
        return model
    model.kind = "hgo" if top[0][0] == b"HGOF" else "gsc"
    for tag, s, e in chunks(d, top[0][1], top[0][2]):
        if tag == b"NTBL":
            model.names = _names(d, s, e)
        elif tag == b"TST0":
            model.textures = _textures(d, s, e)
        elif tag[:2] == b"MS" and tag[2:].isdigit():  # MS00 (Crash), MS03 (Nemo)
            model.materials = _materials(d, s, e)
        elif tag == b"HGO0":
            b = d[s:e]
            model.node_count = b[0] if b else 0
            model.meshes = scan_meshes(b, 2, len(model.materials))
        elif tag == b"GST0":
            model.meshes = scan_meshes(d[s:e], 4, len(model.materials))
        elif tag == b"INST":
            model.instances = _instances(d, s, e)
    return model
