"""PVR - Dreamcast (PowerVR CLX2) textures, and PVM texture packs.

    ["GBIX" u32 size, u32 global_index, pad]  (optional)
    "PVRT" u32 data_size, u8 pixel_format, u8 data_format, u16 0, u16 width, u16 height, data

pixel formats: 0 ARGB1555, 1 RGB565, 2 ARGB4444, 3 YUV422, 4 BUMP (SR), 5 4-bit palette,
6 8-bit palette. data formats: 0x01 twiddled, 0x02 twiddled + mipmaps, 0x03 VQ, 0x04 VQ +
mipmaps, 0x05/0x06 4-bit palette (+mm), 0x07/0x08 8-bit palette (+mm), 0x09 rectangle,
0x0B rectangle stride, 0x0D twiddled rectangle, 0x10 small VQ, 0x11 small VQ + mipmaps.

Twiddling is Morton order with y in the even bits and x in the odd bits, applied per
square tile of min(width, height). With mipmaps the largest level comes last, after one
texel of padding and the 1x1, 2x2 ... levels. VQ: a 256-entry codebook of 2x2 texel blocks
(each block's 4 texels in twiddled order), then one index byte per block in twiddled order
over the half-size grid; "small VQ" shrinks the codebook with the texture size.

PVM ("PVMH"): u32 header_size, u16 flags (1 gbix, 2 names, 4 formats, 8 dimensions),
u16 count, per entry u16 id [+u32 gbix] [+28-byte name] [+u16 format] [+u16 dims]; the
textures follow the header back to back, each a GBIX/PVRT.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

PIXEL_NAMES = {
    0: "ARGB1555", 1: "RGB565", 2: "ARGB4444", 3: "YUV422", 4: "BUMP", 5: "PAL4", 6: "PAL8"
}
DATA_NAMES = {
    0x01: "twiddled", 0x02: "twiddled+mm", 0x03: "vq", 0x04: "vq+mm", 0x05: "pal4",
    0x06: "pal4+mm", 0x07: "pal8", 0x08: "pal8+mm", 0x09: "rect", 0x0B: "rect-stride",
    0x0D: "twiddled-rect", 0x10: "small-vq", 0x11: "small-vq+mm", 0x12: "twiddled+mm-alt",
}


@dataclass
class Pvr:
    width: int
    height: int
    pixel_format: int
    data_format: int
    data: bytes
    gbix: int | None = None

    @property
    def fmt_name(self) -> str:
        return f"{PIXEL_NAMES.get(self.pixel_format, self.pixel_format)}/" + DATA_NAMES.get(
            self.data_format, hex(self.data_format)
        )

    def decode(self) -> np.ndarray:
        return _decode(self)


def is_pvr(data: bytes) -> bool:
    return data[:4] in (b"GBIX", b"PVRT")


def parse(data: bytes) -> Pvr:
    p = 0
    gbix = None
    if data[:4] == b"GBIX":
        size = struct.unpack_from("<I", data, 4)[0]
        if size >= 4:
            gbix = struct.unpack_from("<I", data, 8)[0]
        p = 8 + size
    if data[p : p + 4] != b"PVRT":
        raise ValueError("not a PVR texture")
    size, pf, df, _z, w, h = struct.unpack_from("<IBBHHH", data, p + 4)
    body = data[p + 16 : p + 8 + size]
    return Pvr(w, h, pf, df, body, gbix)


def pvr_size(data: bytes) -> int:
    """Total bytes of the GBIX+PVRT record starting at data[0] (to step through a PVM)."""
    p = 0
    if data[:4] == b"GBIX":
        p = 8 + struct.unpack_from("<I", data, 4)[0]
    return p + 8 + struct.unpack_from("<I", data, p + 4)[0]


# -- pixel conversion ---------------------------------------------------------------------


def _to_rgba(words: np.ndarray, pf: int) -> np.ndarray:
    """(N,) uint16 -> (N,4) uint8 RGBA."""
    w = words.astype(np.uint32)
    out = np.empty((len(w), 4), np.uint8)
    if pf == 0:  # ARGB1555
        out[:, 0] = ((w >> 10) & 31) * 255 // 31
        out[:, 1] = ((w >> 5) & 31) * 255 // 31
        out[:, 2] = (w & 31) * 255 // 31
        out[:, 3] = ((w >> 15) & 1) * 255
    elif pf == 1:  # RGB565
        out[:, 0] = ((w >> 11) & 31) * 255 // 31
        out[:, 1] = ((w >> 5) & 63) * 255 // 63
        out[:, 2] = (w & 31) * 255 // 31
        out[:, 3] = 255
    elif pf == 2:  # ARGB4444
        out[:, 0] = ((w >> 8) & 15) * 17
        out[:, 1] = ((w >> 4) & 15) * 17
        out[:, 2] = (w & 15) * 17
        out[:, 3] = ((w >> 12) & 15) * 17
    elif pf == 4:  # BUMP: S (byte 1) / R (byte 0) angles -> visualise as a normal map
        s = ((w >> 8) & 255).astype(np.float64) / 255 * (np.pi / 2)
        r = (w & 255).astype(np.float64) / 255 * (2 * np.pi)
        nx, ny, nz = np.cos(s) * np.cos(r), np.cos(s) * np.sin(r), np.sin(s)
        out[:, 0] = (nx * 127 + 128).astype(np.uint8)
        out[:, 1] = (ny * 127 + 128).astype(np.uint8)
        out[:, 2] = (nz * 127 + 128).astype(np.uint8)
        out[:, 3] = 255
    else:  # YUV422 handled separately; palettes: index as grey
        g = (w & 255).astype(np.uint8)
        out[:, 0] = out[:, 1] = out[:, 2] = g
        out[:, 3] = 255
    return out


def _yuv422(words: np.ndarray, w: int, h: int) -> np.ndarray:
    # pairs of 16-bit words: (Y0 << 8 | U), (Y1 << 8 | V)
    w0 = words[0::2].astype(np.int32)
    w1 = words[1::2].astype(np.int32)
    u = (w0 & 255) - 128
    y0 = w0 >> 8
    v = (w1 & 255) - 128
    y1 = w1 >> 8
    out = np.empty((len(words), 4), np.uint8)
    for k, y in ((0, y0), (1, y1)):
        r = np.clip(y + 1.402 * v, 0, 255)
        g = np.clip(y - 0.344 * u - 0.714 * v, 0, 255)
        b = np.clip(y + 1.772 * u, 0, 255)
        out[k::2, 0], out[k::2, 1], out[k::2, 2], out[k::2, 3] = r, g, b, 255
    return out


# -- twiddling ------------------------------------------------------------------------------


def _part1by1(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.uint32) & 0xFFFF
    v = (v | (v << 8)) & 0x00FF00FF
    v = (v | (v << 4)) & 0x0F0F0F0F
    v = (v | (v << 2)) & 0x33333333
    v = (v | (v << 1)) & 0x55555555
    return v


def twiddle_index(w: int, h: int) -> np.ndarray:
    """(h, w) array: for each (y, x) the index of that texel in twiddled storage."""
    side = min(w, h)
    ys, xs = np.mgrid[0:h, 0:w]
    tile_x, tile_y = xs // side, ys // side
    tx, ty = xs % side, ys % side
    within = _part1by1(ty) | (_part1by1(tx) << 1)
    tile = (tile_y * (w // side) + tile_x) * side * side
    return (tile + within).astype(np.int64)


def _mip_offset(w: int, h: int, bpp_bytes: float, df: int) -> int:
    """Byte offset of the largest level in a mipmapped image."""
    if df in (0x04, 0x11):  # VQ: one index byte per 2x2 block, minimum one byte per level
        off = 0
        s = 1
        while s < w:
            off += max(1, (s * s) // 4)
            s *= 2
        return off
    off = int(bpp_bytes)  # one texel of padding before the 1x1 level
    s = 1
    while s < w:
        off += int(s * s * bpp_bytes)
        s *= 2
    return off


def _small_vq_entries(w: int, mipmaps: bool) -> int:
    if mipmaps:
        return 16 if w <= 16 else 64 if w <= 32 else 128 if w <= 64 else 256
    return 16 if w <= 16 else 32 if w <= 32 else 128 if w <= 64 else 256


def _decode(t: Pvr) -> np.ndarray:
    w, h, pf, df, data = t.width, t.height, t.pixel_format, t.data_format, t.data
    if w == 0 or h == 0:
        raise ValueError("empty texture")
    if df in (0x03, 0x04, 0x10, 0x11):
        entries = 256 if df in (0x03, 0x04) else _small_vq_entries(w, df == 0x11)
        cb = np.frombuffer(data, dtype="<u2", count=entries * 4)
        idx_data = data[entries * 8 :]
        off = _mip_offset(w, h, 0.25, df) if df in (0x04, 0x11) else 0
        bw, bh = w // 2, h // 2
        idx = np.frombuffer(idx_data, dtype=np.uint8, count=bw * bh, offset=off)
        blocks = idx[twiddle_index(bw, bh).reshape(-1)].reshape(bh, bw).astype(np.int64)
        # each codebook entry: 4 texels in twiddled order: (x0,y0) (x0,y1) (x1,y0) (x1,y1)
        words = np.empty((h, w), np.uint16)
        words[0::2, 0::2] = cb[blocks * 4 + 0]
        words[1::2, 0::2] = cb[blocks * 4 + 1]
        words[0::2, 1::2] = cb[blocks * 4 + 2]
        words[1::2, 1::2] = cb[blocks * 4 + 3]
        flat = words.reshape(-1)
        rgba = _yuv422(flat, w, h) if pf == 3 else _to_rgba(flat, pf)
        return rgba.reshape(h, w, 4)
    if df in (0x05, 0x06, 0x07, 0x08):  # palettised: no palette in the file -> grey index
        bits = 4 if df in (0x05, 0x06) else 8
        off = _mip_offset(w, h, bits / 8, df) if df in (0x06, 0x08) else 0
        n = w * h
        if bits == 8:
            idx = np.frombuffer(data, dtype=np.uint8, count=n, offset=off).astype(np.uint16)
        else:
            packed = np.frombuffer(data, dtype=np.uint8, count=(n + 1) // 2, offset=off)
            idx = np.empty(n, np.uint16)
            idx[0::2] = packed[: (n + 1) // 2] & 15
            idx[1::2] = (packed[: n // 2] >> 4) & 15
            idx = idx * 17
        rgba = _to_rgba(idx, 99)[twiddle_index(w, h).reshape(-1)]
        return rgba.reshape(h, w, 4)
    # 16-bit texels
    mm = df in (0x02, 0x12)
    off = _mip_offset(w, h, 2, df) if mm else 0
    words = np.frombuffer(data, dtype="<u2", count=w * h, offset=off)
    if df in (0x09, 0x0B):
        flat = words
    else:
        flat = words[twiddle_index(w, h).reshape(-1)]
    rgba = _yuv422(flat, w, h) if pf == 3 else _to_rgba(flat, pf)
    return rgba.reshape(h, w, 4)


# -- PVM ----------------------------------------------------------------------------------


@dataclass
class PvmEntry:
    index: int
    id: int
    name: str
    offset: int
    size: int
    gbix: int | None = None


def is_pvm(data: bytes) -> bool:
    return data[:4] == b"PVMH"


def parse_pvm(data: bytes) -> list[PvmEntry]:
    if not is_pvm(data):
        raise ValueError("not a PVM")
    hsize = struct.unpack_from("<I", data, 4)[0]
    flags, count = struct.unpack_from("<HH", data, 8)
    p = 12
    entries = []
    for i in range(count):
        if p + 2 > len(data):
            break
        tid = struct.unpack_from("<H", data, p)[0]
        p += 2
        name = f"tex{i:03d}"
        gbix = None
        if flags & 2:
            name = data[p : p + 28].split(b"\x00", 1)[0].decode("ascii", "replace")
            p += 28
        if flags & 4:
            p += 2
        if flags & 8:
            p += 2
        if flags & 1:
            gbix = struct.unpack_from("<I", data, p)[0]
            p += 4
        entries.append(PvmEntry(i, tid, name, 0, 0, gbix))
    q = 8 + hsize
    for e in entries:
        q = _next_record(data, q)
        if q is None:
            break
        size = pvr_size(data[q : q + 32])
        e.offset, e.size = q, size
        q += size
    return [e for e in entries if e.size]


def _next_record(data: bytes, q: int) -> int | None:
    """Offset of the next GBIX/PVRT record at or after q (packers put MDLN and other
    blocks between the header and the textures)."""
    if q + 4 <= len(data) and data[q : q + 4] in (b"GBIX", b"PVRT"):
        return q
    a = data.find(b"GBIX", q)
    b = data.find(b"PVRT", q)
    cands = [x for x in (a, b) if x >= 0]
    return min(cands) if cands else None
