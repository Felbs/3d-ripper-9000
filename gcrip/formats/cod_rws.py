"""Call of Duty: Finest Hour's ``.rws`` - RenderWare sections behind an 8-byte header each.

The disc reports **21 models** and holds 231 ``.rws`` totalling 582 MB.  Two different files
share the extension:

* the big ones - ``NGC_2s1.rws`` is 299 MB - open ``0x080D`` and are the streamed audio that
  ``docs/formats/rws-is-audio.md`` describes.  Nothing to rip.
* the ``s_*.rws`` are **level geometry**, and they are ordinary RenderWare behind a header so
  small it is easy to miss::

      u32 kind      0, 1, 2 ... for the WORLDs, 4 for the texture dictionary
      u32 size      of the RenderWare chunk that follows, header included
      ... a stock RenderWare chunk: TEXDICT (0x16) or WORLD (0x0B) ...

  repeated to the end of the file.

`plugins/renderware.py` declines the file because byte 0 is not a chunk id, and reads every
section happily once it is handed one.  On ``s_1.rws`` - 509,974 bytes - the walk finds **four
sections and lands on 509,970**, the last four bytes being padding, and the three WORLDs give
**14,957 triangles**.

The identity is the walk: `at += 8 + size` from byte 0 has to reach the end of the file, within
a padding word, and every section has to open on a RenderWare chunk carrying a 3.x version
stamp.  The audio files fail it at the first section - `0x080D`'s size is larger than the file -
so the two kinds cannot be confused.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

#: u32 kind, u32 size
HEADER = 8
#: a RenderWare chunk header inside it
CHUNK = 12
#: RenderWare 3.x version stamps, high half
STAMPS = (0x1800, 0x1801, 0x1802, 0x1803)
#: the ids these files carry
TEXDICT, WORLD = 0x16, 0x0B
#: trailing bytes the walk may leave
MAX_PAD = 16
MAX_SECTIONS = 1 << 12
#: what each id is called when the section comes out as a file
EXT = {TEXDICT: "txd", WORLD: "bsp", 0x10: "dff"}


@dataclass(frozen=True)
class Section:
    kind: int
    offset: int  # of the RenderWare chunk, past the 8-byte header
    size: int
    ident: int

    @property
    def end(self) -> int:
        return self.offset + self.size


def sections(data: bytes) -> list[Section]:
    """Every section, or nothing when the walk does not account for the file."""
    out: list[Section] = []
    at = 0
    n = len(data)
    while at + HEADER + CHUNK <= n and len(out) < MAX_SECTIONS:
        kind, size = struct.unpack_from("<2I", data, at)
        if not 0 < size <= n - at - HEADER:
            break
        ident, csize, version = struct.unpack_from("<3I", data, at + HEADER)
        if (version >> 16) not in STAMPS or csize + CHUNK > size:
            return []
        out.append(Section(kind, at + HEADER, size, ident))
        at += HEADER + size
    if not out or n - at > MAX_PAD:
        return []
    return out


def is_cod_rws(head: bytes) -> bool:
    """The first section has to open on a stamped RenderWare chunk."""
    if len(head) < HEADER + CHUNK:
        return False
    _kind, size = struct.unpack_from("<2I", head, 0)
    ident, csize, version = struct.unpack_from("<3I", head, HEADER)
    return bool(size) and (version >> 16) in STAMPS and csize + CHUNK <= size


def _walk_accounts_for_the_file(data: bytes):
    if not is_cod_rws(data[: HEADER + CHUNK]):
        return None, "not a sectioned .rws"
    got = sections(data)
    if not got:
        return False, "the walk does not reach the end of the file"
    left = len(data) - got[-1].end
    return left <= MAX_PAD, f"{len(got)} sections, {left} bytes left over"


def _sections_are_renderware(data: bytes):
    got = sections(data)
    if not got:
        return None, "no sections"
    known = sum(1 for s in got if s.ident in EXT)
    return known == len(got), f"{known} of {len(got)} sections are TEXDICT, WORLD or CLUMP"


IDENTITIES = [
    Identity(
        "the section walk accounts for the file",
        "at += 8 + size from byte 0 reaches the end, within a padding word",
        _walk_accounts_for_the_file,
    ),
    Identity(
        "every section is a RenderWare chunk",
        "each section opens on TEXDICT, WORLD or CLUMP with a 3.x stamp",
        _sections_are_renderware,
    ),
]
