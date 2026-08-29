"""Avalanche Software DBL / DBU databases (Tak 1-3, Chicken Little, DBZ Sagas, Rugrats: Royal
Ransom) as a container: the files are sequences of sub-databases, each a 0x40-byte header
``u16 id | u16 kind | u32 size | u16 count | "1000" | 0x30 zero bytes`` (big-endian in the
GameCube ``.dbl`` / ``.mdb`` files, little-endian for the members merged into a ``.dbu`` by
DBLMerge) followed by ``size`` bytes of records - texture tables with GX pixels, and mesh
records that embed raw GX FIFO streams (CP / XF register loads + display lists) with their
vertex arrays.  The record layouts (meshes, texture tables, material lists) are decoded by
gcrip.formats.dbl_mesh; see docs/formats/avalanche-dbl-gamecube.md.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

_TAG = re.compile(rb"1000\x00\x00")
EXTS = (".dbl", ".dbu", ".mdb", ".sdb", ".dbp", ".adb")


@dataclass
class Block:
    offset: int  # header start
    size: int  # payload size
    kind: int
    little: bool


def is_dbl(name: str, head: bytes) -> bool:
    if not name.lower().endswith(EXTS) or len(head) < 0x40:
        return False
    if head[:7].strip(b" ").isdigit() and head[7:8] == b"\n":
        return True  # text header ("8704   \n" build notes)
    return head[:4] in (b"0\0\0\0", b"\x30\x00\x00\x00") and head[8:11] in (b"GCN", b"DB\0")


def blocks(data: bytes) -> list[Block]:
    out: list[Block] = []
    n = len(data)
    last_end = 0
    for m in _TAG.finditer(data):
        h = m.start() - 10
        if h < last_end or h < 0 or h + 0x40 > n:
            continue
        if data[h + 16 : h + 0x40] != bytes(0x30):
            continue
        for fmt, little in ((">", False), ("<", True)):
            _id, kind, size, _cnt = struct.unpack_from(fmt + "HHIH", data, h)
            if 0 < size <= n - h - 0x40 and kind < 0x100:
                out.append(Block(h, size, kind, little))
                last_end = h + 0x40 + size
                break
    return out


def expand(data: bytes, min_size: int = 0x100) -> list[tuple[str, bytes]]:
    out = []
    for i, b in enumerate(blocks(data)):
        if b.size < min_size:
            continue
        end = min(b.offset + 0x40 + b.size, len(data))
        out.append((f"{i:03d}_kind{b.kind:x}.dbl", data[b.offset : end]))
    return out
