"""Blitz Games ``.gcp`` packs (Pac-Man World 3, Bratz, Bad Boys, Cubix, Fairly OddParents,
Frogger Ancient Shadow, Chicken Little, ...): a small header then uncompressed "packages"
at 0x800-aligned offsets, each opening with ``01 69 07`` and a build stamp
(``dd/mm/yyyy at hh:mm:ss by <user>``) followed by Blitz's object-serialisation stream.
The stream itself is not decoded yet; splitting the pack into packages lets the GX scanner
(gcrip.plugins.gx) pull the display lists out of the sector packages."""

from __future__ import annotations

import re
import struct

NAME = "blitz"

_STAMP = re.compile(rb"\x01\x69\x07\d\d/\d\d/\d{4} at \d\d:\d\d:\d\d by ")
_ALIGN = 0x800


def is_container(name: str, head: bytes) -> bool:
    if not name.lower().endswith(".gcp") or len(head) < 16:
        return False
    hdr, zero = struct.unpack_from(">II", head, 4)
    return zero == 0 and hdr in (0x20, 0x800)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    starts = [m.start() for m in _STAMP.finditer(data) if m.start() % _ALIGN == 0]
    if not starts:
        return []
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(data)
        stamp = data[s + 3 : s + 3 + 48].split(b"\0")[0]
        who = stamp.rsplit(b" by ", 1)[-1].decode("latin-1", "replace")
        out.append((f"pkg{i:03d}_{who}.pkg", data[s:end]))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
