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
