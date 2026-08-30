"""TPL texture palette files (Nintendo SDK format; magic 0x0020AF30).

Header: u32 magic, u32 image count, u32 image table offset.
Image table entry: u32 image header offset, u32 palette header offset (0 = none).
Image header: u16 height, u16 width, u32 format, u32 data offset, u32 wrapS,
  u32 wrapT, u32 min filter, u32 mag filter, f32 lod bias, u8 edge lod,
  u8 min lod, u8 max lod, u8 unpacked.
Palette header: u16 entry count, u8 unpacked, u8 pad, u32 format, u32 data offset.
Offsets are absolute within the file.
"""

from __future__ import annotations

import struct

from gcrip.formats import gx_texture
from gcrip.formats.bti import BtiTexture

MAGIC = b"\x00\x20\xaf\x30"


def parse(data: bytes, base: int = 0) -> list[BtiTexture]:
    """Textures in a TPL whose header starts at `base`.

    A TPL's internal offsets are relative to its own header, so an embedded one is read by
    passing the containing file as `data` and the header position as `base`; every offset is
    then resolved against `base`.  Mega Man X: Command Mission wraps one in a 32-byte header,
    putting the TPL at 0x20 of each `.arc`.  With ``base=0`` this is exactly the old behaviour.
    """
    if data[base : base + 4] != MAGIC:
        raise ValueError("not a TPL file")
    count, table_off = struct.unpack_from(">II", data, base + 4)
    out = []
    for i in range(count):
        img_off, pal_off = struct.unpack_from(">II", data, base + table_off + i * 8)
        img_off += base
        pal_off = pal_off + base if pal_off else 0
        height, width, fmt, data_off, wrap_s, wrap_t, min_f, mag_f = struct.unpack_from(
            ">HHIIIIII", data, img_off
        )
        _bias, _edge, _minlod, max_lod, _unpacked = struct.unpack_from(
            ">fBBBB", data, img_off + 0x18
        )
        mips = max(1, max_lod + 1)
        total = 0
        w, h = width, height
        for _ in range(mips):
            if fmt in gx_texture.TILE_DIMS:
                total += gx_texture.encoded_size(fmt, w, h)
            w, h = max(1, w // 2), max(1, h // 2)
        palette = None
        pal_fmt = None
        pal_count = 0
        if pal_off:
            pal_count, _unp, _pad, pal_fmt, pal_data_off = struct.unpack_from(
                ">HBBII", data, pal_off
            )
            pal_data_off += base
            palette = data[pal_data_off : pal_data_off + pal_count * 2]
        out.append(
            BtiTexture(
                name=f"image{i}",
                fmt=fmt,
                width=width,
                height=height,
                wrap_s=wrap_s,
                wrap_t=wrap_t,
                palette_fmt=pal_fmt,
                palette=palette,
                palette_count=pal_count,
                mip_count=mips,
                min_filter=min_f,
                mag_filter=mag_f,
                data=data[base + data_off : base + data_off + total],
            )
        )
    return out
