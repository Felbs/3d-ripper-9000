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
"""

from __future__ import annotations

from dataclasses import dataclass

from gcrip.formats import png

MAX_MEMBERS = 65536
MIN_PNG = 64  # a PNG smaller than this is a false hit, not an image


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


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return [(m.name, data[m.offset : m.offset + m.size]) for m in members(data)]
