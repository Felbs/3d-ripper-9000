"""Sonic Heroes .one archives (GameCube / PS2 / PC): a RenderWare-stamped file table plus
PRS-compressed members. Checked against the Sonic Heroes GameCube disc (735 archives).

  u32 0            u32 file size - 12          u32 RW library id (0x1400FFFF)
  u32 1            u32 0x4000 (name table size) u32 RW library id
  256 x char[64]   member names (entries 0 and 1 are blank)
  members:         u32 name index, u32 compressed size, u32 RW library id, PRS data
A few archives (coverOpen*.one) drop the first three words: u32 1, u32 0x4000, id, names...
"""

from __future__ import annotations

import struct

from dcrip.formats import prs
from gcrip.formats import prs as sega_prs

NAME_COUNT = 256
NAME_LEN = 64


V060 = b"One Ver 0.60"


def is_one(name: str, head: bytes) -> bool:
    if not name.lower().endswith(".one") or len(head) < 24:
        return False
    if head[12:24] == V060:
        return True
    a, b, c, d, e, f = struct.unpack_from("<6I", head, 0)
    if a == 0 and d == 1 and e == NAME_COUNT * NAME_LEN and (c & 0xFFFF) == 0xFFFF:
        return True
    return a == 1 and b == NAME_COUNT * NAME_LEN and (c & 0xFFFF) == 0xFFFF


def _expand_v060(data: bytes) -> list[tuple[str, bytes]]:
    """Shadow the Hedgehog: ``u32 0, u32 size - 12, u32 RW id, "One Ver 0.60", u32 0, u32
    count`` padded with 0xcd to 0xb0, then 56-byte entries ``char name[44], u32 unpacked
    size, u32 offset, u32 compressed (1 = PRS)``; member sizes run to the next offset."""
    count = struct.unpack_from("<I", data, 0x1C)[0]
    entries = []
    for i in range(min(count, 4096)):
        o = 0xB0 + i * 56
        if o + 56 > len(data):
            break
        name = data[o : o + 44].split(b"\0")[0].decode("latin-1", "replace")
        size, off, comp = struct.unpack_from("<3I", data, o + 44)
        if name and off < len(data):
            entries.append((name, size, off, comp))
    entries.sort(key=lambda e: e[2])
    out = []
    for i, (name, size, off, comp) in enumerate(entries):
        # every member starts with a 12-byte slot (the old name index / size / RW id
        # header, now unused); the PRS stream follows and may run into the next slot
        end = entries[i + 1][2] + 12 if i + 1 < len(entries) else len(data)
        blob = data[off + 12 : end]
        if comp:
            try:
                blob = sega_prs.decompress(blob, size or None)
            except Exception:  # noqa: BLE001
                continue
        out.append((name, blob[:size] if size else blob))
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if data[12:24] == V060:
        return _expand_v060(data)
    a = struct.unpack_from("<I", data, 0)[0]
    names_off = 0x18 if a == 0 else 0x0C
    names = []
    for i in range(NAME_COUNT):
        o = names_off + i * NAME_LEN
        names.append(data[o : o + NAME_LEN].split(b"\0")[0].decode("latin-1"))
    off = names_off + NAME_COUNT * NAME_LEN
    out = []
    seen: dict[str, int] = {}
    while off + 12 <= len(data):
        idx, size, _lib = struct.unpack_from("<3I", data, off)
        off += 12
        if size == 0 or off + size > len(data):
            break
        name = names[idx] if idx < NAME_COUNT and names[idx] else f"entry{idx}"
        n = seen.get(name, 0)
        seen[name] = n + 1
        if n:
            stem, dot, ext = name.rpartition(".")
            name = f"{stem}~{n}.{ext}" if dot else f"{name}~{n}"
        out.append((name, prs.decompress(data[off : off + size])))
        off += size
    return out
