"""Sony ``TIM2`` textures - Capcom's GameCube ports keep them unchanged from the PS2.

Found so far inside AFS members on Auto Modellista (``afs02``) and Capcom vs SNK 2 EO
(``afs02``), where an offset table points at several in a row.  Little-endian::

    +0   char magic[4]     "TIM2"
    +4   u8   version
    +5   u8   format        1 -> the header is padded to 128 bytes, 0 -> 16
    +6   u16  pictures
    ...  each picture header, at 16 or 128:
         u32 total size | u32 clut bytes | u32 image bytes | u16 header bytes
         u16 clut colours | u8 picture format | u8 mip levels | u8 clut type
         u8 image type | u16 width | u16 height

**The header is self-checking twice over**: ``image + clut + header == total`` and
``total + 16 or 128 == the member's length``.  Both hold on every picture found, which is what
makes a magic-scan safe here - four ASCII bytes on their own would not be.

The pixels keep the **PS2's linear layout**; they are not re-tiled for GX.  Reading the index
plane as an 8x4 or 4x4 GX tile scrambles it, and the roughness says so - 28.6 linear against
50.2 and 47.5 for the two tilings over the six pictures found.

The CLUT is stored **CSM1**, which interleaves it: within every block of 32 entries the middle
two groups of eight are swapped.  ``clut type`` is 3 here, and bit 7 clear means CSM1.  The
evidence is thinner than for the pixel layout - unswizzling improves image roughness from 19.35
to 16.72 on Auto Modellista and from 47.57 to 46.87 on Capcom vs SNK 2, both in the right
direction but neither dramatic - so it is applied because the format says so and the numbers
agree, not because the numbers alone would prove it.

PS2 alpha runs 0-128 rather than 0-255, so it is doubled and clamped.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"TIM2"
ALIGNED = 128
COMPACT = 16
PICTURE = 48
INDEXED8 = 5
INDEXED4 = 4
RGBA32 = 3
CSM1_BLOCK = 32
MAX_DIM = 4096
TABLE_END = 0xFFFFFFFF
MAX_TABLE = 4096


@dataclass
class Picture:
    width: int
    height: int
    image_type: int
    clut_colours: int
    pixels: bytes
    clut: bytes


def is_tim2(head: bytes) -> bool:
    return head[:4] == MAGIC


def _header_size(data: bytes) -> int:
    return ALIGNED if data[5] else COMPACT


def pictures(data: bytes) -> list[Picture]:
    if not is_tim2(data[:6]) or len(data) < COMPACT:
        return []
    at = _header_size(data)
    out = []
    for _ in range(struct.unpack_from("<H", data, 6)[0]):
        if at + PICTURE > len(data):
            break
        total, clut_bytes, image_bytes, header_bytes = struct.unpack_from("<3IH", data, at)
        clut_colours = struct.unpack_from("<H", data, at + 14)[0]
        image_type = data[at + 19]
        width, height = struct.unpack_from("<2H", data, at + 20)
        if image_bytes + clut_bytes + header_bytes != total:
            break
        if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM):
            break
        start = at + header_bytes
        if start + image_bytes + clut_bytes > len(data):
            break
        out.append(
            Picture(
                width,
                height,
                image_type,
                clut_colours,
                data[start : start + image_bytes],
                data[start + image_bytes : start + image_bytes + clut_bytes],
            )
        )
        at += total
    return out


def _unswizzle(palette: np.ndarray) -> np.ndarray:
    """CSM1 swaps the middle two groups of eight inside every block of 32."""
    if len(palette) % CSM1_BLOCK:
        return palette
    order = np.arange(len(palette)).reshape(-1, 4, 8)
    order[:, [1, 2]] = order[:, [2, 1]]
    return palette[order.reshape(-1)]


def _palette(clut: bytes, colours: int) -> np.ndarray | None:
    """The CLUT as RGBA.  Its entry width is taken from the byte count rather than from the
    clut type - 4 bytes an entry is RGBA, 3 is RGB with no alpha to double, 2 is PS2
    ``A1B5G5R5``.  Anything else declines: three pictures here have an eight-byte stride that
    no documented CLUT format explains, and guessing at those would produce plausible
    nonsense."""
    if not colours or len(clut) < colours:
        return None
    width = len(clut) // colours
    if width not in (2, 3, 4):
        return None
    palette = np.full((colours, 4), 255, np.uint8)
    if width == 2:
        # PS2 A1B5G5R5, little-endian: red in the low five bits, one bit of alpha on top
        raw = np.frombuffer(clut[: colours * 2], "<u2").astype(np.uint32)
        for i, shift in enumerate((0, 5, 10)):
            five = (raw >> shift) & 0x1F
            palette[:, i] = (five << 3) | (five >> 2)
        palette[:, 3] = np.where(raw >> 15, 255, 0).astype(np.uint8)
    else:
        table = np.frombuffer(clut[: colours * width], np.uint8).reshape(colours, width)
        palette[:, :3] = table[:, :3]
        if width == 4:
            palette[:, 3] = np.minimum(table[:, 3].astype(np.uint16) * 2, 255)
    return _unswizzle(palette) if colours == 256 else palette


def decode(pic: Picture) -> np.ndarray | None:
    """RGBA, or None when the picture is not one of the layouts confirmed on a disc."""
    if pic.image_type not in (INDEXED4, INDEXED8):
        return None
    palette = _palette(pic.clut, pic.clut_colours)
    if palette is None:
        return None
    pixels = pic.width * pic.height
    if pic.image_type == INDEXED8:
        if len(pic.pixels) < pixels:
            return None
        index = np.frombuffer(pic.pixels[:pixels], np.uint8)
    else:
        packed = (pixels + 1) // 2
        if len(pic.pixels) < packed:
            return None
        raw = np.frombuffer(pic.pixels[:packed], np.uint8)
        # low nibble first, as the PS2 stores 4-bit indices
        index = np.empty(packed * 2, np.uint8)
        index[0::2] = raw & 0x0F
        index[1::2] = raw >> 4
        index = index[:pixels]
    if index.max(initial=0) >= len(palette):
        return None
    return palette[index].reshape(pic.height, pic.width, 4)


def _offsets(data: bytes, limit: int | None = None) -> list[int]:
    """The ascending table at the head of the blob, or [] if it is not one.

    ``limit`` bounds the offsets to the blob's length and is only passed when the whole blob is
    in hand.  On a 64-byte sniff every entry after the first points past the end, so applying
    the bound there would reject the very tables this is meant to find.
    """
    if len(data) < 8:
        return []
    first = struct.unpack_from("<I", data, 0)[0]
    if not 8 <= first <= MAX_TABLE * 4 or first % 4:
        return []
    offsets: list[int] = []
    at = 0
    stop = min(first, len(data))
    while at + 4 <= stop and len(offsets) < MAX_TABLE:
        value = struct.unpack_from("<I", data, at)[0]
        if value == TABLE_END:
            break
        if (offsets and value <= offsets[-1]) or (limit is not None and value >= limit):
            break
        offsets.append(value)
        at += 4
    return offsets


def looks_like_table(head: bytes) -> bool:
    """True for a blob that opens with such a table.  It deliberately does not look for the
    magic: the first offset is often exactly 64, so on a 64-byte sniff the magic it points at
    is one byte out of reach.  :func:`table` does the real check."""
    return len(_offsets(head)) >= 2


def table(data: bytes) -> list[tuple[int, int]]:
    """An AFS member is often an offset table pointing at several TIM2 in a row, closed by
    ``0xffffffff``.  A slice is only kept when its offset lands exactly on the magic, so an
    ordinary ascending array of numbers cannot be mistaken for one."""
    offsets = _offsets(data, len(data))
    out = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        if data[start : start + 4] == MAGIC:
            out.append((start, end))
    return out
