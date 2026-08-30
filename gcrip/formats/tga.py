"""Truevision TGA images, as shipped loose beside RenderWare models (MLB SlugFest, Outlaw
Golf, ...).

Header: ``u8 id length | u8 colour-map type | u8 image type | u16 map first | u16 map length |
u8 map entry bits | u16 x | u16 y | u16 width | u16 height | u8 bits | u8 descriptor``, then
the id field, the colour map and the pixels.  Image types 1 / 9 are colour-mapped, 2 / 10
true-colour and 3 / 11 greyscale; the 8+ variants are RLE (``u8 count | pixel`` runs, the top
bit marking a repeat).  Rows run bottom-up unless bit 5 of the descriptor is set.
"""

from __future__ import annotations

import struct

import numpy as np

HEADER = 18


class TgaError(ValueError):
    pass


def is_tga(data: bytes) -> bool:
    if len(data) < HEADER:
        return False
    cmap, kind, bits = data[1], data[2], data[16]
    return cmap in (0, 1) and kind in (1, 2, 3, 9, 10, 11) and bits in (8, 15, 16, 24, 32)


def _expand(px: np.ndarray, bits: int) -> np.ndarray:
    """(N, bytes) pixels -> (N, 4) RGBA."""
    n = len(px)
    out = np.empty((n, 4), np.uint8)
    if bits == 32:
        out[:, 0], out[:, 1], out[:, 2], out[:, 3] = px[:, 2], px[:, 1], px[:, 0], px[:, 3]
    elif bits == 24:
        out[:, 0], out[:, 1], out[:, 2] = px[:, 2], px[:, 1], px[:, 0]
        out[:, 3] = 255
    elif bits in (15, 16):
        v = px[:, 0].astype(np.uint16) | (px[:, 1].astype(np.uint16) << 8)
        r = ((v >> 10) & 31) * 255 // 31
        g = ((v >> 5) & 31) * 255 // 31
        b = (v & 31) * 255 // 31
        out[:, 0], out[:, 1], out[:, 2] = r, g, b
        out[:, 3] = np.where((v & 0x8000) != 0, 255, 255 if bits == 15 else 0).astype(np.uint8)
    else:  # 8-bit grey
        out[:, 0] = out[:, 1] = out[:, 2] = px[:, 0]
        out[:, 3] = 255
    return out


def _rle(data: bytes, start: int, count: int, stride: int) -> np.ndarray:
    out = np.empty((count, stride), np.uint8)
    p = start
    n = 0
    while n < count and p < len(data):
        packet = data[p]
        p += 1
        run = (packet & 0x7F) + 1
        run = min(run, count - n)
        if packet & 0x80:
            if p + stride > len(data):
                break
            out[n : n + run] = np.frombuffer(data, np.uint8, stride, p)
            p += stride
        else:
            if p + run * stride > len(data):
                break
            out[n : n + run] = np.frombuffer(data, np.uint8, run * stride, p).reshape(run, stride)
            p += run * stride
        n += run
    if n < count:
        out[n:] = 0
    return out


def decode(data: bytes) -> np.ndarray:
    """RGBA (h, w, 4) uint8."""
    if not is_tga(data):
        raise TgaError("not a TGA image")
    idlen, cmap_type, kind = data[0], data[1], data[2]
    map_first, map_len, map_bits = struct.unpack_from("<HHB", data, 3)
    width, height, bits, desc = struct.unpack_from("<HHBB", data, 12)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise TgaError("implausible size")
    p = HEADER + idlen
    palette = None
    if cmap_type and map_len:
        entry = max(map_bits, 8) // 8
        have = min(map_len * entry, max(len(data) - p, 0)) // entry * entry
        raw = np.frombuffer(data, np.uint8, have, p)
        p += map_len * entry
        if have:
            palette = _expand(raw.reshape(-1, entry), map_bits)
    stride = max(bits, 8) // 8
    count = width * height
    if kind >= 9:
        px = _rle(data, p, count, stride)
    else:
        have = min(count * stride, max(len(data) - p, 0))
        px = np.zeros((count, stride), np.uint8)
        px.reshape(-1)[:have] = np.frombuffer(data, np.uint8, have, p)
    if palette is not None and kind in (1, 9):
        idx = px[:, 0].astype(np.int32) - map_first
        np.clip(idx, 0, len(palette) - 1, out=idx)
        rgba = palette[idx]
    else:
        rgba = _expand(px, bits)
    img = rgba.reshape(height, width, 4)
    if not desc & 0x20:  # origin at the bottom left
        img = img[::-1]
    return np.ascontiguousarray(img)
