"""Acclaim texture blocks - the All-Star Baseball discs keep every texture in them, in two
containers that share one image header: ``TBLOCKTEX`` (2003 and 2004) and the older
``ASB_TEXTURE`` (2002).

The block header is big-endian and the image headers inside it are little-endian, which is the
first thing to get straight::

    +0   char magic[16]  "TBLOCKTEX_30_BE\\0"
    +16  u32 image count            big-endian
    +20  u32 x 5
    +40  the image table, 36 bytes an entry:
             char name[32]          "jersey", "sky_day_clear_24bit"
             u32 offset             big-endian, from the start of the file

    image, at that offset:
    +0   u32 x 2                    GameCube RAM addresses, 544 apart
    +8   u32 pixel bytes            little-endian
    +12  u32 palette bytes          little-endian
    +16  u16 width | u16 height     little-endian, repeated at +20
    +24  u32 x 2
    +32  the pixels, then the palette

**The palette comes after the pixels, not before.**  Put it first and the image still decodes -
the tiling is right and the shapes read - so a Padres jersey comes out with legible lettering
and colour noise everywhere else, which looks like a palette-format problem rather than a
layout one.  It is worth stating plainly because the wrong reading is convincing.

Nothing in the header names a GX format.  It does not have to: the **palette size and the bits
per pixel determine it**, and the arithmetic then has to agree exactly.

    palette 512 bytes, 8 bits per pixel   ->  C8    (256 entries)
    palette  32 bytes, 4 bits per pixel   ->  C4    (16 entries)
    no palette,        4 bits per pixel   ->  CMPR
    no palette,       32 bits per pixel   ->  RGBA8

Palettes are `RGB5A3` in `TBLOCKTEX` and **`RGB565` in `ASB_TEXTURE`** - nothing in either
header says which, and the wrong one gives a recognisable picture in wrong colours rather
than noise.  The check is that ``encoded_size(format, width, height)`` reproduces the
stored pixel byte count; where it comes up short the extra bytes are a mip chain, and only the
top level is decoded.

The older ``ASB_TEXTURE`` container has no image table because it does not need one - every
image in a file is the **same size**::

    +0   char magic[12]  "ASB_TEXTURE\\0"
    +16  u32 image count            big-endian
    +24  u32 total pixel bytes      big-endian
    +28  u32 bytes an image         big-endian, repeated at +32
    +36  char name[32] * count      "ABREU_BOBBY", "ABBOTT_PAUL"
    ...  the images, back to back, then a trailing 268-byte record an image

The arithmetic closes exactly on every file: names, then count times the image size, then
268 more bytes an image, is the file length to the byte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture as gx

MAGIC = b"TBLOCKTEX"
OLD_MAGIC = b"ASB_TEXTURE"
HEADER = 40
OLD_NAMES_AT = 36
ENTRY = 36
NAME = 32
IMAGE_HEADER = 32
RGB5A3, RGB565 = 2, 1  # TBLOCKTEX palettes are RGB5A3, ASB_TEXTURE palettes are RGB565
MAX_IMAGES = 65536
MAX_DIM = 4096
# (palette bytes, bits per pixel) -> GX format
FORMATS = {(512, 8): 9, (32, 4): 8, (0, 4): 0xE, (0, 32): 6}


@dataclass
class Image:
    name: str
    offset: int
    width: int
    height: int
    format: int
    pixels: int
    palette: int
    palette_format: int = RGB5A3


def is_tblocktex(head: bytes) -> bool:
    return len(head) >= 20 and (head[: len(MAGIC)] == MAGIC or head[: len(OLD_MAGIC)] == OLD_MAGIC)


def _image(data: bytes, at: int, name: str, palette_format: int = RGB5A3) -> Image | None:
    """One image from its 32-byte header; the format falls out of the two sizes."""
    if at + IMAGE_HEADER > len(data):
        return None
    pixels, palette = struct.unpack_from("<2I", data, at + 8)
    width, height = struct.unpack_from("<2H", data, at + 16)
    if not (0 < width <= MAX_DIM and 0 < height <= MAX_DIM and pixels):
        return None
    if at + IMAGE_HEADER + pixels + palette > len(data):
        return None
    fmt = FORMATS.get((palette, round(pixels * 8 / (width * height))))
    if fmt is None or gx.encoded_size(fmt, width, height) > pixels:
        return None
    return Image(name, at, width, height, fmt, pixels, palette, palette_format)


def images(data: bytes) -> list[Image]:
    if len(data) < HEADER:
        return []
    if data[: len(OLD_MAGIC)] == OLD_MAGIC:
        return _old(data)
    if data[: len(MAGIC)] != MAGIC:
        return []
    count = struct.unpack_from(">I", data, 16)[0]
    if not 0 < count <= MAX_IMAGES or HEADER + count * ENTRY > len(data):
        return []
    out: list[Image] = []
    for i in range(count):
        p = HEADER + i * ENTRY
        name = data[p : p + NAME].split(b"\0")[0].decode("latin-1", "replace")
        got = _image(data, struct.unpack_from(">I", data, p + NAME)[0], name or f"image{i:04d}")
        if got is not None:
            out.append(got)
    return out


def _old(data: bytes) -> list[Image]:
    """``ASB_TEXTURE`` has no image table, so the images are walked one after another.

    The size at +28 is only the *first* image's, not a stride: on the player-face files every
    image is 64x64 and the two readings agree, but ``ASBUI.tex`` mixes sizes and a fixed stride
    walks off the end of the file after one image.  Stepping by each image's own header covers
    219 more files on All-Star Baseball 2002."""
    count = struct.unpack_from(">I", data, 16)[0]
    at = OLD_NAMES_AT + count * NAME
    if not 0 < count <= MAX_IMAGES or at > len(data):
        return []
    out: list[Image] = []
    for i in range(count):
        raw = data[OLD_NAMES_AT + i * NAME : OLD_NAMES_AT + (i + 1) * NAME]
        name = raw.split(b"\0")[0].decode("latin-1", "replace")
        got = _image(data, at, name or f"image{i:04d}", RGB565)
        if got is None:
            break
        out.append(got)
        at += IMAGE_HEADER + got.pixels + got.palette
    return out


def decode(data: bytes, image: Image) -> np.ndarray | None:
    """RGBA of the top mip level."""
    need = gx.encoded_size(image.format, image.width, image.height)
    start = image.offset + IMAGE_HEADER
    palette = None
    if image.palette:
        at = start + image.pixels
        palette = gx.decode_palette(
            image.palette_format, data[at : at + image.palette], image.palette // 2
        )
    return gx.decode(image.format, image.width, image.height, data[start : start + need], palette)
