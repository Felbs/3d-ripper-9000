"""Truevision ``TGA`` images, shipped loose on Ubisoft's UE2 GameCube discs - Splinter
Cell Chaos Theory / Double Agent carry hundreds of ``*.tga`` loading screens and menu
plates (``screens/<lang>/*_loading*.tga``, ``SaveLoadScreens/*.tga``).  Before this
decoder existed nothing claimed them, so the ``gx`` fallback scanned their pixel data
for display lists and shipped 51 noise meshes per disc (the GCJE41 quality-audit
finding); a loading screen is a picture, not a model.

The classic 18-byte header, little-endian::

    +0   u8  id_length          bytes of free-form id after the header
    +1   u8  colormap_type      0 none, 1 present
    +2   u8  image_type         1/2/3 uncompressed cmap/truecolor/gray, 9/10/11 the RLE twins
    +3   u16 cmap_first | u16 cmap_length | u8 cmap_entry_bits (15/16/24/32)
    +8   u16 x_origin | u16 y_origin
    +12  u16 width | u16 height
    +16  u8  bits_per_pixel     8 (cmap/gray), 15/16 (ARGB1555), 24, 32
    +17  u8  descriptor         bit5 = top-down rows; bits 6-7 (interleave) always 0

then the id, the colormap (entries packed like pixels), and the rows - bottom-up unless
descriptor bit 5.  16-bit is ARGB1555; 24/32-bit are BGR(A).  RLE packets are a count
byte (bit7 = run) followed by one pixel (run) or ``count+1`` pixels (raw).  A footer
(``TRUEVISION-XFILE.``) may trail the pixels; it is ignored.

TGA has **no magic number**, so ``is_tga`` is deliberately strict - a consistent header
alone (all Chaos Theory screens: type 1, 256 x 24-bit palette, 8 bpp, 640x448) - and the
plugin additionally requires the ``.tga`` file name.  Kashmir's GameCube-repacked
".tga" pictures (``RPMOC3S`` tag at +1) fail the colormap_type check here and keep
their own reader.
"""

from __future__ import annotations

import struct

import numpy as np

HEADER = 18
MAX_DIM = 4096
UNCOMPRESSED = (1, 2, 3)
RLE = (9, 10, 11)
CMAP_BITS = (15, 16, 24, 32)


def is_tga(head: bytes, size: int | None = None) -> bool:
    if len(head) < HEADER:
        return False
    cmap_type, image_type = head[1], head[2]
    cmap_length, cmap_bits = struct.unpack_from("<H", head, 5)[0], head[7]
    width, height = struct.unpack_from("<2H", head, 12)
    bits, descriptor = head[16], head[17]
    if image_type not in UNCOMPRESSED + RLE or descriptor & 0xC0:
        return False
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return False
    if image_type in (1, 9):  # color-mapped: a palette and 8-bit indices
        if cmap_type != 1 or bits != 8:
            return False
        if not (0 < cmap_length <= 256 and cmap_bits in CMAP_BITS):
            return False
    elif image_type in (2, 10):  # truecolor
        if cmap_type != 0 or bits not in (15, 16, 24, 32):
            return False
    else:  # grayscale
        if cmap_type != 0 or bits != 8:
            return False
    if size is not None and image_type in UNCOMPRESSED:
        need = HEADER + head[0] + cmap_length * ((cmap_bits + 7) // 8 if cmap_type else 0)
        if need + width * height * ((bits + 7) // 8) > size:
            return False
    return True


def _rle(data: bytes, at: int, count: int, step: int) -> bytes | None:
    """Un-RLE ``count`` pixels of ``step`` bytes each starting at ``at``."""
    out = bytearray()
    want = count * step
    n = len(data)
    while len(out) < want:
        if at >= n:
            return None
        packet = data[at]
        at += 1
        repeat = (packet & 0x7F) + 1
        if packet & 0x80:  # run: one pixel, repeated
            if at + step > n:
                return None
            out += data[at : at + step] * repeat
            at += step
        else:  # raw: repeat pixels verbatim
            if at + repeat * step > n:
                return None
            out += data[at : at + repeat * step]
            at += repeat * step
    return bytes(out[:want])


def _rgba(px: np.ndarray, bits: int) -> np.ndarray:
    """(N, step) raw pixels -> (N, 4) RGBA."""
    out = np.empty((len(px), 4), np.uint8)
    if bits in (15, 16):  # ARGB1555, little-endian
        v = px[:, 0].astype(np.uint16) | (px[:, 1].astype(np.uint16) << 8)
        out[:, 0] = ((v >> 10) & 0x1F) * 255 // 31
        out[:, 1] = ((v >> 5) & 0x1F) * 255 // 31
        out[:, 2] = (v & 0x1F) * 255 // 31
        out[:, 3] = ((v >> 15) * 255).astype(np.uint8) if bits == 16 else 255
        if bits == 16 and not out[:, 3].any():
            # a zeroed attribute bit throughout means "no alpha", not "all invisible"
            out[:, 3] = 255
    else:  # BGR(A)
        out[:, 0], out[:, 1], out[:, 2] = px[:, 2], px[:, 1], px[:, 0]
        out[:, 3] = px[:, 3] if px.shape[1] == 4 else 255
    return out


def decode(data: bytes) -> np.ndarray | None:
    """RGBA (height, width, 4), top row first."""
    if not is_tga(data[:HEADER], len(data)):
        return None
    cmap_type, image_type = data[1], data[2]
    cmap_length, cmap_bits = struct.unpack_from("<H", data, 5)[0], data[7]
    width, height = struct.unpack_from("<2H", data, 12)
    bits, descriptor = data[16], data[17]

    at = HEADER + data[0]  # skip the id
    palette = None
    if cmap_type:
        entry = (cmap_bits + 7) // 8
        table = data[at : at + cmap_length * entry]
        if len(table) < cmap_length * entry:
            return None
        palette = _rgba(np.frombuffer(table, np.uint8).reshape(cmap_length, entry), cmap_bits)
        at += cmap_length * entry

    step = (bits + 7) // 8
    if image_type in RLE:
        raw = _rle(data, at, width * height, step)
        if raw is None:
            return None
    else:
        raw = data[at : at + width * height * step]
        if len(raw) < width * height * step:
            return None
    px = np.frombuffer(raw, np.uint8).reshape(width * height, step)

    if image_type in (1, 9):
        index = px[:, 0].astype(np.int32)
        if index.max() >= len(palette):
            return None
        rgba = palette[index]
    elif image_type in (3, 11):
        rgba = np.empty((width * height, 4), np.uint8)
        rgba[:, 0] = rgba[:, 1] = rgba[:, 2] = px[:, 0]
        rgba[:, 3] = 255
    else:
        rgba = _rgba(px, bits)
    out = rgba.reshape(height, width, 4)
    return out if descriptor & 0x20 else out[::-1]
