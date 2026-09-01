"""``PIGGCN.pkd`` - Piglet's BIG GAME, one 232 MB block-compressed archive of RenderWare assets.

The backlog filed this disc under ``.rws`` RenderWare stream bundles.  Its ``.rws`` are audio
(see ``docs/formats/rws-is-audio.md``); everything the game draws is in this one file.

It opens ``78 da`` at entropy 7.99 and is a **chain of independent zlib streams**: each
terminates cleanly and the next begins where ``unused_data`` starts.  The chain covers the file
**exactly** - 232,370,273 of 232,370,273 bytes in 10,328 streams, inflating to 425 MB - which is
the identity that says the walk is right.

**Assets span blocks, and that is the whole trick.**  Read a block on its own and most
RenderWare chunks declare a size a little larger than the block holds: of 23 clumps in an early
sample only 2 satisfied ``12 + size == len(block)``.  The give-away is that the short blocks'
lengths are all **multiples of 16** while the two that fitted are not - blocks are padded to 16
except the last one of an asset.  So the blocks are concatenated into one image and each asset
is read from there; every clump then parses, 13 of 13 in the first 300 blocks.

Two readings that look plausible and are wrong, recorded so they are not retried:

* *the concatenation is one chunk chain* - it is not.  Walking chunks from offset 0 stops
  immediately, because the first block is ``XMD`` property text, not a chunk.
* *a short chunk is completed by the following block alone* - joining the two does make the
  size fit, but the next block often belongs to a different asset, so the fit is a coincidence
  of size rather than evidence.

What the archive holds, counted over all 10,328 blocks::

    4,891  0x1B  RenderWare animation
    3,089  XMD   property data (AttachedSND, BoneLink, Rigid, Sphere)
      936  0x10  CLUMP
      533  0x1E
      404  0x16  TEXDICTIONARY
      162  DSBH
      140  0x0C
       66  0x0B  WORLD

The RenderWare payloads need no new reader - ``plugins/renderware.py`` takes them as they are.
``XMD`` is three letters and a NUL, **not** the ``XMDL`` that :mod:`gcrip.formats.xmdl` reads.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

ZLIB_MAGIC = (b"\x78\xda", b"\x78\x9c", b"\x78\x01")
HEADER = 12
# the RenderWare chunk types this archive stores at a block boundary
ASSET_TYPES = (0x10, 0x0B, 0x16, 0x1B, 0x1E, 0x0C)
MAX_BLOCKS = 1 << 17
MAX_OUTPUT = 1 << 31  # 2 GiB: the real file makes 425 MB, so this only stops a runaway


@dataclass
class Asset:
    kind: int
    offset: int  # into the inflated image
    size: int  # including the 12-byte chunk header


def is_pkd(head: bytes) -> bool:
    return head[:2] in ZLIB_MAGIC


def inflate(data: bytes) -> tuple[bytes, list[int]] | None:
    """The whole archive as one image, plus the offset each block starts at.

    ``memoryview`` matters here: slicing ``bytes`` copies the remaining 232 MB on every one of
    the ten thousand blocks, which is the difference between seconds and never finishing.
    """
    if not is_pkd(data[:2]):
        return None
    view = memoryview(data)
    out = bytearray()
    starts: list[int] = []
    at = 0
    while at < len(data) and len(starts) < MAX_BLOCKS and len(out) < MAX_OUTPUT:
        stream = zlib.decompressobj()
        try:
            block = stream.decompress(view[at:])
        except zlib.error:
            return None
        if not stream.eof:
            return None
        starts.append(len(out))
        out += block
        at += (len(data) - at) - len(stream.unused_data)
    if at != len(data):
        return None
    return bytes(out), starts


def assets(image: bytes, starts: list[int]) -> list[Asset]:
    """Every RenderWare chunk that begins at a block boundary and fits the image."""
    out = []
    for off in starts:
        if off + HEADER > len(image):
            break
        kind, size, _lib = struct.unpack_from("<3I", image, off)
        if kind not in ASSET_TYPES or size <= 16:
            continue
        if off + HEADER + size > len(image):
            continue
        out.append(Asset(kind, off, HEADER + size))
    return out
