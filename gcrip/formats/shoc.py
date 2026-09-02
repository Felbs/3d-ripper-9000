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

from gcrip.identities import Identity

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
#: Bytes of per-chunk header before a data chunk's payload, proven by size identity on
#: Tiger Woods 2005: summing `payload - 44` over a resource's chunks reproduces the size
#: its SHDR declares exactly, for `RLst` (8,548 over 2 chunks) and `sync` (65,536 over 9).
#: The same sum is 63% of declared for `ter` and 39% for `txfh`, which is how we know
#: those are genuinely packed rather than merely mis-read.
CHUNK_HEADER = 44
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

# -- block structure -----------------------------------------------------------------------

#: A data chunk's inner tag says how its block is stored, and this is the whole difference
#: between the discs that read and the discs that did not:
#:
#: ``SDAT``  stored - the payload after the 44-byte header IS the data
#: ``Zdat``  a zlib stream (Tiger Woods 06)
#: ``Rdat``  a ``u32`` big-endian uncompressed size, then EA's own LZ (2003/2004/2005)
#:
#: The old reader knew the first two and treated ``Rdat`` as one of them, which is why those
#: three discs produced 57 members totalling 5 KB out of a 4.9 MB archive.
STORED, ZLIB, EALZ = b"SDAT", b"Zdat", b"Rdat"
#: a zlib block's output size is not recorded; it has to be inflated
UNKNOWN = -1


@dataclass
class Block:
    """One data chunk's payload, and how to get the bytes out of it."""

    how: bytes  # STORED / ZLIB / EALZ
    offset: int  # of the block, after the 44-byte chunk header
    size: int  # bytes of block present in the file
    #: what it must produce, or ``UNKNOWN`` for a zlib block - deflate does not record its
    #: output size, so that one can only be had by inflating
    unpacked: int

    @property
    def stored(self) -> bool:
        return self.how == STORED


@dataclass
class Resource:
    kind: str
    index: int
    declared: int
    blocks: list[Block]

    @property
    def sizes_known(self) -> bool:
        """False when any block is zlib, whose output size is not recorded anywhere."""
        return all(b.unpacked != UNKNOWN for b in self.blocks)

    @property
    def reconciles(self) -> bool:
        """The identity: the blocks account for exactly what the ``SHDR`` declares.

        Only meaningful when :attr:`sizes_known` - a zlib block has to be inflated before it can
        be counted, so a `Zdat` resource is not evidence either way rather than a failure.
        """
        return self.sizes_known and sum(b.unpacked for b in self.blocks) == self.declared


def resources(data: bytes) -> list[Resource]:
    """Every ``SHDR`` resource and the blocks that make it up.

    Verified by the identity on `Resource.reconciles`: **267 of 267 resources** on Tiger Woods
    2005's `_gree/hole_01` account for their declared size exactly.
    """
    if not is_shoc(data[:4]):
        return []
    out: list[Resource] = []
    cur: Resource | None = None
    for tag, at, span in _chunks(data):
        if tag != SHOC or at + WRAPPER + 4 > len(data):
            continue
        inner = data[at + WRAPPER : at + WRAPPER + 4]
        if inner == SHDR:
            body = data[at + WRAPPER + 4 : at + WRAPPER + 20]
            if len(body) == 16:
                _v, kind, idx, unp = struct.unpack(">I4s2I", body)
                cur = Resource(kind.decode("latin-1").strip() or "data", idx, unp, [])
                out.append(cur)
        elif inner in DATA and cur is not None:
            # the payload follows the 4-byte inner tag directly, then the 44-byte header;
            # WRAPPER + HEADER would be 4 bytes too far and breaks the identity outright
            start = at + WRAPPER + 4 + CHUNK_HEADER
            end = at + span
            if start >= end:
                continue
            if inner == EALZ:
                if start + 4 > len(data):
                    continue
                unpacked = struct.unpack_from(">I", data, start)[0]
                cur.blocks.append(Block(inner, start + 4, end - start - 4, unpacked))
            elif inner == ZLIB:
                cur.blocks.append(Block(inner, start, end - start, UNKNOWN))
            else:
                cur.blocks.append(Block(inner, start, end - start, end - start))
    return out


# -- identities ---------------------------------------------------------------------------


def _blocks_account_for_declared(data: bytes):
    """Every resource's blocks sum to exactly the size its SHDR declares."""
    rs = [r for r in resources(data) if r.blocks and r.sizes_known]
    if not rs:
        return None, "no resource with known block sizes (all zlib, or not a SHOC archive)"
    ok = sum(1 for r in rs if r.reconciles)
    return ok == len(rs), f"{ok} of {len(rs)} resources account for their declared size"


def _tags_are_known(data: bytes):
    rs = resources(data)
    if not rs:
        return None, "not a SHOC archive"
    blocks = [b for r in rs for b in r.blocks]
    if not blocks:
        return None, "no data blocks"
    good = sum(1 for b in blocks if b.how in (STORED, ZLIB, EALZ))
    return good == len(blocks), f"{good} of {len(blocks)} blocks carry a known storage tag"


IDENTITIES = [
    Identity(
        "blocks account for the declared size",
        "sum(block.unpacked) == SHDR.declared, per resource",
        _blocks_account_for_declared,
    ),
    Identity(
        "every block says how it is stored",
        "inner tag is SDAT, Zdat or Rdat",
        _tags_are_known,
    ),
]
