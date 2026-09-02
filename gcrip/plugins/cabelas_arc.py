"""Cabela's ``Data/data.arc`` - a chain of raw zlib streams at 0x800-aligned offsets.

307 MB on Dangerous Hunts 2, and **the blocks are not all the same thing**, which is what made
this disc look empty: the first blocks are navigation data stamped ``PathGen 3.2``, the middle
holds Lua, and the tail is ``MULA`` texture archives.  A verdict taken from the first block
generalised to the file and the disc was written off.

Only the ``MULA`` blocks are kept.  Inflating all ~8,300 of them would cost hundreds of
megabytes to hand back navigation meshes and scripts no plugin reads, so each block is inflated,
tested, and dropped again unless it is an archive we can use.
"""

from __future__ import annotations

import zlib

from gcrip.formats import mula

NAME = "cabelas_arc"

ALIGN = 0x800
ZLIB_CMF = 0x78
ZLIB_FLG = (0x01, 0x5E, 0x9C, 0xDA)
MIN_INFLATED = 64
MAX_BLOCK = 64 << 20


def _zlib_start(data: bytes, at: int) -> bool:
    return data[at] == ZLIB_CMF and data[at + 1] in ZLIB_FLG


def is_container(name: str, head: bytes) -> bool:
    return (
        name.lower().endswith(".arc")
        and len(head) >= 2
        and _zlib_start(head, 0)
    )


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for at in range(0, len(data) - 1, ALIGN):
        if not _zlib_start(data, at):
            continue
        try:
            blob = zlib.decompressobj().decompress(data[at : at + MAX_BLOCK])
        except zlib.error:
            continue
        if len(blob) < MIN_INFLATED or not mula.is_mula(blob[:4]):
            continue
        out.append((f"block{at:09x}.mula", blob))
    return out


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
