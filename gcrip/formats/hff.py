"""``HFF`` data files - Aquaman: Battle for Atlantis, Casper and TONKA Rescue Patrol keep one
apiece, 144 to 251 MB, and all three discs produced nothing.

**There is no directory.**  The last four kilobytes of every one of the three is zero, there is
no table at the head, and the file simply begins with its first member: a `PNG` on Aquaman, and
on the other two a text file that starts ``// this file contains the path to the *.obd file``.
So the members are found by **carving**, not by walking a table.

That is only safe for formats with an unambiguous end marker, which is why this reads `PNG` and
nothing else.  A PNG closes with ``IEND`` plus its four CRC bytes, so a member's extent is
exact rather than inferred - carving on a start magic alone (`BM` was the tempting one, at 303
apparent hits in a 32 MB sample) produces garbage, because two bytes match everywhere.

Sampling 32 MB spread through each file: Aquaman holds roughly 200 PNGs per 8 MB - 97 of 97
carved from one window decoded, at 16x16 up to 256x1024 - while Casper has none and TONKA five.
Casper's bulk reads as `f32` unit vectors, so its geometry is there in some other form.

**That other form is RenderWare** (2026-09-03).  ``casperGCN.elf`` keeps its symbol table and
it is RW 3.0's: ``readGeometryNative``, ``WorldBuildMeshAtomicSector``, ``SkinGeometryRead``,
``_rxDlVertexFmt``.  The ``.hff`` is a run of RenderWare streams - little-endian chunk headers
with the 0x0800FFFF / 0x0C02FFFF library stamps - texture dictionaries, clumps, a world, and
bare rasters (type 0x15), back to back with the odd stretch of other data between.  So the
carver walks chunk headers too: a top-level ``TEXDICT`` / ``CLUMP`` / ``WORLD`` / raster whose
size fits is a member, the next begins at its end, and a header that does not read resyncs on
the next plausible one.  Casper's first 16 MB give a 13,650-triangle world with 78 textures
bound and 40 clumps that the RenderWare plugin reads as they are.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import png

MAX_MEMBERS = 65536
MIN_PNG = 64  # a PNG smaller than this is a false hit, not an image
RW_TYPES = {0x10: "dff", 0x0B: "bsp", 0x16: "txd", 0x15: "rwtex"}
RW_LIBS = {0x0800, 0x0C02, 0x1003, 0x1400, 0x1803, 0x1C02, 0x1C01, 0x1001}
MIN_RW = 16


@dataclass
class Member:
    name: str
    offset: int
    size: int


def is_hff(name: str, head: bytes) -> bool:
    return name.lower().endswith(".hff") and len(head) >= 8


def members(data: bytes) -> list[Member]:
    out: list[Member] = []
    at = 0
    while len(out) < MAX_MEMBERS:
        start = data.find(png.MAGIC, at)
        if start < 0:
            break
        stop = data.find(png.END, start)
        if stop < 0:
            break
        end = stop + len(png.END)
        if end - start >= MIN_PNG and png.is_png(data[start : start + 32]):
            out.append(Member(f"image_{len(out):05d}.png", start, end - start))
        at = end
    return out


def _rw_header(data: bytes, at: int) -> tuple[int, int] | None:
    """(type, size) when a top-level RenderWare chunk header sits at ``at``."""
    if at + 12 > len(data):
        return None
    t, sz, lib = struct.unpack_from("<3I", data, at)
    if t not in RW_TYPES or lib & 0xFFFF != 0xFFFF or (lib >> 16) not in RW_LIBS:
        return None
    if sz < MIN_RW or at + 12 + sz > len(data):
        return None
    return t, sz


def rw_members(data: bytes) -> list[Member]:
    """Every RenderWare stream in the file, walked header to header from the first one."""
    out: list[Member] = []
    at = 0
    n = len(data)
    while at + 12 <= n and len(out) < MAX_MEMBERS:
        got = _rw_header(data, at)
        if got is None:
            at += 4  # resync: the streams are 4-byte aligned
            continue
        t, sz = got
        out.append(Member(f"stream_{len(out):05d}.{RW_TYPES[t]}", at, 12 + sz))
        at += 12 + sz
        at += -at % 4
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    found = members(data) + rw_members(data)
    found.sort(key=lambda m: m.offset)
    return [(m.name, data[m.offset : m.offset + m.size]) for m in found]
