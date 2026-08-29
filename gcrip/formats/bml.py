"""Phantasy Star Online (GameCube) BML archives: ``u32 0 | u32 count | u32 LE data offset
hint | ...`` (64-byte header), ``count`` 64-byte entries ``char name[32] | u32 BE packed
size | u32 0 | u32 BE unpacked size | u32 BE texture packed size | u32 BE texture
unpacked size | ...`` and, from 0x800 (the table rounded up), per entry a Sega-PRS stream
of the model (GJCM/GJTL/NJCM Ninja blocks) followed - 32-byte aligned - by the PRS stream
of its GVM texture archive when the texture sizes are non-zero.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import prs


@dataclass
class Member:
    name: str
    offset: int
    packed: int
    size: int
    tex_offset: int
    tex_packed: int
    tex_size: int


def is_bml(head: bytes, size: int | None = None) -> bool:
    if len(head) < 64 or head[:4] != b"\0\0\0\0":
        return False
    count = struct.unpack_from(">I", head, 4)[0]
    if not (0 < count < 4096):
        return False
    if size is not None and 64 + count * 64 > size:
        return False
    name = head[64:96].split(b"\0")[0] if len(head) >= 96 else b"x"
    return bool(name) and all(32 <= c < 127 for c in name)


def _align(v: int, a: int) -> int:
    return (v + a - 1) & ~(a - 1)


def members(data: bytes) -> list[Member]:
    if not is_bml(data[:96], len(data)):
        return []
    count = struct.unpack_from(">I", data, 4)[0]
    p = _align(64 + count * 64, 0x800)
    out = []
    for i in range(count):
        o = 64 + i * 64
        if o + 64 > len(data):
            break
        name = data[o : o + 32].split(b"\0")[0].decode("latin-1", "replace")
        packed, _z, size, tpacked, tsize = struct.unpack_from(">5I", data, o + 32)
        if not name or packed == 0 or p + packed > len(data):
            break
        m = Member(name, p, packed, size, 0, 0, 0)
        p = _align(p + packed, 0x20)
        if tpacked and p + tpacked <= len(data):
            m.tex_offset, m.tex_packed, m.tex_size = p, tpacked, tsize
            p = _align(p + tpacked, 0x20)
        out.append(m)
    return out


def read(data: bytes, off: int, packed: int, size: int) -> bytes:
    raw = data[off : off + packed]
    if raw[:4] in (b"NJCM", b"NJTL", b"GJCM", b"GJTL", b"GVMH"):
        return raw
    return prs.decompress(raw, size or None)
