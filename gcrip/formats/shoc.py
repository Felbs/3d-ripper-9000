"""EA ``SHOC`` chunk archives - the ``.hog`` on the four Tiger Woods PGA Tour discs.

These share an extension with Warthog's archives (:mod:`gcrip.formats.wart_hog`) and nothing
else, which is how the backlog came to list one seven-disc `.hog` cluster where there are two:
872 of these against 101 of those.  **An extension is not a format.**

Big-endian chunks, ``char tag[4]`` then ``u32 size`` *including* the eight-byte header, laid
out as pairs::

    SHOC  wrapper, 8 bytes of zeros, then one inner chunk
      SHDR   u32 version | char type[4] | u32 index | u32 unpacked size
      Zdat   a zlib stream

so a member is an ``SHDR`` naming it and the data chunks that follow.  Members are typed rather
than named - ``sfx``, ``ter``, ``tgd``, ``Cact``, ``txf``, ``SONO``, ``CAMC``.

**The stream runs to the end of its SHOC wrapper, not to the end of the Zdat chunk.**  Zdat's
own size falls a few bytes short of the data, so bounding the inflate by it truncates every
stream: 0 of 170 finish, against 140 when the wrapper supplies the bound.  The unpacked size
in the SHDR is what confirms the pairing - it equals the inflated length, so a member that
decompresses to the wrong size is dropped rather than reported.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

HEADER = 8
WRAPPER = 16
MAGIC = b"CTRL"
SHOC = b"SHOC"
SHDR = b"SHDR"
ZDAT = b"Zdat"
DATA = (ZDAT, b"SDAT", b"Rdat")
FILL = b"FILL"
TAGS = {SHOC, SHDR, ZDAT, b"SDAT", b"Rdat", FILL, MAGIC, b"SYNC", b"PADD"}
ZLIB_CMF = b"x"
RAW_PREFIX = 40
MAX_CHUNKS = 1 << 18


@dataclass
class Member:
    kind: str
    index: int
    data: bytes


def is_shoc(head: bytes) -> bool:
    return head[:4] == MAGIC


def _chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    out = []
    at = 0
    while at + HEADER <= len(data) and len(out) < MAX_CHUNKS:
        tag = data[at : at + 4]
        # `FILL` is usually an ordinary sized chunk, but it is also used as a bare four-byte
        # pad - and there it is followed straight by another tag rather than by a size.  Read
        # that one as a sized chunk and its "size" is the next tag's letters, which ends the
        # walk mid-archive: it stopped 958,460 bytes into a 3.5 MB file on Tiger Woods 2005.
        if tag == FILL and data[at + 4 : at + 8] in TAGS:
            at += 4
            continue
        if not all(32 <= c < 127 for c in tag):
            break
        span = max(struct.unpack_from(">I", data, at + 4)[0], HEADER)
        if at + span > len(data):
            break
        out.append((tag, at, span))
        at += span
    return out


def members(data: bytes) -> list[Member]:
    """Every member whose payload reconciles with the size its ``SHDR`` declares."""
    if not is_shoc(data[:4]):
        return []
    out: list[Member] = []
    head: tuple[str, int, int] | None = None
    parts: list[bytes] = []

    def flush() -> None:
        if head is None or not parts:
            return
        kind, index, unpacked = head
        blob = b"".join(parts)
        if blob[:1] == ZLIB_CMF:
            try:
                blob = zlib.decompressobj().decompress(blob)
            except zlib.error:
                return
        elif len(blob) == unpacked + RAW_PREFIX:
            blob = blob[RAW_PREFIX:]
        if len(blob) == unpacked and unpacked:
            out.append(Member(kind, index, blob))

    for tag, at, span in _chunks(data):
        if tag != SHOC or at + WRAPPER + 4 > len(data):
            continue
        inner = data[at + WRAPPER : at + WRAPPER + 4]
        if inner == SHDR:
            flush()
            head, parts = None, []
            body = data[at + WRAPPER + 4 : at + WRAPPER + 20]
            if len(body) == 16:
                _version, kind, index, unpacked = struct.unpack(">I4s2I", body)
                head = (kind.decode("latin-1").strip() or "data", index, unpacked)
        elif inner in DATA and head is not None:
            parts.append(data[at + WRAPPER + HEADER : at + span])
    flush()
    return out
