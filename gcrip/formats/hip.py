"""HIP / HOP archives (Heavy Iron's asset packs: SpongeBob SquarePants: Battle for Bikini Bottom,
The Incredibles, Scooby-Doo! Night of 100 Frights ...). Checked against the BfBB GameCube disc.

Big-endian FourCC blocks of (tag, u32 size, body):
  HIPA (empty)   PACK { PVER PFLG PCNT PCRT PMOD PLAT }
  DICT { ATOC { AINF, AHDR... }, LTOC {...} }   STRM { DHDR, DPAK: the asset bytes }
Every AHDR is: u32 asset id, FourCC type (MODL, RWTX, JSP, ANIM, SNDS, ...), u32 absolute file
offset, u32 size, u32 plus, u32 flags, then an ADBG block: u32 alignment, C string name, u32
checksum.  MODL assets are RenderWare clumps, RWTX are one-texture TXDs, JSP assets are either
the level clumps (RW clump stream) or the JSP info block (0xBEEF01 chunks).
"""

from __future__ import annotations

import struct


def is_hip(head: bytes) -> bool:
    return head[:4] == b"HIPA" and head[8:12] == b"PACK"


def _blocks(data: bytes, off: int, end: int):
    while off + 8 <= end:
        tag = data[off : off + 4]
        size = struct.unpack_from(">I", data, off + 4)[0]
        yield tag, off + 8, min(off + 8 + size, end)
        off += 8 + size


def assets(data: bytes) -> list[tuple[int, str, str, int, int]]:
    """(asset id, type, name, offset, size) for every AHDR."""
    out = []
    for tag, o, e in _blocks(data, 0, len(data)):
        if tag != b"DICT":
            continue
        for t2, o2, e2 in _blocks(data, o, e):
            if t2 != b"ATOC":
                continue
            for t3, o3, e3 in _blocks(data, o2, e2):
                if t3 != b"AHDR" or e3 - o3 < 24:
                    continue
                aid, typ, off, size, _plus, _flags = struct.unpack_from(">I4sIIII", data, o3)
                name = ""
                for t4, o4, e4 in _blocks(data, o3 + 24, e3):
                    if t4 == b"ADBG" and e4 - o4 > 4:
                        name = data[o4 + 4 : e4].split(b"\0")[0].decode("latin-1")
                out.append((aid, typ.decode("latin-1").strip(), name, off, size))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Inner paths are '<TYPE>/<asset name>' (names carry the tool's extension: .dff, .RW3 ...)."""
    out = []
    seen: dict[str, int] = {}
    for aid, typ, name, off, size in assets(data):
        if off + size > len(data) or size == 0:
            continue
        base = name or f"{aid:08x}"
        path = f"{typ}/{base}"
        n = seen.get(path, 0)
        seen[path] = n + 1
        if n:
            path = f"{typ}/{base}~{n}"
        out.append((path, data[off : off + size]))
    return out
