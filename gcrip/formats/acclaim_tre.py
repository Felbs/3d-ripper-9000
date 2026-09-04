"""Acclaim Austin's ``supertree0.tre`` (Vexx, Turok: Evolution) - one 739 / 846 MB file that
is the whole game.

The head is a table of 16-byte big-endian records ``u32 id, u32 offset, u32 size, u32 key``
sorted by ``key`` (a name hash - the ``Game.txt`` member names levels by path, and members
carry ``Y:\\Data\\Actors\\...`` paths); the table runs until the keys stop ascending (4,213
records on Vexx, 9,879 on Turok) and the first member starts right after it.  Members cover
the file exactly (739,296,370 bytes of 739,296,370).

Members seen: **textures** (a 32-byte header: ten zero bytes, ``u16 bytes``, ``u32``, ``u16
width, height, width, height``, ``ff ff``, ``00 59 ff 30 01 nn`` for CMPR with mips or
``00 51 ff 2c 01 00`` for one RGBA8 level - the format byte at +29), ``SWAP`` animation and
stream packs, ``\\x01atr`` / ``\\x01ati`` actor definitions and instance lists (a
tag-length-value stream: ``ACTOR``, ``NAME``, ``POS``, ``ROT``, ``SCALE``, ``EVENTS``), text
(``*PARTDEF``, ``*EMITDEF``, ``*PF``, ``*key``) and directory members that repeat the table's
triples (the "super tree").  No GX display lists were found in the largest members, so the
models are still to be located - the ``.atr`` actor definitions are the place to look.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture

RECORD = 16
MAX_RECORDS = 1 << 20
TEXTURE_HEADER = 32
TEXTURE_FORMATS = {0x30: 14, 0x2E: 14, 0x2C: 6, 0x2B: 6}  # header byte 29 -> GX format


@dataclass
class Entry:
    ident: int
    offset: int
    size: int
    key: int


def table(head: bytes, size: int) -> list[Entry]:
    """The records whose keys ascend, offsets fit and the first of which starts the data."""
    n = min(len(head) // RECORD, MAX_RECORDS)
    if n < 2:
        return []
    r = np.frombuffer(head, ">u4", n * 4).reshape(n, 4).astype(np.int64)
    ok = np.ones(n, bool)
    ok[1:] = np.diff(r[:, 3]) > 0
    ok &= (r[:, 1] + r[:, 2] <= size) & (r[:, 1] >= 0)
    end = int(np.argmin(ok)) if not ok.all() else n
    if end < 2 or int(r[:end, 1].min()) < RECORD * end:
        return []
    return [Entry(int(a), int(b), int(c), int(d)) for a, b, c, d in r[:end]]


def is_tre(head: bytes, size: int) -> bool:
    return len(table(head[: RECORD * 64], size)) >= 3  # a 64-byte sniff holds four


def is_texture(head: bytes, size: int) -> bool:
    # eight zero bytes, u32 pixel bytes, u32, u16 width, height, width, height, ff ff, kind
    if len(head) < TEXTURE_HEADER or head[:8] != bytes(8) or head[24:26] != b"\xff\xff":
        return False
    if struct.unpack_from(">I", head, 8)[0] != size - TEXTURE_HEADER:
        return False
    fmt = TEXTURE_FORMATS.get(head[29])
    width, height = struct.unpack_from(">2H", head, 16)
    if fmt is None or not (0 < width <= 2048 and 0 < height <= 2048):
        return False
    return size >= TEXTURE_HEADER + gx_texture.encoded_size(fmt, width, height)


def texture(data: bytes) -> np.ndarray | None:
    if not is_texture(data[:TEXTURE_HEADER], len(data)):
        return None
    fmt = TEXTURE_FORMATS[data[29]]
    width, height = struct.unpack_from(">2H", data, 16)
    need = gx_texture.encoded_size(fmt, width, height)
    try:
        return gx_texture.decode(fmt, width, height, data[TEXTURE_HEADER : TEXTURE_HEADER + need])
    except ValueError:
        return None
