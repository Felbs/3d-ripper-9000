"""BTI texture header (standalone .bti files and TEX1 entries inside BMD/BDL).

Header (0x20 bytes, big-endian; offsets are relative to the header start):
  0x00 u8  format          0x01 u8  alpha setting     0x02 u16 width
  0x04 u16 height          0x06 u8  wrap S            0x07 u8  wrap T
  0x08 u8  palettes on     0x09 u8  palette format    0x0A u16 palette count
  0x0C u32 palette offset  0x10 u32 (border color / unused)
  0x14 u8  min filter      0x15 u8  mag filter        0x16 u8  min LOD (x8)
  0x17 u8  max LOD (x8)    0x18 u8  mip count         0x19 u8  pad
  0x1A u16 LOD bias        0x1C u32 image data offset
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture

HEADER_SIZE = 0x20
WRAP_MODES = {0: "clamp", 1: "repeat", 2: "mirror"}


@dataclass
class BtiTexture:
    name: str
    fmt: int
    width: int
    height: int
    wrap_s: int
    wrap_t: int
    palette_fmt: int | None
    palette: bytes | None  # raw palette bytes
    palette_count: int
    mip_count: int
    min_filter: int
    mag_filter: int
    data: bytes  # raw image data (all mips)

    @property
    def fmt_name(self) -> str:
        return gx_texture.FORMAT_NAMES.get(self.fmt, f"fmt{self.fmt}")

    @property
    def has_alpha(self) -> bool:
        return gx_texture.has_alpha(self.fmt, self.palette_fmt)

    def decode(self, level: int = 0) -> np.ndarray:
        pal = None
        if self.fmt in (8, 9, 10):
            if not self.palette or self.palette_fmt is None:
                raise ValueError("palettized texture without palette")
            pal = gx_texture.decode_palette(self.palette_fmt, self.palette, self.palette_count)
        w, h, off = self.width, self.height, 0
        for _ in range(level):
            off += gx_texture.encoded_size(self.fmt, w, h)
            w, h = max(1, w // 2), max(1, h // 2)
        return gx_texture.decode(self.fmt, w, h, self.data[off:], pal)


def parse(blob: bytes, header_offset: int = 0, name: str = "") -> BtiTexture:
    """Parse a BTI header at `header_offset` inside `blob` (image/palette offsets
    are relative to the header). For a standalone .bti file, header_offset=0."""
    h = blob[header_offset : header_offset + HEADER_SIZE]
    if len(h) < HEADER_SIZE:
        raise ValueError("BTI header truncated")
    fmt, _alpha, width, height, wrap_s, wrap_t, pal_on, pal_fmt, pal_count, pal_off = (
        struct.unpack_from(">BBHHBBBBHI", h, 0)
    )
    min_f, mag_f, _minlod, _maxlod, mips, _pad, _bias, data_off = struct.unpack_from(
        ">BBBBBBHI", h, 0x14
    )
    mips = max(1, mips)
    total = 0
    w, hh = width, height
    for _ in range(mips):
        total += gx_texture.encoded_size(fmt, w, hh) if fmt in gx_texture.TILE_DIMS else 0
        w, hh = max(1, w // 2), max(1, hh // 2)
    data = blob[header_offset + data_off : header_offset + data_off + total]
    palette = None
    if fmt in (8, 9, 10):
        palette = blob[header_offset + pal_off : header_offset + pal_off + pal_count * 2]
    return BtiTexture(
        name=name,
        fmt=fmt,
        width=width,
        height=height,
        wrap_s=wrap_s,
        wrap_t=wrap_t,
        palette_fmt=pal_fmt if fmt in (8, 9, 10) else None,
        palette=palette,
        palette_count=pal_count,
        mip_count=mips,
        min_filter=min_f,
        mag_filter=mag_f,
        data=data,
    )
