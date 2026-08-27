"""EA Black Box "chunk stream" files as found on the GameCube builds of Need for Speed
(Underground 2, GUGE69). Everything below was worked out on that disc.

Chunk stream: (u32 LE id, u32 LE size) headers; ids with the top bit set are containers
of further chunks; id 0 is padding. The GameCube build keeps the PC little-endian chunk
headers and little-endian metadata; only the GX-native payloads (display lists, vertex
arrays, texture tiles) are big-endian.

Disc packing: NFSUNDER/ZDIR.BIN is a hash-sorted directory of 24-byte records
(name hash, ZZDATA index, sector offset, disc sector, size, hash 2) into ZZDATA0-3.BIN,
where each member starts on a 2048-byte sector. `scan_pack` recovers the members without
the directory by walking chunk headers from sector boundaries.

Texture pack (0xB3300000): 0xB3310000 info {0x33310001 name/path, 0x33310002 hash list
(u32 + pad, 8 bytes each), 0x33310003 records (u32 hash, u32 offset, u32 packed size,
u32 unpacked size, 0x100, 0) - offsets are absolute in the file}; 0xB3320000 data. Each
texture is a JDLZ (or HUFF) stream that unpacks to [GX tiles][palette 0x200][184-byte
trailer]: trailer +0x0C name[24], +0x24 hash, +0x38 data size, +0x3C palette size,
+0x44 u16 width, +0x46 u16 height, +0x48 log2 w, log2 h, mip count, +0xB4 u32 BE GX
format. Palettes are RGB5A3. Track packs instead keep the PC layout (0x33310004 124-byte
records + 0x33310005 60-byte platform records, plain GX tiles in the data chunk) - see
`_parse_raw_records`.

Geometry (0x80134000): 0x80134001 info {0x00134002 header (+0x10 source path),
0x00134003 part hashes, 0x00134004 part table}, then 0x80134010 per part
{0x00134011 192-byte header (+0x10 hash, +0x14 u16 tris, +0x16 u16 verts, +0x20 bbox
min, +0x30 bbox max, +0x40 4x4 matrix, +0xA4 name), 0x00134012 texture hashes (u32 + pad),
0x00134013 shader hashes, 0x80134100 mesh {0x00134800 header, 0x00134801 strip table,
0x00134802 data}}. Mesh blocks start with 0x11 fill bytes to align, then are big-endian:
  0x00134800: u32 flags, u16 strips, u16 verts, u32 total, u32 pos, u32 nrm, u32 clr,
              u32 uv, u32 (unused) - offsets into the 0x00134802 data
  0x00134801: per strip u32 offset, u16 size, u16 flags, u8 count, u8 group, u8 texture,
              u8 shader, u16 format, u16 bytes
  0x00134802: strips (format bit 0x8000: a GX 0x9A/count header precedes the vertices;
              format bits 0x1000/0x0800/0x0400/0x0200: 16-bit position/normal/aux/uv
              indices, else 8-bit; the header form carries one extra aux index), then
              positions (s16 xyz fixed point with the scale taken from the bbox, or f32 xyz
              for attribute set 0x01), normals s8 xyz + pad (1/64), colours RGBA8,
              uvs s16 (1/4096).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

SECTOR = 0x800
# high halves of every top-level chunk id seen on the disc (0x0003xxxx track/frontend data,
# 0x0013xxxx geometry, 0x00E3xxxx, 0xB33xxxxx texture packs, 0xB030xxxx, and their
# container forms with the top bit set) - anything else at a sector boundary is not a stream
_ROOT_HI = {0x0003, 0x0013, 0x00E3, 0x8003, 0x8013, 0x80E3, 0xB330, 0xB030}
_CHILD_HI = _ROOT_HI | {0xB331, 0xB332}

ID_GEOMETRY = 0x80134000
ID_TPK = 0xB3300000


def chunk_ok(cid: int) -> bool:
    return (cid >> 16) in _ROOT_HI or cid == 0x53219999


def is_stream(head: bytes) -> bool:
    """A file whose first chunk is one of the NFS families."""
    if len(head) < 8:
        return False
    cid, size = struct.unpack_from("<II", head, 0)
    return cid != 0 and size != 0 and chunk_ok(cid)


def chunks(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    """(id, payload offset, payload size) for the chunks between start and end."""
    out = []
    p = start
    while p + 8 <= end:
        cid, size = struct.unpack_from("<II", data, p)
        if p + 8 + size > end:
            break
        out.append((cid, p + 8, size))
        p += 8 + size
    return out


def _find(lst, cid):
    return [c for c in lst if c[0] == cid]


def _skip_fill(data: bytes, p: int, end: int) -> int:
    while p < end and data[p] == 0x11:
        p += 1
    return p


# ---------------------------------------------------------------- JDLZ / HUFF


def jdlz_decompress(src: bytes) -> bytes:
    """JDLZ: EA's byte-oriented LZ (magic 'JDLZ', u8 2, u8 0x10, u16 0, u32 out, u32 in)."""
    if src[:4] != b"JDLZ":
        raise ValueError("not JDLZ")
    out_len = struct.unpack_from("<I", src, 8)[0]
    out = bytearray(out_len)
    f1 = f2 = 1
    ip, op = 16, 0
    n = len(src)
    while ip < n and op < out_len:
        if f1 == 1:
            f1 = src[ip] | 0x100
            ip += 1
        if f2 == 1:
            f2 = src[ip] | 0x100
            ip += 1
        if f1 & 1:
            if f2 & 1:
                length = (src[ip + 1] | ((src[ip] & 0xF0) << 4)) + 3
                back = (src[ip] & 0x0F) + 1
            else:
                back = (src[ip + 1] | ((src[ip] & 0xE0) << 3)) + 17
                length = (src[ip] & 0x1F) + 3
            ip += 2
            for i in range(length):
                if op + i >= out_len:
                    break
                out[op + i] = out[op + i - back]
            op += length
            f2 >>= 1
        else:
            out[op] = src[ip]
            ip += 1
            op += 1
        f1 >>= 1
    return bytes(out)


# ---------------------------------------------------------------- ZZDATA scanning


@dataclass
class PackMember:
    name: str
    start: int
    end: int


def _stream_end(data: bytes, p: int, n: int) -> int:
    """Walk top-level chunks from p; the member ends at the first byte that is not a chunk."""
    while p + 8 <= n:
        cid, size = struct.unpack_from("<II", data, p)
        if cid == 0 and size == 0:
            break
        if cid != 0 and not chunk_ok(cid):
            break
        if p + 8 + size > n or size > MAX_CHUNK:
            break
        p += 8 + size
    return p


MAX_CHUNK = 128 << 20


def _stream_start(data: bytes, p: int, n: int) -> bool:
    """A plausible member start: a known chunk id whose first child (containers) or
    successor (leaf chunks) is itself a chunk - audio and video sectors do not pass."""
    cid, size = struct.unpack_from("<II", data, p)
    if cid == 0 and 0 < size < SECTOR and p + 16 + size <= n:  # leading alignment padding
        p += 8 + size
        cid, size = struct.unpack_from("<II", data, p)
    if cid == 0 or size == 0 or size > MAX_CHUNK or not chunk_ok(cid) or p + 8 + size > n:
        return False
    if cid & 0x80000000:
        if p + 16 > n:
            return False
        child, _ = struct.unpack_from("<II", data, p + 8)
        return child == 0 or (child >> 16) in _CHILD_HI
    q = p + 8 + size
    if q + 8 > n:
        return True
    nxt, _ = struct.unpack_from("<II", data, q)
    return nxt == 0 or chunk_ok(nxt)


def scan_pack(data: bytes) -> list[PackMember]:
    """Members of a ZZDATA*.BIN pack: every sector-aligned chunk stream."""
    n = len(data)
    out: list[PackMember] = []
    seen: dict[str, int] = {}
    p = 0
    while p + 8 <= n:
        if _stream_start(data, p, n):
            cid = struct.unpack_from("<I", data, p)[0]
            end = max(_stream_end(data, p, n), p + 8)
            name = member_name(data, p, end) or f"{p:08x}_{cid:08x}.bin"
            if name in seen:
                seen[name] += 1
                stem, _, ext = name.rpartition(".")
                name = f"{stem}#{seen[name]}.{ext}"
            else:
                seen[name] = 0
            out.append(PackMember(name, p, end))
            p = (end + SECTOR - 1) // SECTOR * SECTOR
        else:
            p += SECTOR
    return out


def _cstr(data: bytes, off: int, n: int) -> str:
    return data[off : off + n].split(b"\0", 1)[0].decode("latin-1", "replace")


def member_name(data: bytes, start: int, end: int) -> str | None:
    """A path for a chunk stream from what it declares about itself: the geometry source
    path ('..\\GAMECUBE\\CDUG2\\CARS\\RX7\\GEOMETRY.BIN' -> 'CARS/RX7/GEOMETRY.BIN') or the
    texture pack path ('Global\\CarTextures.tpk')."""
    geo = tpk = None
    for cid, off, size in chunks(data, start, end):
        if cid == ID_GEOMETRY and geo is None:
            info = _find(chunks(data, off, off + size), 0x80134001)
            if info:
                hdr = _find(chunks(data, info[0][1], info[0][1] + info[0][2]), 0x00134002)
                if hdr:
                    geo = _cstr(data, hdr[0][1] + 0x10, 0x38)
        elif cid == ID_TPK and tpk is None:
            info = _find(chunks(data, off, off + size), 0xB3310000)
            if info:
                nm = _find(chunks(data, info[0][1], info[0][1] + info[0][2]), 0x33310001)
                if nm:
                    tpk = _cstr(data, nm[0][1] + 0x20, 0x40) or _cstr(data, nm[0][1] + 4, 0x1C)
    src = geo or tpk
    if not src:
        return None
    parts = [p for p in src.replace("\\", "/").split("/") if p and p != ".."]
    if geo:
        # drop the platform/build prefix ("GAMECUBE", "CDUG2", ...) - keep the last 3 parts
        parts = parts[-3:]
    return "/".join(parts) if parts else None


# ---------------------------------------------------------------- texture packs


@dataclass
class TpkTexture:
    hash: int
    offset: int  # absolute in the file (packed) / relative to the data payload (raw)
    packed: int
    unpacked: int
    raw: bool = False  # True: plain GX tiles described by the record, not a JDLZ stream
    name: str = ""
    fmt: int = 0
    width: int = 0
    height: int = 0
    pal_offset: int = -1
    pal_size: int = 0
    data_base: int = 0  # file offset of the data payload (after its 0x11 fill), raw only


@dataclass
class Tpk:
    name: str
    path: str
    start: int
    textures: dict[int, TpkTexture] = field(default_factory=dict)


def parse_tpks(data: bytes, start: int = 0, end: int | None = None) -> list[Tpk]:
    end = len(data) if end is None else end
    out = []
    for cid, off, size in chunks(data, start, end):
        if cid != ID_TPK:
            continue
        info = _find(chunks(data, off, off + size), 0xB3310000)
        if not info:
            continue
        sub = chunks(data, info[0][1], info[0][1] + info[0][2])
        name = path = ""
        nm = _find(sub, 0x33310001)
        if nm:
            name = _cstr(data, nm[0][1] + 4, 0x1C)
            path = _cstr(data, nm[0][1] + 0x20, 0x40)
        tpk = Tpk(name, path, off - 8)
        for rec in _find(sub, 0x33310003):
            for i in range(rec[2] // 24):
                h, o, packed, unpacked = struct.unpack_from("<IIII", data, rec[1] + i * 24)
                tpk.textures[h] = TpkTexture(h, o, packed, unpacked)
        rec4 = _find(sub, 0x33310004)
        if rec4 and not tpk.textures:
            _parse_raw_records(data, rec4[0], _find(sub, 0x33310005), off, size, tpk)
        _rebase_packed(data, tpk)
        out.append(tpk)
    return out


def _rebase_packed(data: bytes, tpk: Tpk) -> None:
    """Packed-record offsets are absolute in the pack member the texture pack was written
    into; when the pack sits behind other data in a merged member they are relative to
    the pack chunk instead - pick whichever base lands on a JDLZ/HUFF stream."""
    packed = [t for t in tpk.textures.values() if not t.raw]
    if not packed:
        return
    first = min(packed, key=lambda t: t.offset)
    if data[first.offset : first.offset + 4] in (b"JDLZ", b"HUFF"):
        return
    shifted = tpk.start + first.offset
    if data[shifted : shifted + 4] in (b"JDLZ", b"HUFF"):
        for t in packed:
            t.offset += tpk.start


def _parse_raw_records(data, rec4, rec5, off, size, tpk) -> None:
    """Track packs keep the PC layout: 124-byte records (+0x0C name, +0x24 hash, +0x30
    data offset, +0x34 palette offset, +0x38 data size, +0x3C palette size, +0x44 u16
    width/height) paired with 60-byte platform records whose last u32 (big-endian) is
    the GX format; offsets are relative to the 0x33320002 payload after its fill."""
    base = 0
    dat = _find(chunks(data, off, off + size), 0xB3320000)
    if dat:
        d2 = _find(chunks(data, dat[0][1], dat[0][1] + dat[0][2]), 0x33320002)
        if d2:
            base = _skip_fill(data, d2[0][1], d2[0][1] + d2[0][2])
    if not base:
        return
    n = rec4[2] // 124
    for i in range(n):
        r = rec4[1] + i * 124
        h = struct.unpack_from("<I", data, r + 0x24)[0]
        doff, poff, dsize, psize = struct.unpack_from("<IIII", data, r + 0x30)
        w, hgt = struct.unpack_from("<HH", data, r + 0x44)
        fmt = -1
        if rec5 and (i + 1) * 60 <= rec5[0][2]:
            fmt = struct.unpack_from(">I", data, rec5[0][1] + i * 60 + 0x38)[0]
        tpk.textures[h] = TpkTexture(
            h, doff, dsize, dsize, raw=True, name=_cstr(data, r + 0x0C, 24), fmt=fmt,
            width=w, height=hgt, pal_offset=poff if poff != 0xFFFFFFFF else -1,
            pal_size=psize, data_base=base,
        )  # fmt: skip


def decode_tpk_texture(data: bytes, t: TpkTexture) -> tuple[str, np.ndarray]:
    """(name, RGBA) for one texture-pack record in `data`."""
    if not t.raw:
        return decode_texture(data[t.offset : t.offset + t.packed])
    if t.fmt not in gx_texture.TILE_DIMS:
        raise ValueError(f"unknown GX format {t.fmt}")
    if t.width == 0 or t.height == 0:
        raise ValueError("zero-sized texture")
    palette = None
    if t.fmt in (8, 9, 10):
        count = 16 if t.fmt == 8 else 256
        if t.pal_offset < 0:
            raise ValueError("paletted texture without a palette")
        po = t.data_base + t.pal_offset
        palette = gx_texture.decode_palette(2, data[po : po + count * 2], count)
    do = t.data_base + t.offset
    rgba = gx_texture.decode(t.fmt, t.width, t.height, data[do : do + t.packed], palette)
    return t.name or f"tex_{t.hash:08x}", rgba


def decode_texture(blob: bytes) -> tuple[str, np.ndarray]:
    """One packed TPK texture -> (name, RGBA)."""
    if blob[:4] == b"JDLZ":
        raw = jdlz_decompress(blob)
    elif blob[:4] == b"HUFF":
        raise ValueError("HUFF-compressed texture (not supported)")
    else:
        raw = blob
    if len(raw) < 0xB8:
        raise ValueError("texture too small")
    tr = raw[-0xB8:]
    name = _cstr(tr, 0x0C, 24)
    data_size, pal_size = struct.unpack_from("<II", tr, 0x38)
    width, height = struct.unpack_from("<HH", tr, 0x44)
    fmt = struct.unpack_from(">I", tr, 0xB4)[0]
    if width == 0 or height == 0:
        raise ValueError("zero-sized texture")
    if fmt not in gx_texture.TILE_DIMS:
        raise ValueError(f"unknown GX format {fmt}")
    palette = None
    if fmt in (8, 9, 10):
        count = 16 if fmt == 8 else 256
        palette = gx_texture.decode_palette(2, raw[data_size : data_size + count * 2], count)
    rgba = gx_texture.decode(fmt, width, height, raw[:data_size], palette)
    return name, rgba


# ---------------------------------------------------------------- geometry


@dataclass
class Strip:
    texture: int
    shader: int
    verts: list[dict]  # per vertex {"pos": i, "uv": i, "nrm"?: i, "clr"?: i}


@dataclass
class Part:
    name: str
    hash: int
    tris: int
    verts: int
    bbox: tuple[np.ndarray, np.ndarray]
    matrix: np.ndarray
    textures: list[int]
    shaders: list[int]
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray  # (N,3) f32
    uvs: np.ndarray  # (N,2) f32
    colors: np.ndarray  # (N,4) f32
    strips: list[Strip]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Geometry:
    source: str
    parts: list[Part]
    warnings: list[str] = field(default_factory=list)


# The low byte of a strip's format word names its vertex attribute set (it matches the
# GX vertex-format slot in the 0x98|vat draw opcode: 0x01 -> VAT 1, 0x16 -> VAT 2,
# 0x20 -> VAT 3). Bits 0x10/0x08/0x04/0x02 of the high byte widen the 1st..4th slot's
# index to 16 bits. VAT 2 lists with a GX header carry the 3rd slot twice.
_ATTR_SETS = {
    0x16: ("pos", "nrm", "aux", "uv"),
    0x20: ("pos", "clr", "uv"),
    0x01: ("pos", "clr", "uv"),
}
_SLOT_BITS = {0: 0x10, 1: 0x08, 2: 0x04, 3: 0x02}


def _strip_layout(fmt: int, has_header: bool) -> list[tuple[str, int]] | None:
    """[(attribute, index width)] for one strip, or None for an unknown attribute set."""
    attrs = _ATTR_SETS.get(fmt & 0xFF)
    if attrs is None:
        return None
    bits = (fmt >> 8) & 0x7F
    slots = (0, 2, 3) if len(attrs) == 3 else (0, 1, 2, 3)  # pos, clr, uv skip the normal slot
    layout = [(a, 2 if bits & _SLOT_BITS[sl] else 1) for a, sl in zip(attrs, slots, strict=True)]
    if has_header and len(attrs) == 4:
        layout.insert(3, ("aux2", layout[2][1]))
    return layout


def _read_strip(data: bytes, p: int, count: int, fmt: int, size: int) -> list[dict]:
    """Per vertex {attribute: index} for one strip."""
    has_header = bool(fmt & 0x8000)
    if has_header:
        p += 3
        size -= 3
    layout = _strip_layout(fmt, has_header)
    if layout is None:
        raise ValueError(f"unknown vertex attribute set {fmt & 0xFF:#x}")
    stride = sum(w for _, w in layout)
    if count * stride > size:
        raise ValueError(f"strip needs {count * stride} bytes, has {size} (fmt {fmt:04x})")
    verts = []
    for _ in range(count):
        q = p
        v = {}
        for attr, w in layout:
            v[attr] = data[q] if w == 1 else (data[q] << 8 | data[q + 1])
            q += w
        verts.append(v)
        p += stride
    return verts


def _pos_scale(raw: np.ndarray, bbox: tuple[np.ndarray, np.ndarray]) -> float:
    """Fixed-point positions carry no shift; pick the power of two that lands them in
    the part's bounding box (1/4096 for cars, coarser for track sections)."""
    amax = float(np.abs(raw).max()) if raw.size else 0.0
    bmax = float(np.abs(np.concatenate(bbox)).max())
    if amax <= 0 or bmax <= 0:
        return 1.0 / 4096
    k = round(math.log2(amax / bmax))
    return 2.0**-k


def _parse_part(data: bytes, off: int, size: int) -> Part | None:
    sub = chunks(data, off, off + size)
    hdr = _find(sub, 0x00134011)
    if not hdr:
        return None
    h = _skip_fill(data, hdr[0][1], hdr[0][1] + hdr[0][2])  # some headers are 0x11-padded
    phash = struct.unpack_from("<I", data, h + 0x10)[0]
    tris, nverts = struct.unpack_from("<HH", data, h + 0x14)
    bmin = np.array(struct.unpack_from("<3f", data, h + 0x20), np.float32)
    bmax = np.array(struct.unpack_from("<3f", data, h + 0x30), np.float32)
    matrix = np.array(struct.unpack_from("<16f", data, h + 0x40), np.float32).reshape(4, 4)
    name = _cstr(data, h + 0xA4, 0x3C) or f"part_{phash:08x}"
    textures = []
    for c in _find(sub, 0x00134012):
        textures += [struct.unpack_from("<I", data, c[1] + i * 8)[0] for i in range(c[2] // 8)]
    shaders = []
    for c in _find(sub, 0x00134013):
        shaders += [struct.unpack_from("<I", data, c[1] + i * 8)[0] for i in range(c[2] // 8)]
    mesh = _find(sub, 0x80134100)
    warnings: list[str] = []
    empty = (
        np.zeros((0, 3), np.float32),
        np.zeros((0, 3), np.float32),
        np.zeros((0, 2), np.float32),
        np.zeros((0, 4), np.float32),
    )
    if not mesh:
        return Part(name, phash, tris, nverts, (bmin, bmax), matrix, textures, shaders, *empty, [])
    msub = chunks(data, mesh[0][1], mesh[0][1] + mesh[0][2])
    c800, c801, c802 = (_find(msub, i) for i in (0x00134800, 0x00134801, 0x00134802))
    if not (c800 and c801 and c802):
        warnings.append(f"{name}: incomplete mesh chunk")
        return Part(
            name, phash, tris, nverts, (bmin, bmax), matrix, textures, shaders, *empty, [], warnings
        )  # fmt: skip
    p = _skip_fill(data, c800[0][1], c800[0][1] + c800[0][2])
    _flags, _nstrips, _nverts, total, pos_off, nrm_off, clr_off, uv_off = struct.unpack_from(
        ">IHHIIIII", data, p
    )
    base = _skip_fill(data, c802[0][1], c802[0][1] + c802[0][2])
    end = c802[0][1] + c802[0][2]
    total = min(total, end - base)
    bounds = sorted([pos_off, nrm_off, clr_off, uv_off, total])

    def extent(o: int) -> int:
        later = [b for b in bounds if b > o]
        return (later[0] if later else total) - o

    p = _skip_fill(data, c801[0][1], c801[0][1] + c801[0][2])
    rows_end = c801[0][1] + c801[0][2]
    rows = []
    while p + 16 <= rows_end:
        rows.append(struct.unpack_from(">IHHBBBBHH", data, p))
        p += 16
    # attribute set 0x01 (VAT 1) parts - track sections, sky domes - keep float positions;
    # the s16 sets carry no shift, the bounding box gives it (1/4096 for cars)
    float_pos = any((r[7] & 0xFF) == 0x01 for r in rows if r[3] >= 3 and r[8])
    npos = extent(pos_off) // (12 if float_pos else 6)
    nnrm = extent(nrm_off) // 4
    nuv = extent(uv_off) // 4
    nclr = extent(clr_off) // 4
    if float_pos:
        positions = np.frombuffer(data, ">f4", npos * 3, base + pos_off).reshape(-1, 3)
        positions = np.nan_to_num(positions.astype(np.float32))
    else:
        raw_pos = np.frombuffer(data, ">i2", npos * 3, base + pos_off).reshape(-1, 3)
        positions = raw_pos.astype(np.float32) * _pos_scale(raw_pos, (bmin, bmax))
    normals = (
        np.frombuffer(data, "i1", nnrm * 4, base + nrm_off).reshape(-1, 4)[:, :3].astype(np.float32)
        / 64.0
    )
    uvs = np.frombuffer(data, ">i2", nuv * 2, base + uv_off).reshape(-1, 2)
    uvs = uvs.astype(np.float32) / 4096.0
    colors = np.frombuffer(data, "u1", nclr * 4, base + clr_off).reshape(-1, 4)
    colors = colors.astype(np.float32) / 255.0
    limits = {"pos": npos, "nrm": nnrm, "uv": nuv, "clr": nclr}

    strips = []
    for s_off, _s_size, _s_flags, count, _group, tex, shader, fmt, nbytes in rows:
        if count < 3 or nbytes == 0 or base + s_off + nbytes > end:
            continue
        try:
            verts = _read_strip(data, base + s_off, count, fmt, nbytes)
        except ValueError as e:
            warnings.append(f"{name}: {e}")
            continue
        bad = [v for v in verts if any(v[a] >= limits[a] for a in limits if a in v)]
        if bad:
            warnings.append(f"{name}: strip fmt {fmt:04x} indexes past its arrays")
            continue
        strips.append(Strip(tex, shader, verts))
    return Part(
        name, phash, tris, nverts, (bmin, bmax), matrix, textures, shaders,
        positions, normals, uvs, colors, strips, warnings,
    )  # fmt: skip


def parse_geometry(data: bytes, start: int = 0, end: int | None = None) -> list[Geometry]:
    end = len(data) if end is None else end
    out = []
    for cid, off, size in chunks(data, start, end):
        if cid != ID_GEOMETRY:
            continue
        sub = chunks(data, off, off + size)
        source = ""
        info = _find(sub, 0x80134001)
        if info:
            hdr = _find(chunks(data, info[0][1], info[0][1] + info[0][2]), 0x00134002)
            if hdr:
                source = _cstr(data, hdr[0][1] + 0x10, 0x38)
        geo = Geometry(source, [])
        for c in _find(sub, 0x80134010):
            try:
                part = _parse_part(data, c[1], c[2])
            except (ValueError, struct.error) as e:
                geo.warnings.append(f"part at {c[1]:x}: {e}")
                continue
            if part is not None:
                geo.parts.append(part)
                geo.warnings += part.warnings
        out.append(geo)
    return out


# ---------------------------------------------------------------- Scene building


_UP = np.array([0.0, 0.0, 1.0], np.float32)
_WHITE = np.array([1.0, 1.0, 1.0, 1.0], np.float32)


class _Bucket:
    """Vertex/index accumulator for one material."""

    def __init__(self) -> None:
        self.vindex: dict = {}
        self.pos: list = []
        self.nrm: list = []
        self.uv: list = []
        self.clr: list = []
        self.j: list = []
        self.idx: list = []
        self.has_nrm = False
        self.has_clr = False


def _lod(name: str) -> str:
    """Trailing _A/_B/_C/_D is the level of detail; unsuffixed parts count as A."""
    if len(name) > 2 and name[-2] == "_" and name[-1] in "ABCD":
        return name[-1]
    return "A"


def _strip_triangles(verts: list[dict]) -> list[tuple]:
    """Triangles of one strip. Strips are several sub-strips glued with degenerate
    triangles, and every sub-strip starts with the even winding again (checked against
    the vertex normals: 21105 agree / 25 disagree on the RX7, versus 77% with a running
    parity)."""
    tris = []
    base = 0
    last_degenerate = -2
    for i in range(len(verts) - 2):
        a, b, c = verts[i], verts[i + 1], verts[i + 2]
        if a["pos"] == b["pos"] or b["pos"] == c["pos"] or a["pos"] == c["pos"]:
            last_degenerate = i
            continue
        if last_degenerate == i - 1:
            base = i
        tris.append((a, c, b) if (i - base) & 1 else (a, b, c))
    return tris


def build_scenes(
    geos: list[Geometry],
    name: str,
    lookup,
    *,
    lods: str = "ABCD",
) -> list[Scene]:
    """One Scene per LOD letter: parts become joints (rigid), strips become primitives
    keyed by texture. `lookup(hash)` -> (texture name, RGBA) or None."""
    parts = [(g, p) for g in geos for p in g.parts]
    scenes = []
    for lod in lods:
        sel = [(g, p) for g, p in parts if _lod(p.name) == lod]
        if not sel:
            continue
        scene = Scene(name=f"{name}_{lod}" if lod != "A" else name)
        for g in geos:
            scene.warnings += g.warnings
        scene.extras["source"] = geos[0].source
        scene.joints.append(Joint("root", None, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1)))
        mat_index: dict[str, int] = {}
        buckets: dict[int, dict] = {}
        for _g, part in sel:
            if not part.strips:
                continue
            ji = len(scene.joints)
            m = part.matrix
            t = tuple(float(x) for x in m[3, :3])
            scene.joints.append(Joint(part.name, 0, t, (0, 0, 0, 1), (1, 1, 1)))
            rot = m[:3, :3].astype(np.float32)
            for s in part.strips:
                thash = part.textures[s.texture] if s.texture < len(part.textures) else 0
                tex = lookup(thash) if thash else None
                key = tex[0] if tex else f"tex_{thash:08x}"
                if key not in mat_index:
                    mat_index[key] = len(scene.materials)
                    scene.materials.append(MaterialDef(name=key, texture=key if tex else None))
                    if tex:
                        scene.textures[key] = tex[1]
                mi = mat_index[key]
                b = buckets.setdefault(mi, _Bucket())
                for tri in _strip_triangles(s.verts):
                    for v in tri:
                        vk = (ji, v["pos"], v.get("nrm"), v.get("clr"), v["uv"])
                        vi = b.vindex.get(vk)
                        if vi is None:
                            vi = len(b.pos)
                            b.vindex[vk] = vi
                            b.pos.append(part.positions[v["pos"]] @ rot)
                            if "nrm" in v:
                                b.nrm.append(part.normals[v["nrm"]] @ rot)
                                b.has_nrm = True
                            else:
                                b.nrm.append(_UP)
                            if "clr" in v:
                                b.clr.append(part.colors[v["clr"]])
                                b.has_clr = True
                            else:
                                b.clr.append(_WHITE)
                            b.uv.append(part.uvs[v["uv"]])
                            b.j.append(ji)
                        b.idx.append(vi)
        for mi, b in sorted(buckets.items()):
            n = len(b.pos)
            if n == 0 or not b.idx:
                continue
            joints = np.zeros((n, 4), np.uint16)
            joints[:, 0] = b.j
            weights = np.zeros((n, 4), np.float32)
            weights[:, 0] = 1.0
            scene.primitives.append(
                Primitive(
                    material=mi,
                    positions=np.array(b.pos, np.float32),
                    indices=np.array(b.idx, np.uint32),
                    normals=np.array(b.nrm, np.float32) if b.has_nrm else None,
                    uvs=np.array(b.uv, np.float32),
                    colors=np.array(b.clr, np.float32) if b.has_clr else None,
                    joints=joints,
                    weights=weights,
                )
            )
        if scene.primitives:
            scenes.append(scene)
    return scenes
