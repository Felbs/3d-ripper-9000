"""RenderWare GameCube platform payloads: Native Data PLG geometry and texture-native rasters.
Checked on 16.8k geometries and 900 textures from Sonic Heroes and SpongeBob: BfBB.

Native Data PLG (0x510) Struct body:
  u32 platform (6)   u32 header_size   u32 data_size          <- little-endian (stream side)
  header (big-endian): u32 id, u32 unknown (0/1), u32 num_attrs,
     num_attrs x (u32 offset into data, u8 GX attribute (9 POS, 10 NRM, 11 CLR0, 13 TEX0),
                  u8 stride, u8 GX index type (2 = u8, 3 = u16), u8 0)
     num_meshes x (u32 display list offset, u32 size)      one per BinMesh PLG mesh (material)
  data: the display lists (GX opcodes: 0x98 tristrip, 0x90 triangles, 0xA0 fan, u16 BE count,
     then per vertex [u8 PNMTXIDX when the skin uses direct matrix indices] + one index per
     attribute) followed by the attribute arrays, each padded to 32 bytes: POS/NRM f32 x3,
     CLR0 RGBA8, TEX0 f32 x2, all big-endian.
  A PNMTXIDX is a GX matrix slot (0, 3, 6 ...); slot/3 indexes the Skin PLG's used-bone list.

Texture native (0x15) Struct body (big-endian), RW >= 3.3:
  u32 platform (6), u32 (filter | addrU << 8 | addrV << 12), u32 x4 unknown (0,1,1,0),
  char name[32], char mask[32], u32 raster format | type, u16 w, u16 h, u8 depth, u8 mips,
  u8 GX texture format, u8 palette format (0 IA8, 1 RGB565, 2 RGB5A3; 0xFF none),
  [palette u16[16|256] for C4/C8], u32 has_alpha?, u32 data size, all mip levels back to back.
RW 3.2 (Sonic Heroes textures/*.txd): platform, filter, name[32], mask[32], u32 raster
  format, u32 0, u16 w, u16 h, u8 depth, u8 mips, u8 type, u8 compressed, u32 size, data:
  compressed = CMPR, else 16 bpp RGB565 / RGB5A3 or 32 bpp RGBA8 by raster pixel format.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture, j3d
from gcrip.formats import rwstream as rw

GX_POS = 9
GX_NRM = 10
GX_CLR0 = 11
GX_CLR1 = 12
GX_TEX0 = 13
GX_PNMTXIDX = 0

_ATTR_COMPS = {GX_POS: 3, GX_NRM: 3, GX_CLR0: 4, GX_CLR1: 4, GX_TEX0: 2}
_DRAW_OPS = {0x80, 0x88, 0x90, 0x98, 0xA0}


@dataclass
class NativeMesh:
    """One display-list run of a geometry, already de-indexed into per-corner attribute rows."""

    mesh: int  # BinMesh index (material slot)
    triangles: np.ndarray  # (T,3) into the rows below
    positions: np.ndarray  # (N,3)
    normals: np.ndarray | None
    colors: np.ndarray | None  # (N,4) float 0..1
    uvs: np.ndarray | None
    vertex_index: np.ndarray  # (N,) original position index (skin lookups)
    matrix_slot: np.ndarray | None  # (N,) PNMTXIDX / 3, or None


def _read_array(data: bytes, off: int, end: int, attr: int, stride: int, frac: int) -> np.ndarray:
    """One attribute array (big-endian) -> float rows; count from the padded extent."""
    ncomp = _ATTR_COMPS.get(attr, stride // 4 or 1)
    count = max(0, (min(end, len(data)) - off) // stride)
    if attr in (GX_CLR0, GX_CLR1):
        if stride == 4:
            arr = (
                np.frombuffer(data, np.uint8, count * 4, off).reshape(count, 4).astype(np.float32)
                / 255.0
            )
        elif stride == 2:  # RGB565 / RGBA4 - decode as RGB565 (most common)
            v = np.frombuffer(data, ">u2", count, off).astype(np.uint32)
            arr = np.stack(
                [((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0, np.ones(count)],
                axis=1,
            ).astype(np.float32)
        else:
            arr = np.ones((count, 4), np.float32)
        return arr
    if stride == ncomp * 4:
        return (
            np.frombuffer(data, ">f4", count * ncomp, off).reshape(count, ncomp).astype(np.float32)
        )
    if stride == ncomp * 2:
        raw = (
            np.frombuffer(data, ">i2", count * ncomp, off).reshape(count, ncomp).astype(np.float32)
        )
        return raw / float(1 << frac) if frac else raw
    if stride == ncomp:
        raw = (
            np.frombuffer(data, np.int8, count * ncomp, off)
            .reshape(count, ncomp)
            .astype(np.float32)
        )
        return raw / float(1 << frac) if frac else raw
    raise rw.RwError(f"native attribute {attr} with stride {stride} not understood")


PAD_TEXT = frozenset(b"PAD0123456789")


def skip_pad(data: bytes, at: int) -> int:
    """Past a run of ``PAD32`` / ``PAD128`` filler - Midway's file-alignment text, which
    stops mid-word at the alignment boundary (``PAD32PAD32PA``)."""
    if data[at : at + 2] != b"PA":
        return at
    end = at
    while end < len(data) and data[end] in PAD_TEXT:
        end += 1
    return end


def _take(arrays: dict[int, np.ndarray], v: np.ndarray, attr: int) -> np.ndarray | None:
    """De-index one attribute for the display-list corners `v`."""
    if attr not in arrays or f"a{attr}" not in v.dtype.names:
        return None
    a = arrays[attr]
    if len(a) == 0:
        return None
    idx = v[f"a{attr}"].astype(np.int64)
    return a[np.minimum(idx, len(a) - 1)]


NORMAL_FRAC = {3: 6, 6: 14}  # GX fixes the normal fraction by type: S8 -> 6 bits, S16 -> 14


def decode_native(
    body: bytes, direct_matrix: bool, fracs: dict[int, int] | None = None
) -> list[NativeMesh]:
    """``fracs``: attribute -> fraction bits to use when the table gives none (Midway's
    quantised streams carry theirs in code, not in the data)."""
    if len(body) < 24:
        raise rw.RwError("native data too short")
    platform, hsz, dsz = struct.unpack_from("<3I", body, 0)
    if platform != rw.PLATFORM_GAMECUBE:
        raise rw.RwError(f"native data for platform {platform}, not GameCube")
    h = 12
    if h + hsz > len(body) or hsz < 12:
        raise rw.RwError("native data header out of range")
    nattr = struct.unpack_from(">I", body, h + 8)[0]
    if 12 + 8 * nattr > hsz:
        raise rw.RwError("native data attribute table out of range")
    attrs = [struct.unpack_from(">IBBBB", body, h + 12 + 8 * i) for i in range(nattr)]
    nmesh = (hsz - 12 - 8 * nattr) // 8
    meshes = [struct.unpack_from(">II", body, h + 12 + 8 * nattr + 8 * i) for i in range(nmesh)]
    # Midway (Mortal Kombat) pads the data to a 32-byte file position with "PAD32" text; the
    # display-list and array offsets count from the padded start
    data_off = skip_pad(body, h + hsz)
    data_end = min(len(body), data_off + dsz)
    # attribute arrays: extent runs to the next array (arrays follow the display lists in order)
    starts = sorted(a[0] for a in attrs)
    arrays: dict[int, np.ndarray] = {}
    fields: list[tuple[int, str]] = []
    for off, attr, stride, itype, frac in attrs:
        nxt = min([s for s in starts if s > off] + [dsz])
        if not frac and attr == GX_NRM and stride in NORMAL_FRAC:
            frac = NORMAL_FRAC[stride]
        elif not frac and fracs:
            frac = fracs.get(attr, 0)
        arrays[attr] = _read_array(body, data_off + off, data_off + nxt, attr, stride, frac)
        if itype == 2:
            fields.append((attr, "u1"))
        elif itype == 3:
            fields.append((attr, ">u2"))
        elif itype == 1:
            fields.append((attr, "u1"))  # direct u8 data is only plausible for matrix indices
        elif itype != 0:
            raise rw.RwError(f"native attribute {attr}: index type {itype}")
    dt_fields = ([("mtx", "u1")] if direct_matrix else []) + [(f"a{a}", t) for a, t in fields]
    vdt = np.dtype(dt_fields)
    stride = vdt.itemsize
    out: list[NativeMesh] = []
    for mi, (moff, msize) in enumerate(meshes):
        p = data_off + moff
        end = min(data_off + moff + msize, data_end)
        tris = []
        rows: list[np.ndarray] = []
        base = 0
        while p + 3 <= end:
            op = body[p]
            if op == 0:
                p += 1
                continue
            if op not in _DRAW_OPS:
                break
            count = struct.unpack_from(">H", body, p + 1)[0]
            p += 3
            if p + count * stride > end:
                break
            arr = np.frombuffer(body, vdt, count, p)
            p += count * stride
            t = j3d.triangulate(op, count)
            if len(t):
                tris.append(t + base)
            rows.append(arr)
            base += count
        if not rows:
            continue
        v = np.concatenate(rows)
        tri = np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)
        pos = _take(arrays, v, GX_POS)
        if pos is None:
            continue
        vidx = v[f"a{GX_POS}"].astype(np.int64)
        out.append(
            NativeMesh(
                mesh=mi,
                triangles=tri,
                positions=pos,
                normals=_take(arrays, v, GX_NRM),
                colors=_take(arrays, v, GX_CLR0),
                uvs=_take(arrays, v, GX_TEX0),
                vertex_index=vidx,
                matrix_slot=(v["mtx"].astype(np.int64) // 3) if direct_matrix else None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------

_OLD_FMT = {
    0x100: 5,
    0x200: 4,
    0x300: 5,
    0x400: 1,
    0x500: 6,
    0x600: 6,
    0x800: 1,
}  # raster pixel fmt -> GX


@dataclass
class TextureNative:
    name: str
    mask: str
    width: int
    height: int
    gx_format: int
    filter_addr: int
    image: np.ndarray | None  # (h,w,4) u8, level 0
    error: str | None = None


def texture_names(data: bytes) -> list[str]:
    """Names of the textures in a TXD stream without decoding rasters."""
    out = []
    try:
        for t in _texture_structs(data):
            out.append(t[0])
    except (rw.RwError, struct.error):
        pass
    return out


def _texture_structs(data: bytes):
    c = rw.top(data)
    if c.type != rw.TEXDICT:
        raise rw.RwError(f"not a texture dictionary (chunk {c.type:#x})")
    for k in rw.chunks(data, c.off, c.end):
        if k.type != rw.TEXNATIVE:
            continue
        st = rw.child(data, k, rw.STRUCT)
        if st is None or st.size < 72:
            continue
        old = k.version < 0x33000
        name_off = st.off + (8 if old else 24)
        name = data[name_off : name_off + 32].split(b"\0")[0].decode("latin-1")
        mask = data[name_off + 32 : name_off + 64].split(b"\0")[0].decode("latin-1")
        yield name, mask, st, old


def _decode_one(data: bytes, st: rw.Chunk, old: bool) -> tuple[int, int, int, int, np.ndarray]:
    platform = struct.unpack_from(">I", data, st.off)[0]
    if platform != rw.PLATFORM_GAMECUBE:
        raise rw.RwError(f"texture for platform {platform}, not GameCube")
    filt = struct.unpack_from(">I", data, st.off + 4)[0]
    if old:
        p = st.off + 72
        rf, _z, w, h, depth, _mips, _typ, compressed = struct.unpack_from(">IIHHBBBB", data, p)
        p += 16
        size = struct.unpack_from(">I", data, p)[0]
        p += 4
        if compressed:
            fmt = 14
        elif depth == 8 and rf & 0x2000:  # PAL8
            fmt = 9
        else:
            fmt = _OLD_FMT.get(rf & 0xF00, 4 if depth == 16 else 6)
        palette = None
        if fmt in (8, 9):
            n = 16 if fmt == 8 else 256
            palette = gx_texture.decode_palette(
                2 if (rf & 0xF00) in (0x100, 0x300) else 1, data[p : p + 2 * n], n
            )
            p += 2 * n
        need = gx_texture.encoded_size(fmt, w, h) if fmt in gx_texture.TILE_DIMS else size
        if data[p : p + 2] == b"PA" and 0 < size - need < 128:
            p += size - need  # Midway's alignment filler, counted in the size
            size = need
        raw = data[p : min(st.end, p + size)]
    else:
        p = st.off + 88
        rf, w, h, depth, mips, fmt, pal_fmt = struct.unpack_from(">IHHBBBB", data, p)
        p += 12
        palette = None
        if fmt in (8, 9):
            n = 16 if fmt == 8 else 256
            palette = gx_texture.decode_palette(
                pal_fmt if pal_fmt < 3 else 1, data[p : p + 2 * n], n
            )
            p += 2 * n
        elif fmt == 10:
            raise rw.RwError("C14X2 texture")
        _has_alpha, size = struct.unpack_from(">II", data, p)
        p += 8
        # Midway counts its alignment filler in the size: the pixels are the tail of it
        need = gx_texture.encoded_size(fmt, w, h) if fmt in gx_texture.TILE_DIMS else size
        if data[p : p + 2] == b"PA" and 0 < size - need < 128:
            p += size - need
            size = need
        raw = data[p : min(st.end, p + size)]
    if w == 0 or h == 0 or w > 4096 or h > 4096:
        raise rw.RwError(f"texture size {w}x{h}")
    img = gx_texture.decode(fmt, w, h, raw, palette)
    return w, h, fmt, filt, img


def parse_txd(data: bytes) -> list[TextureNative]:
    out = []
    for name, mask, st, old in _texture_structs(data):
        try:
            w, h, fmt, filt, img = _decode_one(data, st, old)
            out.append(TextureNative(name, mask, w, h, fmt, filt, img))
        except (rw.RwError, ValueError, struct.error) as e:
            out.append(TextureNative(name, mask, 0, 0, 0, 0, None, error=str(e)))
    return out


# -- the Piglet header: array offsets declared, meshes tabled -------------------------------
#
# Piglet's BIG GAME (and, to be checked, the other RenderWare 3.6 GameCube titles) writes a
# native block whose header is not the attribute table `decode_native` reads, but this::
#
#     +0   u32 LE  platform 6
#     +4   u32 LE  header size   76 + 8 * meshes
#     +8   u32 LE  data size
#     +12  header, big-endian from here:
#            +8   u8  flags      bit 2 = colours present
#            +24  u32 x4         data offsets of the position, normal, colour, texcoord arrays
#                                (0 = absent)
#            +68  meshes x { u32 size; u32 offset }   one display-list run per material
#     +12+header   data:  the display lists first, then the arrays at the offsets above
#
# A vertex in a display list is one index per present attribute - all holding the same value,
# so the arrays are interleaved and one index addresses them all - **one byte wide when the
# geometry has 255 vertices or fewer, two otherwise**.  Lists are padded to 32.
#
# What pins it: the position array's declared offset plus `vertices * 12` is the normal
# array's offset, and that plus `vertices * 12` is the colour array's, on every geometry read;
# the normals are unit length; and the mesh table's sizes sum to the first array offset.
# Measured over ten header shapes (76 to 116 bytes, 1 to 6 meshes, both index widths) with the
# largest index never exceeding vertices - 1.

PIGLET_HEADER_BASE = 76
PIGLET_ARRAYS_AT = 24
PIGLET_MESHES_AT = 68
PIGLET_FLAGS_AT = 8
PIGLET_HAS_COLOURS = 0x04
#: arrays and display lists are padded to this
PIGLET_ALIGN = 32


def looks_like_piglet_native(body: bytes) -> bool:
    if len(body) < 12 + PIGLET_HEADER_BASE:
        return False
    platform, hsz, dsz = struct.unpack_from("<3I", body, 0)
    if (
        platform != rw.PLATFORM_GAMECUBE
        or hsz < PIGLET_HEADER_BASE
        or (hsz - PIGLET_HEADER_BASE) % 8
    ):
        return False
    return 12 + hsz + dsz <= len(body) + 64


def decode_native_piglet(body: bytes, nverts: int) -> list[NativeMesh]:
    platform, hsz, dsz = struct.unpack_from("<3I", body, 0)
    if platform != rw.PLATFORM_GAMECUBE:
        raise rw.RwError(f"native data for platform {platform}, not GameCube")
    h = 12
    if hsz < PIGLET_HEADER_BASE or (hsz - PIGLET_HEADER_BASE) % 8 or h + hsz > len(body):
        raise rw.RwError("not a Piglet-style native header")
    data = h + hsz
    offs = struct.unpack_from(">4I", body, h + PIGLET_ARRAYS_AT)
    nmesh = (hsz - PIGLET_MESHES_AT) // 8
    table = [struct.unpack_from(">2I", body, h + PIGLET_MESHES_AT + 8 * i) for i in range(nmesh)]
    has_colours = bool(body[h + PIGLET_FLAGS_AT] & PIGLET_HAS_COLOURS) and offs[2] != 0
    has_uvs = offs[3] != 0
    if nverts <= 0 or offs[0] == 0 or offs[1] == 0:
        raise rw.RwError("Piglet native header names no position or normal array")
    # every array is padded to 32 bytes, so the gap to the next array is the exact size
    # rounded up - measured on 120 geometries the over-run is 0 to 28 bytes and never more
    span = offs[1] - offs[0]
    if not nverts * 12 <= span < nverts * 12 + PIGLET_ALIGN:
        raise rw.RwError(
            f"position array is {span} bytes for {nverts} vertices (want {nverts * 12}, padded)"
        )
    lists = sum(s for s, _ in table)
    if not lists <= offs[0] < lists + PIGLET_ALIGN:
        raise rw.RwError("mesh table does not account for the display lists")

    def arr(off: int, dtype: str, comps: int, count: int):
        at = data + off
        need = count * comps * np.dtype(dtype).itemsize
        if at + need > len(body):
            raise rw.RwError("native array runs past the block")
        return np.frombuffer(body, dtype, count * comps, at).reshape(count, comps)

    positions = arr(offs[0], ">f4", 3, nverts).astype(np.float32)
    normals = arr(offs[1], ">f4", 3, nverts).astype(np.float32)
    colors = arr(offs[2], np.uint8, 4, nverts).astype(np.float32) / 255.0 if has_colours else None
    uvs = arr(offs[3], ">f4", 2, nverts).astype(np.float32) if has_uvs else None
    attrs = 2 + int(has_colours) + int(has_uvs)
    width = 1 if nverts <= 256 else 2
    idt = np.uint8 if width == 1 else ">u2"
    out: list[NativeMesh] = []
    for mi, (size, off) in enumerate(table):
        p = data + off
        end = min(p + size, data + offs[0])
        tris: list[np.ndarray] = []
        while p + 3 <= end:
            op = body[p]
            if op == 0:
                p += 1
                continue
            if (op & 0xF8) != 0x98:
                break
            count = struct.unpack_from(">H", body, p + 1)[0]
            p += 3
            span = count * attrs * width
            if p + span > end:
                break
            idx = (
                np.frombuffer(body, idt, count * attrs, p)
                .reshape(count, attrs)[:, 0]
                .astype(np.int64)
            )
            p += span
            if count >= 3:
                a, b, c = idx[:-2], idx[1:-1], idx[2:]
                even = np.arange(count - 2) % 2 == 0
                t = np.where(even[:, None], np.stack([a, b, c], 1), np.stack([b, a, c], 1))
                keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
                tris.append(t[keep])
        if not tris:
            continue
        tri = np.concatenate(tris)
        if int(tri.max()) >= nverts:
            raise rw.RwError(f"mesh {mi} indexes vertex {int(tri.max())} of {nverts}")
        out.append(
            NativeMesh(
                mesh=mi,
                triangles=tri.astype(np.uint32),
                positions=positions,
                normals=normals,
                colors=colors,
                uvs=uvs,
                vertex_index=np.arange(nverts, dtype=np.uint32),
                matrix_slot=None,
            )
        )
    return out
