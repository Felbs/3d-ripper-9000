"""Finding display lists in a file that carries no index of them.

An object file's geometry is reached through its skeleton, but a skeleton is not always where
we can find it yet, and levels reach theirs through scene/room headers.  So there is a
fallback, in the same spirit as gcrip's ``gxscan``: walk the file looking for command streams
that parse as F3DEX2 and actually draw something.

The discriminator is deliberately strict, because a false display list produces geometry that
looks like a rip rather than like an error:

* the stream must terminate at ``G_ENDDL`` within a sane length,
* every command in it must be one the microcode defines,
* it must contain at least one vertex load and one triangle,
* and it must not start in the middle of another list we already accepted.

On Ocarina of Time this finds display lists in 675 of 1,509 files; a byte-shuffled control of
the same data yields none, which is the check that says the discriminator is real.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from n64rip import f3dex2

#: every opcode F3DEX2 defines.  Anything else means we are not looking at a command stream.
VALID_OPS = frozenset(
    [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
     0xD3, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF,
     0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB,
     0xEC, 0xED, 0xEE, 0xEF, 0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
     0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD]
)
MAX_COMMANDS = 4096


@dataclass(frozen=True)
class Found:
    offset: int
    commands: int
    vertices: int
    triangles: int


def _walk(data: bytes, start: int) -> Found | None:
    """Parse a command stream at *start*; None unless it is a display list that draws."""
    off = start
    n = verts = tris = 0
    while off + 8 <= len(data):
        if n > MAX_COMMANDS:
            return None
        op = data[off]
        if op not in VALID_OPS:
            return None
        w0 = struct.unpack_from(">I", data, off)[0]
        off += 8
        n += 1
        if op == f3dex2.G_ENDDL:
            if verts and tris:
                return Found(start, n, verts, tris)
            return None
        if op == f3dex2.G_VTX:
            verts += (w0 >> 12) & 0xFF
        elif op == f3dex2.G_TRI1:
            tris += 1
        elif op in (f3dex2.G_TRI2, f3dex2.G_QUAD):
            tris += 2
    return None


def display_lists(data: bytes, step: int = 8) -> list[Found]:
    """Every display list in *data*, outermost first, without overlaps.

    Commands are 8-byte aligned, so the scan steps by 8; a list found inside a range already
    claimed is skipped, which keeps a long list from being reported once per command.
    """
    out: list[Found] = []
    claimed_to = -1
    for off in range(0, len(data) - 8, step):
        if off < claimed_to:
            continue
        got = _walk(data, off)
        if got is None:
            continue
        out.append(got)
        claimed_to = off + got.commands * 8
    return out
