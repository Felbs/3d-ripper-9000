"""Amusement Vision TPL texture packs (the .tpl next to every .gma in F-Zero GX and Super
Monkey Ball). Not the Nintendo SDK TPL (no 0x0020AF30 magic): u32 texture count, then
16-byte entries - u16 0, u8 null flag, u8 GX texture format, u32 absolute data offset,
u16 width, u16 height, u16 mip level count, u16 0x1234 - then the image data (all mips
back to back, 32-byte aligned). Unused slots have a zero offset (F-Zero GX leaves garbage
in their format bytes). No palettes: only the direct GX formats occur.
"""

from __future__ import annotations

import struct

from gcrip.formats import gx_texture
from gcrip.formats.bti import BtiTexture

ENTRY_MAGIC = 0x1234


def looks_like(data: bytes) -> bool:
    if len(data) < 4 + 16:
        return False
    (count,) = struct.unpack_from(">I", data, 0)
    if not 0 < count <= 65535 or len(data) < 4 + 16 * count:
        return False
    (magic,) = struct.unpack_from(">H", data, 4 + 14)
    return magic == ENTRY_MAGIC


def parse(data: bytes) -> list[BtiTexture | None]:
    """One entry per slot; None for empty or undecodable slots."""
    if not looks_like(data):
        raise ValueError("not an Amusement Vision TPL")
    (count,) = struct.unpack_from(">I", data, 0)
    out: list[BtiTexture | None] = []
    for i in range(count):
        _zero, _null, fmt, off, width, height, mips, magic = struct.unpack_from(
            ">HBBIHHHH", data, 4 + 16 * i
        )
        if magic != ENTRY_MAGIC or off == 0 or off >= len(data) or not width or not height:
            out.append(None)
            continue
        if fmt not in gx_texture.TILE_DIMS:
            out.append(None)
            continue
        total = 0
        w, h = width, height
        for _ in range(max(1, mips)):
            total += gx_texture.encoded_size(fmt, w, h)
            w, h = max(1, w // 2), max(1, h // 2)
        out.append(
            BtiTexture(
                name=f"tex{i:03d}",
                fmt=fmt,
                width=width,
                height=height,
                wrap_s=1,
                wrap_t=1,
                palette_fmt=None,
                palette=None,
                palette_count=0,
                mip_count=max(1, mips),
                min_filter=1,
                mag_filter=1,
                data=data[off : off + total],
            )
        )
    return out
