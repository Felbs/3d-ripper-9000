"""EA's RenderWare stream container - Call of Duty: Finest Hour and Harry Potter: Goblet of Fire.

Both discs report almost nothing (21 models and 0) and both are full of files that open as a
RenderWare chunk and then refuse to walk::

    1c 07 00 00   10 03 00 00   ff ff 02 18

`u32 id, u32 size, u32 version` little-endian, with a version stamp of ``0x1802FFFF`` -
RenderWare 3.6 - but the ids are EA's own rather than the stock CLUMP / WORLD / TEXDICT, so
``plugins/renderware.py`` declines the file and nothing else claims it.

The stream walks exactly.  On two files as different as a 591,720-byte level script and a
6,062,378-byte object database, ``at += 12 + size`` covers **every byte and lands on the end**:
554 chunks and 6,411 chunks respectively, with nothing left over.  That is the size identity,
and it is what says the ids are being read correctly.

Three ids carry the structure:

``0x071C``
    the **type table**: `u32 count, name, NUL, 0xBF padding to four` repeated - `RenderTrigger`,
    `WorldLight`, `CAnimPackSelector`, `LevelInfo`, `CPickupSelector`.  One per file, first.
``0x0716``
    an **asset descriptor**: a length-prefixed name, sixteen bytes of identifier, a
    length-prefixed *type* name - `rwID_TEXDICTIONARY`, `rwID_SPLINE` - and the asset's build
    path, `ps:\\cod\\game\\rws\\cod1_22p\\build output\\gamecube\\texture dictionary\\{...}`.
``0x0704`` / ``0x0719``
    the payloads.  495 of the first in the level script; 6,411 of the second in the object
    database, each a small typed record.

The names and types are the point of opening these: a member comes out as
``rwID_TEXDICTIONARY`` or ``rwID_SPLINE`` under the name the game gave it, and whichever plugin
reads that kind gets it.

**What is not here:** mesh geometry.  The two files walked hold 57 splines, one texture
dictionary and an object database, and neither carries a RenderWare chunk with a 3.x stamp
inside it or a single native display-list group.  Call of Duty's meshes are somewhere else on
the disc - its 231 `.rws` (582 MB) are the obvious place, and `docs/formats/rws-is-audio.md`
only measured `.rws` on three other discs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

CHUNK = 12
#: the type-name table, one per file
TYPE_TABLE = 0x071C
#: an asset descriptor: name, identifier, type name, build path
DESCRIPTOR = 0x0716
#: RenderWare 3.x version stamps, high half
STAMPS = (0x1800, 0x1801, 0x1802, 0x1803)
#: sixteen bytes between an asset's name and its type name
IDENT_BYTES = 16
MAX_CHUNKS = 1 << 20
MAX_NAME = 1 << 12
#: Goblet of Fire writes this constant where Call of Duty writes a size.  It is the same value
#: in every file and every chunk that carries it, so it is a sentinel, not a length: the
#: chunk's extent has to be found by looking for the next stamped header.
NO_SIZE = 0xFABB00B5


@dataclass(frozen=True)
class Chunk:
    ident: int
    offset: int
    size: int
    version: int

    @property
    def body(self) -> int:
        return self.offset + CHUNK

    @property
    def end(self) -> int:
        return self.offset + CHUNK + self.size


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    path: str
    chunk: Chunk


#: the ids a stream's first chunk can carry - a level script leads with its type table, an
#: object database with a payload chunk, so the id alone cannot gate the format
FIRST_IDS = (0x0704, DESCRIPTOR, 0x0719, TYPE_TABLE)


def is_ea_rws(head: bytes) -> bool:
    if len(head) < CHUNK:
        return False
    ident, size, version = struct.unpack_from("<3I", head, 0)
    return ident in FIRST_IDS and (version >> 16) in STAMPS and 0 < size


def chunks(data: bytes) -> list[Chunk]:
    """Every top-level chunk.  Returns nothing unless the walk covers the file exactly."""
    if not is_ea_rws(data[:CHUNK]):
        return []
    out: list[Chunk] = []
    at = 0
    n = len(data)
    while at + CHUNK <= n and len(out) < MAX_CHUNKS:
        ident, size, version = struct.unpack_from("<3I", data, at)
        if (version >> 16) not in STAMPS:
            return []
        if size > n - at - CHUNK and size != NO_SIZE:
            return []  # an oversized length is a misread file, not the sentinel variant
        if size == NO_SIZE:
            nxt = _next_header(data, at + CHUNK)
            if nxt is None:
                out.append(Chunk(ident, at, n - at - CHUNK, version))
                return out
            out.append(Chunk(ident, at, nxt - at - CHUNK, version))
            at = nxt
            continue
        out.append(Chunk(ident, at, size, version))
        at += CHUNK + size
    return out if at == n else []


def _next_header(data: bytes, at: int) -> int | None:
    """Where the next stamped chunk header starts, for a chunk that declares no length."""
    n = len(data)
    while at + CHUNK <= n:
        _ident, size, version = struct.unpack_from("<3I", data, at)
        if (version >> 16) in STAMPS and size <= n - at - CHUNK:
            return at
        at += 1
    return None


def _string(data: bytes, at: int) -> tuple[str, int]:
    """A length-prefixed name; the field is NUL-terminated and padded with 0xBF."""
    if at + 4 > len(data):
        return "", at
    length = struct.unpack_from(">I", data, at)[0]
    if not 0 < length <= MAX_NAME or at + 4 + length > len(data):
        return "", at + 4
    raw = data[at + 4 : at + 4 + length].split(b"\0")[0]
    return raw.decode("latin-1", "replace"), at + 4 + length


def assets(data: bytes) -> list[Asset]:
    """The named, typed assets a stream declares."""
    out: list[Asset] = []
    for c in chunks(data):
        if c.ident != DESCRIPTOR:
            continue
        at = c.body + 4
        name, at = _string(data, at)
        at += IDENT_BYTES
        kind, at = _string(data, at)
        path, _ = _string(data, at)
        if name:
            out.append(Asset(name, kind, path, c))
    return out


def type_names(data: bytes) -> list[str]:
    """The class names the leading table registers."""
    got = chunks(data)
    if not got or got[0].ident != TYPE_TABLE:
        return []
    out: list[str] = []
    at = got[0].body
    end = got[0].end
    while at + 5 < end:
        at += 4  # a count, not a length: the name that follows is NUL-terminated
        stop = data.find(bytes(1), at, end)
        if stop < 0:
            break
        raw = data[at:stop]
        if not raw:
            break
        out.append(raw.decode("latin-1", "replace"))
        at = stop + 1
        while at < end and data[at] == 0xBF:  # padded to four with 0xBF
            at += 1
    return out


# -- identities ---------------------------------------------------------------------------


def _walk_covers_the_file(data: bytes):
    if not is_ea_rws(data[:CHUNK]):
        return None, "not an EA RenderWare stream"
    got = chunks(data)
    if not got:
        return False, "the chunk walk does not land on the end of the file"
    return got[-1].end == len(data), f"{len(got)} chunks reaching {got[-1].end} of {len(data)}"


def _assets_are_typed(data: bytes):
    got = assets(data)
    if not got:
        return None, "no asset descriptors"
    typed = sum(1 for a in got if a.kind.startswith("rwID_"))
    return typed == len(got), f"{typed} of {len(got)} assets name an rwID_ type"


IDENTITIES = [
    Identity(
        "the chunk walk covers the file",
        "at += 12 + size from byte 0 lands exactly on the end",
        _walk_covers_the_file,
    ),
    Identity(
        "every asset names its type",
        "a 0x0716 descriptor's second string is an rwID_ name",
        _assets_are_typed,
    ),
]
