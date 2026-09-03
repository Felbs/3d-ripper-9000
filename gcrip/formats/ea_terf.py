"""EA Tiburon archives and textures on GameCube (Madden NFL 2005, GNQE69).

TERF (big-endian): "TERF", u32 section offset, u8[4] version, u16 alignment, u16 count;
sections follow from the section offset, each "TAG_" + u32 size, aligned:
  HSH1  optional name-hash table
  DIR1  u32 offset, u32 size per member (offsets relative to the DATA tag)
  COMP  u32 type, u32 unpacked size per member (type 0 = stored, 5 = GCMP.LIB "LZH1",
        decoded by ea_lzh1; other types keep their packed bytes as .compN)
  DATA  member bytes
Members carry no names; they are numbered and get an extension from their magic.

MMAP (big-endian): "MMAP", u16 version, u16 0, u8[4] channel order, u16 levels, u16, u16,
u16, u32 total size, u32 header size, u32 palette block, u32 name block, u32 -, then per
level u16 width, u16 height, u16 GX format, u16 0, u32 size, u32 offset. Palette block:
u16 format (the texture's own code, not a constant 1 - it reads 11 on a format-11 MMAP),
u16 GX palette format, u32 size, u32 entries offset.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import ea_lzh1, gx_texture


@dataclass
class TerfMember:
    index: int
    offset: int  # absolute
    size: int
    comp_type: int = 0
    unpacked: int = 0


@dataclass
class Terf:
    align: int
    members: list[TerfMember] = field(default_factory=list)


def is_terf(head: bytes) -> bool:
    return len(head) >= 16 and head[:4] == b"TERF"


def parse(data: bytes) -> Terf:
    if not is_terf(data):
        raise ValueError("not a TERF archive")
    sec_off = struct.unpack_from(">I", data, 4)[0]
    align, count = struct.unpack_from(">HH", data, 12)
    align = max(align, 1)
    p = sec_off
    dir_ents: list[tuple[int, int]] = []
    comp: list[tuple[int, int]] = []
    data_off = None
    while p + 8 <= len(data):
        tag = data[p : p + 4]
        size = struct.unpack_from(">I", data, p + 4)[0]
        if tag == b"DIR1":
            n = min(count, (size - 8) // 8)
            dir_ents = [struct.unpack_from(">II", data, p + 8 + i * 8) for i in range(n)]
        elif tag == b"COMP":
            n = min(count, (size - 8) // 8)
            comp = [struct.unpack_from(">II", data, p + 8 + i * 8) for i in range(n)]
        elif tag == b"DATA":
            data_off = p
            break
        elif tag != b"HSH1":
            raise ValueError(f"unknown TERF section {tag!r}")
        p += size
        p = (p + align - 1) // align * align
    if data_off is None:
        raise ValueError("TERF without DATA section")
    t = Terf(align)
    for i, (off, size) in enumerate(dir_ents):
        m = TerfMember(i, data_off + off, size)
        if i < len(comp):
            m.comp_type, m.unpacked = comp[i]
        t.members.append(m)
    return t


LZH1 = 5  # GCMP.LIB codec index: NONE, RLE1, HUFF, LZM1, LZH1

_EXT = {
    b"MMAP": "mmap",
    b"TMdl": "tmdl",
    b"TERF": "terf",
    b"FAC\0": "fac",
    b"DB\0\x08": "db",
    b"SCHl": "schl",
    b"BNKb": "bnk",
    b"ABKC": "abk",
    b"MADk": "madk",
}


def expand(data: bytes) -> list[tuple[str, bytes]]:
    t = parse(data)
    out = []
    for m in t.members:
        blob = data[m.offset : m.offset + m.size]
        if m.comp_type == LZH1 and m.size:
            try:
                blob = ea_lzh1.unpack(blob, m.unpacked or None)
            except ea_lzh1.Lzh1Error:
                out.append((f"{m.index:04d}.comp{m.comp_type}", blob))
                continue
        if m.comp_type not in (0, LZH1, 0xFFFFFFFF) and m.size:
            ext = f"comp{m.comp_type}"
        elif blob[:1] == b"<":
            ext = "txt"
        else:
            ext = _EXT.get(blob[:4], "bin")
        out.append((f"{m.index:04d}.{ext}", blob))
    return out


# ---------------------------------------------------------------- MMAP


# EA uses one code GX does not define.  **11 is C8**: its data is exactly 8 bits a pixel
# (24x20 = 480 bytes, exact on both samples), and it carries the standard palette block
# declaring **256 RGB5A3 entries, all of them populated with plausible colours**, which is
# meaningless unless the pixels are indices into it.  Smoothness cannot confirm it at that size
# - C8 1.54, I8 2.13, IA4 1.11 are all near the noise floor on 480 pixels - so the palette is
# the evidence, not the picture.  Unfixed, this raised on 863 textures across four EA discs,
# 847 of them on NASCAR Thunder 2003.
EA_FORMATS = {11: 9}


def is_mmap(head: bytes) -> bool:
    return len(head) >= 0x28 and head[:4] == b"MMAP"


def _mmap_palette(data: bytes, pal_off: int, gx_fmt: int, warnings: list[str]) -> tuple[np.ndarray, int]:
    """Palette for one paletted level from the record at ``pal_off``; returns it and the size
    of the record so a pack can step to the next one."""
    count = {8: 16, 9: 256, 10: 16384}[gx_fmt]
    if pal_off and pal_off + 12 <= len(data):
        _own, pfmt, psize, poff = struct.unpack_from(">HHII", data, pal_off)
        count = min(count, max(1, psize // 2))
        if pfmt not in (0, 1, 2):
            warnings.append(f"MMAP palette format {pfmt} unknown, using RGB5A3")
            pfmt = 2
        return gx_texture.decode_palette(pfmt, data[poff : poff + count * 2], count), 12
    warnings.append("paletted MMAP without a palette block")
    palette = np.stack([np.arange(count) % 256] * 3 + [np.full(count, 255)], -1)
    return palette.astype(np.uint8), 0


def _mmap_level(data: bytes, level_off: int, pal_off: int, warnings: list[str]) -> tuple[np.ndarray, int]:
    """Decode the level whose 16-byte descriptor is at ``level_off``; returns the image and
    the number of palette bytes it consumed."""
    w, h, fmt, _z, size, off = struct.unpack_from(">HHHHII", data, level_off)
    gx_fmt = EA_FORMATS.get(fmt, fmt)
    if gx_fmt not in gx_texture.TILE_DIMS:
        raise ValueError(f"MMAP with unknown GX format {fmt}")
    if w == 0 or h == 0:
        raise ValueError("zero-sized MMAP")
    palette = None
    used = 0
    if gx_fmt in (8, 9, 10):
        palette, used = _mmap_palette(data, pal_off, gx_fmt, warnings)
    return gx_texture.decode(gx_fmt, w, h, data[off : off + size], palette), used


def decode_mmap(data: bytes) -> tuple[np.ndarray, list[str]]:
    """Level 0 of an MMAP as RGBA."""
    if not is_mmap(data):
        raise ValueError("not an MMAP texture")
    levels = struct.unpack_from(">H", data, 0x0C)[0]
    hdr_size, pal_off = struct.unpack_from(">II", data, 0x18)
    if levels < 1:
        raise ValueError("MMAP without levels")
    warnings: list[str] = []
    rgba, _ = _mmap_level(data, hdr_size, pal_off, warnings)
    return rgba, warnings


MMAP_NAME = 16


def mmap_pack(data: bytes) -> list[tuple[str, np.ndarray, list[str]]]:
    """Every texture of an MMAP that carries a name block - Tiburon model packs put one
    texture per "level" (base level only, no mips) and name each in 16-byte slots (15
    characters, ``~00`` suffixes for collisions; a per-texture record table after the names
    keeps the source mip counts).  Without a name block the MMAP is one texture and only
    level 0 is returned."""
    if not is_mmap(data):
        raise ValueError("not an MMAP texture")
    levels = struct.unpack_from(">H", data, 0x0C)[0]
    hdr_size, pal_off, name_off = struct.unpack_from(">III", data, 0x18)
    if levels < 1:
        raise ValueError("MMAP without levels")
    if not name_off or name_off + levels * MMAP_NAME > len(data):
        rgba, warnings = decode_mmap(data)
        return [("", rgba, warnings)]
    out = []
    skipped: list[str] = []
    pal = pal_off
    for i in range(levels):
        warnings: list[str] = []
        name = data[name_off + i * MMAP_NAME : name_off + (i + 1) * MMAP_NAME].split(b"\0")[0].decode("latin-1")
        try:
            rgba, used = _mmap_level(data, hdr_size + 16 * i, pal, warnings)
        except ValueError as exc:
            # stadium packs declare 79 slots and fill 61; the rest are stale descriptors
            skipped.append(f"{name or i}: {exc}")
            continue
        pal += used
        out.append((name, rgba, warnings))
    if skipped and out:
        out[0][2].append(f"{len(skipped)} MMAP pack slots did not decode ({skipped[0]})")
    return out
