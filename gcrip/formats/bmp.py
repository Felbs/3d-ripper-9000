"""Windows ``BMP`` images, shipped loose on a dozen discs that produced nothing else -
Aggressive Inline, Cel Damage, Dave Mirra Freestyle BMX 2, WRECKLESS, the Fairly OddParents,
Namco Museum, X-Men, Crash Nitro Kart, BMX XXX, All-Star Baseball 2002.

An ordinary ``BITMAPFILEHEADER`` and ``BITMAPINFOHEADER``, little-endian::

    +0   char magic[2]  "BM"
    +2   u32 file size
    +10  u32 pixel offset
    +14  u32 info header size (40 for BITMAPINFOHEADER)
    +18  i32 width | i32 height     a negative height means the rows are top-down
    +28  u16 bits per pixel         4 or 8 (palette), 24 or 32
    +30  u32 compression            0 only; RLE is not used by any of these discs
    +46  u32 palette entries        0 means 1 << bits
    ...  the palette, BGRA a entry, then the rows, each padded to four bytes

Two discs pad themselves out with **8500x8500 and 7960x8000 BMPs** - ``VeryBigBitmap.bmp``,
``AnotherVeryBigBitmap.bmp``, ``Untitled-1.bmp`` - 216 MB and 191 MB apiece of filler that is
not art.  Decoding those costs 289 MB of RGBA each for nothing, so anything over
``MAX_DIM`` on a side is refused; the limit is the point of the check, not an accident of it.
"""

from __future__ import annotations

import struct

import numpy as np

HEADER = 14
INFO = 40
MAX_DIM = 4096  # above this it is disc padding, not art - see the module docstring
BITS = (4, 8, 24, 32)


def is_bmp(head: bytes) -> bool:
    if len(head) < HEADER + 20 or head[:2] != b"BM":
        return False
    info = struct.unpack_from("<I", head, HEADER)[0]
    bits, compression = struct.unpack_from("<H", head, 28)[0], struct.unpack_from("<I", head, 30)[0]
    return info >= INFO and bits in BITS and compression == 0


def decode(data: bytes) -> np.ndarray | None:
    """RGBA, top row first."""
    if not is_bmp(data[:64]):
        return None
    pixels_at = struct.unpack_from("<I", data, 10)[0]
    info = struct.unpack_from("<I", data, HEADER)[0]
    width, height = struct.unpack_from("<2i", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    used = struct.unpack_from("<I", data, 46)[0] if info >= INFO else 0
    top_down = height < 0
    height = abs(height)
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
        return None

    stride = ((width * bits + 31) // 32) * 4
    if pixels_at + stride * height > len(data):
        return None
    rows = np.frombuffer(data[pixels_at : pixels_at + stride * height], np.uint8)
    rows = rows.reshape(height, stride)

    out = np.empty((height, width, 4), np.uint8)
    if bits in (4, 8):
        count = used or (1 << bits)
        table = data[HEADER + info : HEADER + info + count * 4]
        if len(table) < count * 4:
            return None
        palette = np.frombuffer(table, np.uint8).reshape(count, 4)
        if bits == 4:  # two pixels a byte, high nibble first
            packed = rows[:, : (width + 1) // 2]
            index = np.empty((height, ((width + 1) // 2) * 2), np.int32)
            index[:, 0::2] = packed >> 4
            index[:, 1::2] = packed & 0xF
            index = index[:, :width]
        else:
            index = rows[:, :width].astype(np.int32)
        if index.max() >= count:
            return None
        out[..., 0] = palette[index, 2]
        out[..., 1] = palette[index, 1]
        out[..., 2] = palette[index, 0]
        out[..., 3] = 255
    else:
        step = bits // 8
        px = rows[:, : width * step].reshape(height, width, step)
        out[..., 0], out[..., 1], out[..., 2] = px[..., 2], px[..., 1], px[..., 0]
        out[..., 3] = px[..., 3] if step == 4 else 255
    return out if top_down else out[::-1]
