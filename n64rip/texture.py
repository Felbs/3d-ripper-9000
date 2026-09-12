"""N64 texture decode: the RDP's eight formats to RGBA8.

The N64 stores texels linearly - unlike the GameCube's 4x4/8x8 tiles, so gcrip's
``gx_texture`` does not transfer - but the pixel formats themselves are close cousins.
Formats are a (fmt, size) pair rather than a single code:

    fmt 0 RGBA   size 2 -> RGBA5551 (16bpp)   size 3 -> RGBA8888 (32bpp)
    fmt 2 CI     size 0 -> CI4 + TLUT         size 1 -> CI8 + TLUT
    fmt 3 IA     size 0 -> IA4 (3+1 bits)     size 1 -> IA8 (4+4)   size 2 -> IA16 (8+8)
    fmt 4 I      size 0 -> I4                 size 1 -> I8

Palettes (TLUTs) are 16-bit entries in the same RGBA5551 layout, 16 entries for CI4 (selected
by the tile's ``palette`` field, so one 256-entry TLUT serves 16 different CI4 textures) and
256 for CI8.
"""

from __future__ import annotations

import numpy as np

FMT_RGBA = 0
FMT_YUV = 1
FMT_CI = 2
FMT_IA = 3
FMT_I = 4

SIZE_4 = 0
SIZE_8 = 1
SIZE_16 = 2
SIZE_32 = 3

_NAMES = {
    (FMT_RGBA, SIZE_16): "rgba16",
    (FMT_RGBA, SIZE_32): "rgba32",
    (FMT_CI, SIZE_4): "ci4",
    (FMT_CI, SIZE_8): "ci8",
    (FMT_IA, SIZE_4): "ia4",
    (FMT_IA, SIZE_8): "ia8",
    (FMT_IA, SIZE_16): "ia16",
    (FMT_I, SIZE_4): "i4",
    (FMT_I, SIZE_8): "i8",
}


class TextureError(Exception):
    pass


def format_name(fmt: int, size: int) -> str:
    return _NAMES.get((fmt, size), f"fmt{fmt}_size{size}")


def bits_per_texel(fmt: int, size: int) -> int:
    return {SIZE_4: 4, SIZE_8: 8, SIZE_16: 16, SIZE_32: 32}[size]


def _rgba5551(words: np.ndarray) -> np.ndarray:
    r = ((words >> 11) & 0x1F).astype(np.uint16) * 255 // 31
    g = ((words >> 6) & 0x1F).astype(np.uint16) * 255 // 31
    b = ((words >> 1) & 0x1F).astype(np.uint16) * 255 // 31
    a = np.where(words & 1, 255, 0).astype(np.uint16)
    return np.stack([r, g, b, a], axis=-1).astype(np.uint8)


def _nibbles(data: bytes, count: int) -> np.ndarray:
    """*count* 4-bit values, high nibble first."""
    need = (count + 1) // 2
    raw = np.frombuffer(bytes(data[:need]).ljust(need, b"\0"), np.uint8)
    return np.stack([raw >> 4, raw & 0x0F], axis=-1).reshape(-1)[:count]


def decode_tlut(data: bytes, entries: int) -> np.ndarray:
    """A TLUT to (entries, 4) RGBA8."""
    need = entries * 2
    raw = np.frombuffer(bytes(data[:need]).ljust(need, b"\0"), ">u2", entries)
    return _rgba5551(raw)


def decode(
    fmt: int,
    size: int,
    width: int,
    height: int,
    data: bytes,
    tlut: np.ndarray | None = None,
    palette: int = 0,
) -> np.ndarray:
    """Decode one texture to (height, width, 4) uint8.

    *tlut* is a decoded palette from :func:`decode_tlut`; for CI4 the tile's *palette* index
    selects a 16-entry window into it, which is how one loaded TLUT serves several textures.
    """
    if width <= 0 or height <= 0:
        raise TextureError(f"implausible size {width}x{height}")
    n = width * height
    bpp = bits_per_texel(fmt, size)
    need = (n * bpp + 7) // 8
    buf = bytes(data[:need]).ljust(need, b"\0")

    if fmt == FMT_RGBA and size == SIZE_16:
        words = np.frombuffer(buf, ">u2", n)
        return _rgba5551(words).reshape(height, width, 4)
    if fmt == FMT_RGBA and size == SIZE_32:
        return np.frombuffer(buf, np.uint8, n * 4).reshape(height, width, 4).copy()
    if fmt == FMT_CI:
        if tlut is None:
            raise TextureError("CI texture without a palette")
        if size == SIZE_4:
            idx = _nibbles(buf, n).astype(np.int32)
            window = tlut[palette * 16 : palette * 16 + 16]
            if len(window) < 16:
                window = np.resize(tlut, (16, 4))
            lut = window
        else:
            idx = np.frombuffer(buf, np.uint8, n).astype(np.int32)
            lut = tlut
        idx = np.clip(idx, 0, len(lut) - 1)
        return lut[idx].reshape(height, width, 4)
    if fmt == FMT_IA and size == SIZE_4:
        v = _nibbles(buf, n).astype(np.uint16)
        i = (v >> 1) * 255 // 7
        a = np.where(v & 1, 255, 0)
        return np.stack([i, i, i, a], -1).astype(np.uint8).reshape(height, width, 4)
    if fmt == FMT_IA and size == SIZE_8:
        raw = np.frombuffer(buf, np.uint8, n).astype(np.uint16)
        i = (raw >> 4) * 255 // 15
        a = (raw & 0x0F) * 255 // 15
        return np.stack([i, i, i, a], -1).astype(np.uint8).reshape(height, width, 4)
    if fmt == FMT_IA and size == SIZE_16:
        raw = np.frombuffer(buf, np.uint8, n * 2).reshape(-1, 2)
        i, a = raw[:, 0], raw[:, 1]
        return np.stack([i, i, i, a], -1).astype(np.uint8).reshape(height, width, 4)
    if fmt == FMT_I and size == SIZE_4:
        v = _nibbles(buf, n).astype(np.uint16) * 255 // 15
        return np.stack([v, v, v, v], -1).astype(np.uint8).reshape(height, width, 4)
    if fmt == FMT_I and size == SIZE_8:
        v = np.frombuffer(buf, np.uint8, n)
        return np.stack([v, v, v, v], -1).reshape(height, width, 4)
    raise TextureError(f"unsupported texture format {format_name(fmt, size)}")


def opaque(rgba: np.ndarray) -> np.ndarray:
    """A COPY of *rgba* with the alpha channel filled, for a surface the RDP drew without
    ever reading it.  A copy, never in place: the same decoded array is shared between
    materials, and one of them may be drawn under a mode that does read it.

    Note for anyone histogramming alpha: :func:`_rgba5551` computes ``a = 255 if bit0 else 0``,
    so an RGBA16 texture *cannot* have more than two alpha levels by construction - a count
    of "binary" RGBA16 textures measures the decoder, not the ROM.  And "mixed RGBA16 means
    cut-out" is false: of 153 mixed actor RGBA16 textures, 2 (adult Zelda, mats 34 and 36)
    are drawn under a mode that never tests alpha, and that shortcut would put holes in her.
    """
    out = rgba.copy()
    out[:, :, 3] = 255
    return out
