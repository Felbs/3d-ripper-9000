"""Terminal Reality ``.PKG`` packages - the asset side of the POD archives (BloodRayne,
Blowout, RoadKill; see :mod:`gcrip.formats.pod`).

A flat chain of named chunks, with no directory and no offsets to go wrong::

    char magic[4]   "adoY"      - "Yoda" stored back to front
    char tag[4]                 - likewise reversed: "xet1" is 1tex, "fms_" is _smf
    u32  size                   - of the payload, not counting this 76-byte header
    char name[64]               - NUL-padded, e.g. "WHITE.TIF", "SHELL_MG.SMF"
    u8   payload[size]

The chain ends with a zero-length ``oMoN`` chunk - "NoMo", no more - and because every chunk
carries its own length the walk either lands exactly on the terminator or the file is not a
package.  That makes the format self-verifying, and it does verify: Blowout's
``GCB_11_CREDITS.PKG`` walks 189 chunks to its final byte, BloodRayne's ``GC_BOILERROOM.PKG``
59, RoadKill's ``GC_UI.PKG`` 40.

Tags seen (read them backwards):

======  ======  =====================================================================
stored  reads   contents
======  ======  =====================================================================
xet1    1tex    a texture in the ``.TEX`` format of :mod:`gcrip.formats.tr_tex`
fms_    _smf    static mesh
mfd_    _dfm    deformable (skinned) mesh
lks_    _skl    skeleton, e.g. ``HERO.SKL``, whose payload names bones (``Bip01 Pelvis``)
lpms    smpl    audio sample (``GCA1``)
fedv    vdef    video
oMoN    NoMo    end of file, zero length
======  ======  =====================================================================

The names are the artists' original file names, which is what lets a texture be matched back
to the ``.tif`` a level's ``.BST`` layout file asks for.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"adoY"
END = b"oMoN"
HEADER = 76
NAME = 64
MAX_CHUNKS = 100000


@dataclass
class Chunk:
    tag: str  # as stored, e.g. "xet1"
    name: str
    offset: int  # of the payload
    size: int

    @property
    def kind(self) -> str:
        """The tag the right way round: "xet1" -> "1tex"."""
        return self.tag[::-1]


def is_pkg(head: bytes) -> bool:
    return len(head) >= HEADER and head[:4] == MAGIC


def chunks(data: bytes) -> list[Chunk]:
    """Every chunk, or [] if the chain does not walk cleanly to the terminator."""
    if not is_pkg(data[:HEADER]):
        return []
    out: list[Chunk] = []
    p = 0
    while p + HEADER <= len(data) and len(out) < MAX_CHUNKS:
        if data[p : p + 4] != MAGIC:
            return []
        tag = data[p + 4 : p + 8]
        size = struct.unpack_from("<I", data, p + 8)[0]
        body = p + HEADER
        if body + size > len(data):
            return []
        if tag == END:
            return out
        name = data[p + 12 : p + 12 + NAME].split(b"\0")[0].decode("latin-1", "replace")
        out.append(Chunk(tag.decode("latin-1", "replace"), name, body, size))
        p = body + size
    return out if p == len(data) else []


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for c in chunks(data):
        name = c.name or f"{c.kind}_{len(out):04d}.bin"
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:  # the same artist file name can appear twice in one package
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[c.offset : c.offset + c.size]))
    return out
