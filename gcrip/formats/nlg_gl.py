"""Next Level Games' GL layer on the GameCube - Super Mario Strikers ``.glg`` models and
``.glt`` texture bundles.

Read with ``MarioSoccerR.elf`` (DWARF 1, 740k entries) and its linker map:
``glxLoadModelFromDisk`` walks the chunks, ``dlMakeDisplayList`` turns a packet into a GX
display list (one u16 index a vertex, replicated for every stream), ``glx_SwitchStreams``
maps stream ids to GX attributes and sets the vertex formats, ``glplatLoadTextureBundle`` /
``glx_MakeTexture`` read the bundles.

``.glg`` - a chunk stream, big-endian ``u32 id, u32 size``, payload at +8 (an id with bits
24-30 set aligns its payload to ``1 << n``):

  0x8001b100  a level: several units
  0x8001b000  a unit (one model set), holding
    0x1b001   u16 major, u16 minor (2, 2)
    0x1b002   user data: 4x4 f32 matrices (row vectors), one a packet
    0x1b003   models: u32 packets, u32 id, u32 0, u32 packet-table offset
    0x1b004   packets, 70 or 74 bytes each (the size is the chunk length over the model
              table's packet count): u32 user data, u32 index-buffer offset, u16 vertices,
              u8 primitive, u8 streams, u32 stream-table offset, state[50 / 54]
              (+0x14 matrix offset into the user data, +0x18 texture hash), u32 material set
    0x1b005   streams, 6 bytes: u32 offset into the vertex data, u8 id, u8 stride
    0x1b006   vertex data (aligned)
    0x1b007   index data: u16 per vertex
    0x8001b008 skin data (nlChunk), 0x1b00f texture animation, 0x1b011 vertex animation,
    0x1b012   material list: u32 id, u32 count, count x (material id, packet index, packets)

Stream ids: 0 position (stride 12 F32, 6 S16 / 256), 1 normal (12 F32, 3 S8 / 64),
2 colour (RGBA8), 3..8 texcoords (stride 8 F32, 4 S16 / 1024), 0xc matrix index.
Primitive: 0 triangles, 1 strip, 2 fan, 3 quads, 4 lines, 5 line strip.

``.glt`` - ``PTLG``, u32 count, then count x (u32 hash, u32 offset, u32 bytes, u32 0) at
0x20; offsets count from the end of that table.  A texture is a 32-byte GXTextureHeader
(u32 levels, u32 format, u32, u8, u8, u16 width, u16 height, u32 palette entries) then the
tiles then an RGB5A3 palette; the format enum maps 0 RGB565, 1 RGB5A3, 2 CMPR, 3 RGBA8,
4 I8, 5 I4, 6 I8, 7 IA8, 8 C8.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture, j3d

UNIT, LEVEL = 0x1B000, 0x1B100
CH_VERSION, CH_USERDATA, CH_MODELS, CH_PACKETS, CH_STREAMS, CH_VERTICES, CH_INDICES = (
    0x1B001,
    0x1B002,
    0x1B003,
    0x1B004,
    0x1B005,
    0x1B006,
    0x1B007,
)
PRIM_OPS = {0: 0x90, 1: 0x98, 2: 0xA0, 3: 0x80}
TEX_FORMATS = {0: 4, 1: 5, 2: 14, 3: 6, 4: 1, 5: 0, 6: 1, 7: 3, 8: 9}
PTLG = b"PTLG"
MAX_PACKETS = 1 << 16


class GlError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def is_glg(head: bytes, size: int) -> bool:
    if len(head) < 16 or size < 0x40:
        return False
    cid, csize = struct.unpack_from(">II", head, 0)
    if cid & 0xFFFFFF not in (UNIT, LEVEL) or csize > size or csize < 0x30:
        return False
    inner = _u32(head, 8)
    return inner & 0xFFFFFF in (UNIT, CH_VERSION)


def _chunks(d: bytes, start: int, end: int):
    p = start
    while p + 8 <= end:
        cid, size = struct.unpack_from(">II", d, p)
        al = (cid >> 24) & 0x7F
        payload = ((p + (1 << al) + 7) & ~((1 << al) - 1)) if al else p + 8
        if payload + size > end:
            break
        yield cid & 0xFFFFFF, payload, size
        p += 8 + size


def units(d: bytes) -> list[dict[int, tuple[int, int]]]:
    """Every unit of a file as {chunk id: (payload offset, size)}."""
    out: list[dict[int, tuple[int, int]]] = []

    def walk(start: int, end: int, cur: dict | None) -> None:
        for cid, payload, size in _chunks(d, start, end):
            if cid == LEVEL:
                walk(payload, payload + size, None)
            elif cid == UNIT:
                unit: dict[int, tuple[int, int]] = {}
                out.append(unit)
                walk(payload, payload + size, unit)
            elif cur is not None:
                cur.setdefault(cid, (payload, size))

    walk(0, len(d), None)
    return out


@dataclass
class Packet:
    positions: np.ndarray  # (N, 3) f32, placed by the packet's matrix
    triangles: np.ndarray  # (T, 3)
    normals: np.ndarray | None
    colors: np.ndarray | None
    uvs: np.ndarray | None
    texture: int  # name hash
    texture2: int


@dataclass
class Model:
    id: int
    packets: list[Packet] = field(default_factory=list)


def _array(d: bytes, base: int, stride: int, n: int, sid: int) -> np.ndarray | None:
    end = base + stride * n
    if end > len(d) or n <= 0:
        return None
    if sid == 0:
        if stride == 12:
            return np.frombuffer(d, ">f4", n * 3, base).reshape(n, 3).astype(np.float32)
        if stride == 6:
            return np.frombuffer(d, ">i2", n * 3, base).reshape(n, 3).astype(np.float32) / 256.0
        return None
    if sid == 1:
        if stride == 12:
            return np.frombuffer(d, ">f4", n * 3, base).reshape(n, 3).astype(np.float32)
        if stride == 3:
            return np.frombuffer(d, np.int8, n * 3, base).reshape(n, 3).astype(np.float32) / 64.0
        return None
    if sid == 2:
        if stride == 4:
            return np.frombuffer(d, np.uint8, n * 4, base).reshape(n, 4).copy()
        if stride == 2:
            return gx_texture._rgb565_to_rgba(np.frombuffer(d, ">u2", n, base).astype(np.uint16))
        return None
    if 3 <= sid <= 8:
        if stride == 8:
            return np.frombuffer(d, ">f4", n * 2, base).reshape(n, 2).astype(np.float32)
        if stride == 4:
            return np.frombuffer(d, ">i2", n * 2, base).reshape(n, 2).astype(np.float32) / 1024.0
    return None


def parse_glg(d: bytes, warnings: list[str] | None = None) -> list[Model]:
    warn = warnings if warnings is not None else []
    out: list[Model] = []
    for u in units(d):
        try:
            models, packets, streams, vdata, idata = (
                u[CH_MODELS],
                u[CH_PACKETS],
                u[CH_STREAMS],
                u[CH_VERTICES],
                u[CH_INDICES],
            )
        except KeyError as e:
            warn.append(f"unit without chunk {e}")
            continue
        udata = u.get(CH_USERDATA, (0, 0))
        nmodels = models[1] // 16
        total = sum(_u32(d, models[0] + 16 * i) for i in range(nmodels))
        if not total or total > MAX_PACKETS:
            continue
        psize = packets[1] // total
        if psize < 66:
            warn.append(f"packet size {psize}")
            continue
        for i in range(nmodels):
            npk, mid, _pad, poff = struct.unpack_from(">4I", d, models[0] + 16 * i)
            model = Model(mid)
            for j in range(npk):
                p = packets[0] + poff + psize * j
                if p + psize > packets[0] + packets[1]:
                    warn.append(f"model {mid:08x}: packet past the table")
                    break
                _ud, ib, nv, prim, ns, so = struct.unpack_from(">IIHBBI", d, p)
                state = d[p + 16 : p + psize - 4]
                moff = _u32(state, 0x14)
                tex, tex2 = _u32(state, 0x18), _u32(state, 0x28) if len(state) >= 0x2C else 0
                if nv < 3 or prim not in PRIM_OPS:
                    continue
                if idata[0] + ib + 2 * nv > idata[0] + idata[1]:
                    warn.append(f"model {mid:08x}: indices past the buffer")
                    continue
                idx = np.frombuffer(d, ">u2", nv, idata[0] + ib).astype(np.int64)
                n = int(idx.max()) + 1
                arrays: dict[int, np.ndarray] = {}
                for k in range(ns):
                    at = streams[0] + so + 6 * k
                    if at + 6 > streams[0] + streams[1]:
                        break
                    addr, sid, stride = struct.unpack_from(">IBB", d, at)
                    arr = _array(d, vdata[0] + addr, stride, n, sid)
                    if arr is not None and sid not in arrays:
                        arrays[sid] = arr
                pos = arrays.get(0)
                if pos is None:
                    warn.append(f"model {mid:08x}: packet without positions")
                    continue
                tri = j3d.triangulate(PRIM_OPS[prim], nv)
                if not len(tri):
                    continue
                if udata[1] and moff + 64 <= udata[1]:
                    m = np.frombuffer(d, ">f4", 16, udata[0] + moff).reshape(4, 4)
                    pos = pos @ m[:3, :3] + m[3, :3]
                    nrm = arrays.get(1)
                    if nrm is not None:
                        arrays[1] = nrm @ m[:3, :3]
                uv = next((arrays[s] for s in range(3, 9) if s in arrays), None)
                model.packets.append(
                    Packet(
                        pos[idx].astype(np.float32),
                        tri,
                        None if 1 not in arrays else arrays[1][idx],
                        None if 2 not in arrays else arrays[2][idx],
                        None if uv is None else uv[idx],
                        tex,
                        tex2,
                    )
                )
            out.append(model)
    return out


# ---------------------------------------------------------------- PTLG texture bundles


def is_glt(head: bytes) -> bool:
    return head[:4] == PTLG and len(head) >= 8 and 0 < _u32(head, 4) < 1 << 16


def glt_entries(d: bytes) -> dict[int, tuple[int, int]]:
    """hash -> (offset, size) of the texture headers in a bundle."""
    n = _u32(d, 4)
    for table in (0x20, 0x10):
        base = table + 16 * n
        out = {}
        ok = True
        for i in range(n):
            h, off, size, _z = struct.unpack_from(">4I", d, table + 16 * i)
            if size < 32 or base + off + size > len(d):
                ok = False
                break
            out[h] = (base + off, size)
        if ok and out:
            return out
    return {}


def decode_glt_texture(d: bytes, at: int, size: int) -> np.ndarray:
    levels, fmt_code = struct.unpack_from(">II", d, at)
    w, h = struct.unpack_from(">HH", d, at + 14)
    entries = _u32(d, at + 20)
    fmt = TEX_FORMATS.get(fmt_code)
    if fmt is None:
        raise GlError(f"texture format {fmt_code}")
    need = gx_texture.encoded_size(fmt, w, h)
    palette = None
    if fmt in (8, 9):
        # the palette follows every mip level
        mips = need
        mw, mh = w, h
        for _ in range(1, max(levels, 1)):
            mw, mh = max(mw // 2, 1), max(mh // 2, 1)
            mips += gx_texture.encoded_size(fmt, mw, mh)
        n = entries or (16 if fmt == 8 else 256)
        palette = gx_texture.decode_palette(2, d[at + 32 + mips : at + 32 + mips + 2 * n], n)
    return gx_texture.decode(fmt, w, h, d[at + 32 : at + 32 + need], palette)
