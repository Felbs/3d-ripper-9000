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
Vertices are ``f32 xyz | f32 normal | RGBA8 | [f32 uv]`` (28 or 36 bytes, big-endian), index
groups ``u32 | u32 | u32 prim (5 list / 6 strip) | u32 count | u16 indices`` 4-aligned, and a
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
    normals: np.ndarray
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


STRIDES = (36, 28)


def _fields(rec: np.ndarray, stride: int) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """(pos+normal f32 (n, 6), RGBA (n, 4), uv f32 (n, 2) or None) of raw vertex records."""
    f = rec[:, :24].copy().view(">f4").reshape(len(rec), 6)
    colors = rec[:, 24:28]
    uv = rec[:, 28:36].copy().view(">f4").reshape(len(rec), 2) if stride == 36 else None
    return f, colors, uv


def _stride(b: bytes, off: int, n: int) -> int:
    """Vertex stride of a plausible block at ``off`` (``u32 count`` there) or 0."""
    for stride in STRIDES:
        if off + 4 + n * stride > len(b):
            continue
        rec = np.frombuffer(b, np.uint8, n * stride, off + 4).reshape(n, stride)
        f, _colors, uv = _fields(rec, stride)
        if not np.isfinite(f).all() or (np.abs(f[:, :3]) >= 10000).any():
            continue
        ln = np.linalg.norm(f[:, 3:6], axis=1)
        if np.abs(ln - 1.0).max() >= 0.05:
            continue
        if uv is not None and (not np.isfinite(uv).all() or (np.abs(uv) >= 512).any()):
            continue
        return stride
    return 0


def _mesh(b: bytes, off: int, n: int, stride: int, nmat: int) -> tuple[Mesh | None, int]:
    rec = np.frombuffer(b, np.uint8, n * stride, off + 4).reshape(n, stride)
    f, colors, uv = _fields(rec, stride)
    f = f.astype(np.float32)
    colors = colors.copy()
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
    mat = struct.unpack_from(">I", b, off - 4)[0] if off >= 4 else 0
    mesh = None
    if tris:
        tri = np.concatenate(tris)
        tri = tri[(tri < n).all(axis=1)]
        tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
        if len(tri):
            mesh = Mesh(
                mat if mat < nmat else 0,
                f[:, :3].copy(),
                f[:, 3:6].copy(),
                uv.astype(np.float32) if uv is not None else None,
                colors,
                tri.reshape(-1),
            )
    # skin: u16 0x0101 (after 4-alignment) then n x (f32 w0 w1 w2 | u8 bone[4])
    for pad in (0, 2):
        r = q + pad
        if r + 2 + 16 * n <= len(b) and b[r : r + 2] == b"\x01\x01":
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
        stride = _stride(b, p, n) if 3 <= n <= 65535 else 0
        if stride:
            blocks = struct.unpack_from(">I", b, p - 8)[0] if p >= 8 else 0
            if blocks or group < 0:
                group += 1
            mesh, q = _mesh(b, p, n, stride, max(nmat, 1))
            if mesh is not None:
                mesh.group = group
                out.append(mesh)
            p = max(q, p + 4 + n * stride)
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
