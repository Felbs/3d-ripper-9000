"""Kalisto's ``TotemTech`` engine: the ``.dgc`` data file and its ``.ngc`` index.

Spirits & Spells, Jimmy Neutron: Boy Genius and SpongeBob: Revenge of the Flying Dutchman - 383
files, 525 MB.  ``docs/OPEN.md`` recorded the blocker as *"the file has no directory at all -
nothing anywhere references the verified vertex data"*.

**There is a directory, and it is the sibling file.**  Every ``.dgc`` has a ``.ngc`` of the same
stem - 225 and 225 on Spirits & Spells, sharing all 225 stems - and the ``.ngc`` is plain text::

    -853289997 "WORLD"
    854756687 "DB:>LEVELS>LEVEL07A>MAP>LEVEL07A.TWORLD"
    596819425 "LEVEL07A"
    -1989570394 "DB:>LEVELS>LEVEL07A>MAP>3DNODEFAMILY>ROOT_LEVEL07A.T3DNODE"

A signed 32-bit hash and the object's typed path, one pair per line.  `LEVEL07A.ngc` holds
**3,519** of them, 3,519 of 3,520 lines parsing, and the type suffix says what each object is:

===============  =====
``T3DNODE``      1,473
``TSURFACE``       116
``TGA``            108
``T3DNODE_UDEF``    87
``TBITMAP``         77
``TBITMAP_MAT``     77
``TVOLUME``         56
``TMESH``           52
===============  =====

**And the hashes are in the `.dgc`, big-endian.**  Of the first 400 index entries, **400 are
found verbatim** as big-endian `u32`; as little-endian, **0** are.  They begin at byte 2,056 in
the same order the index lists them, mostly packed four bytes apart, so the data file is a
reference graph keyed by the hashes the sidecar names.

That is what the note was missing.  A `TMESH` hash appears twice - once as a reference and once
at its definition - and the bytes after the definition are float-dense: 74% plausible big-endian
`f32` in the 4 KB following `O_ECHAFAUDAGE_MESH.TMESH`.

This module reads the index.  Walking the graph from a hash to its geometry is the next step and
is not done here.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from gcrip.identities import Identity

#: 79-byte ASCII banner every `.dgc` opens with
BANNER = b"TotemTech Data v"
#: `<signed decimal> "<path>"`
_LINE = re.compile(r'^\s*(-?\d+)\s+"([^"]*)"\s*$')


@dataclass(frozen=True)
class Entry:
    """One indexed object."""

    hash: int  # as unsigned, which is how it appears in the .dgc
    path: str  # "DB:>LEVELS>LEVEL07A>MAP>...>NAME.TMESH"

    @property
    def name(self) -> str:
        return self.path.rsplit(">", 1)[-1]

    @property
    def kind(self) -> str:
        """The type suffix - TMESH, TBITMAP, T3DNODE ... - or "" for a bare label."""
        tail = self.name.rsplit(".", 1)
        return tail[1].upper() if len(tail) == 2 else ""


def is_dgc(head: bytes) -> bool:
    return head[: len(BANNER)] == BANNER


def index(data: bytes) -> list[Entry]:
    """Parse a ``.ngc`` index.  Lines that do not match are skipped, not guessed at."""
    out: list[Entry] = []
    for line in data.decode("latin-1").splitlines():
        m = _LINE.match(line)
        if m:
            out.append(Entry(int(m.group(1)) & 0xFFFFFFFF, m.group(2)))
    return out


def of_kind(entries: list[Entry], kind: str) -> list[Entry]:
    return [e for e in entries if e.kind == kind.upper()]


def locate(dgc: bytes, entry: Entry) -> list[int]:
    """Every offset in the ``.dgc`` where this object's hash appears, big-endian.

    Big-endian is not a guess: of the first 400 entries of `LEVEL07A`, 400 are found this way
    and 0 the other way round.
    """
    key = struct.pack(">I", entry.hash)
    out: list[int] = []
    at = dgc.find(key)
    while at >= 0:
        out.append(at)
        at = dgc.find(key, at + 1)
    return out


# -- identities ---------------------------------------------------------------------------


def _lines_parse(data: bytes):
    text = data.decode("latin-1", "replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None, "empty index"
    got = len(index(data))
    return got >= len(lines) - 1, f"{got} of {len(lines)} non-blank lines parse"


def _paths_are_typed(data: bytes):
    ents = index(data)
    if not ents:
        return None, "no entries"
    typed = sum(1 for e in ents if e.kind)
    return typed > len(ents) // 2, f"{typed} of {len(ents)} entries carry a type suffix"


IDENTITIES = [
    Identity("index lines parse", 'every line is `<int> "<path>"`', _lines_parse),
    Identity("paths carry a type", "the name ends .TMESH, .TBITMAP, .T3DNODE ...", _paths_are_typed),
]


# -- the .dgc record chain -----------------------------------------------------------------
#
# The data file is a flat chain of records, each one::
#
#     u32 size            bytes from here to the next record
#     u32 class hash      hash("MESH"), hash("SURFACE"), hash("BITMAP") ...
#     u32 self hash       the entry the .ngc names
#     u32 name hash       the object's short name
#     ... payload ...
#
# `size` is a **size identity**: 2,027 of 2,036 hops on LEVEL07A land byte-exactly on the next
# record's own header, and the remaining nine land within 32 bytes of it.  Records are packed to
# the byte, not aligned, so the walk must be byte-wise.

#: u32 size, u32 class hash, u32 self hash, u32 name hash
REC_HEADER = 16
#: the smallest record that can hold a header and anything at all
REC_MIN = 16
#: how far past a declared end to look for the next header before giving up on the chain
REC_SLACK = 64


@dataclass(frozen=True)
class Record:
    """One object in the ``.dgc``."""

    offset: int
    size: int
    cls: int  # hash of the class name - "MESH", "SURFACE", "BITMAP", ...
    ident: int  # hash of the object, as the .ngc names it
    name: int  # hash of the object's short name

    @property
    def end(self) -> int:
        return self.offset + self.size


def _hash_mask(data: bytes, wanted: set[int]):
    """For every byte offset, whether the big-endian u32 there is one of `wanted`."""
    import numpy as np

    a = np.frombuffer(data, np.uint8).astype(np.uint32)
    w = (a[:-3] << 24) | (a[1:-2] << 16) | (a[2:-1] << 8) | a[3:]
    keys = np.array(sorted(wanted), dtype=np.uint32)
    at = np.clip(np.searchsorted(keys, w), 0, len(keys) - 1)
    return w, keys[at] == w


def records(dgc: bytes, entries: list[Entry]) -> list[Record]:
    """Walk the record chain.  Needs the ``.ngc`` index: a header is recognised by its hashes.

    The walk restarts at the next plausible header whenever a chain stalls, so a file made of
    several chained sections is read whole rather than truncated at the first gap.
    """
    import numpy as np

    byhash = {e.hash: e for e in entries if e.hash}
    if not byhash:
        return []
    labels = {h for h, e in byhash.items() if ">" not in e.path}
    words, known = _hash_mask(dgc, set(byhash))
    label = _hash_mask(dgc, labels)[1] if labels else known
    n = len(dgc)
    limit = len(known)

    def header(o: int) -> bool:
        if o < 0 or o + REC_HEADER > n or o + 8 >= limit:
            return False
        size = int(words[o])
        return REC_MIN <= size <= n - o and bool(label[o + 4]) and bool(known[o + 8])

    out: list[Record] = []
    seen_to = 0
    for cand in np.nonzero(known[8:])[0].tolist():
        if cand < seen_to or not header(cand):
            continue
        o = cand
        while header(o):
            size = int(words[o])
            out.append(Record(o, size, int(words[o + 4]), int(words[o + 8]), int(words[o + 12])))
            nxt = o + size
            if header(nxt):
                o = nxt
                continue
            step = next((nxt + g for g in range(1, REC_SLACK + 1) if header(nxt + g)), None)
            if step is None:
                break
            o = step
        seen_to = max(seen_to, o + 1)
    out.sort(key=lambda r: r.offset)
    return out


# -- meshes -------------------------------------------------------------------------------
#
# A TMESH payload is three vertex streams followed by triangle strips::
#
#     +116  u32 count, then count * (f32 x, y, z)     positions
#           u32 count, then count * (f32 u, v)        texture coordinates
#           u32 count, then count * (f32 x, y, z)     normals - exactly unit length
#           u32 strips, then per strip:
#               u32 count, count * u16 index, u32 tag, u8 mode
#           strips * f32                              one value per strip
#
# Both modes seen (1 and 2) are triangle strips: scored as strips, adjacent face normals agree
# at 0.82 and 0.81; scored as fans, at -0.66 and -0.38.  The indices are into the **position**
# stream and stay inside it on 51 of 51 meshes - and the normals are unit length to 8e-07 across
# all of them, which is what says these three streams have been read correctly.
#
# Which stream indexes the texture coordinates and normals is NOT established: there are further
# index lists after the strips, and the first of them reaches 356 where the file declares 354
# texture coordinates, so the obvious reading is wrong.  This reads positions only.

#: the vertex count sits at a fixed offset in every TMESH record
MESH_VERTEX_COUNT = 116
#: u32 tag then u8 mode after each strip's indices
STRIP_TRAILER = 5
#: a strip longer than this means the parse has come off the rails
STRIP_MAX = 4096


class TotemError(ValueError):
    """The record does not read as a mesh."""


@dataclass(frozen=True)
class Strip:
    indices: tuple
    tag: int
    mode: int


@dataclass(frozen=True)
class Mesh:
    positions: object  # (n, 3) float32
    uvs: object  # (n, 2) float32
    normals: object  # (n, 3) float32
    strips: list

    def triangles(self) -> list:
        """Strips flattened, dropping the degenerate joins that carry the winding across."""
        out = []
        for s in self.strips:
            ix = s.indices
            for i in range(len(ix) - 2):
                tri = (ix[i], ix[i + 1], ix[i + 2]) if i % 2 == 0 else (ix[i + 1], ix[i], ix[i + 2])
                if tri[0] != tri[1] and tri[1] != tri[2] and tri[0] != tri[2]:
                    out.append(tri)
        return out


def mesh(dgc: bytes, rec: Record) -> Mesh:
    import numpy as np

    end = rec.end
    o = rec.offset + MESH_VERTEX_COUNT
    if o + 4 > end:
        raise TotemError("record too small to hold a vertex count")

    def stream(at: int, width: int):
        count = struct.unpack_from(">I", dgc, at)[0]
        stop = at + 4 + count * 4 * width
        if count > 1 << 20 or stop > end:
            raise TotemError(f"a stream of {count} x {width} floats runs past the record")
        return np.frombuffer(dgc, ">f4", count * width, at + 4).reshape(-1, width), stop

    positions, o = stream(o, 3)
    uvs, o = stream(o, 2)
    normals, o = stream(o, 3)
    if o + 4 > end:
        raise TotemError("no strip count")
    n_strips = struct.unpack_from(">I", dgc, o)[0]
    o += 4
    strips = []
    for _ in range(n_strips):
        if o + 4 > end:
            raise TotemError("the strip list runs past the record")
        count = struct.unpack_from(">I", dgc, o)[0]
        o += 4
        if count > STRIP_MAX or o + 2 * count + STRIP_TRAILER > end:
            raise TotemError(f"a strip of {count} indices runs past the record")
        idx = struct.unpack_from(f">{count}H", dgc, o)
        o += 2 * count
        strips.append(Strip(idx, struct.unpack_from(">I", dgc, o)[0], dgc[o + 4]))
        o += STRIP_TRAILER
    worst = max((max(s.indices) for s in strips if s.indices), default=-1)
    if worst >= len(positions):
        raise TotemError(f"index {worst} outside {len(positions)} positions")
    return Mesh(positions, uvs, normals, strips)
