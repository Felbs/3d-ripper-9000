"""Konami ``LPAC`` packs (TMNT 2: Battle Nexus, TMNT 3: Mutant Nightmare - members of the AFS
``TMNT.DAT``): ``"LPAC" | u32 record count | 0xcd x 56`` then records of ``u32 kind | u32 size
| u32 | u32 | char name[48]`` followed by ``size`` bytes of a little-endian RenderWare stream
(Konami texture pack 0x23, clump 0x10, world 0x0b, animation 0x1b ...).  Expanded to named
members so the renderware plugin and its texture index pick them up."""

from __future__ import annotations

import re
import struct

NAME = "lpac"
MAGIC = b"LPAC"
_EXT = {0x23: "txd", 0x10: "dff", 0x0B: "pac", 0x1B: "anm", 0x16: "txd"}


def is_container(name: str, head: bytes) -> bool:
    return head[:4] == MAGIC and len(head) >= 8 and 0 < struct.unpack_from("<I", head, 4)[0] < 65536


_HEADER = re.compile(rb"[\x01-\x08]\x00\x00\x00.{4}\x00{8}[A-Za-z0-9_]", re.S)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Records are found by their header signature (kind 1-8, size, two zero words, ASCII
    name); 0xcd padding and 0x80-byte index blocks sit between them."""
    if data[:4] != MAGIC:
        return []
    out = []
    seen: dict[str, int] = {}
    p = 0x40
    while p + 0x40 < len(data):
        m = _HEADER.search(data, p)
        if not m:
            break
        o = m.start()
        _kind, size = struct.unpack_from("<2I", data, o)
        if size == 0 or o + 0x40 + size > len(data):
            p = o + 4
            continue
        name = data[o + 16 : o + 64].split(b"\x00")[0].decode("latin-1", "replace")
        hdr = 0x40  # TMNT 2; TMNT 3 records carry a 0x80-byte header
        if (
            o + 0x80 + 12 <= len(data)
            and not _rw_header(data, o + 0x40)
            and _rw_header(data, o + 0x80)
        ):
            hdr = 0x80
        body = data[o + hdr : o + hdr + size]
        if len(body) >= 12:
            rtype = struct.unpack_from("<I", body, 0)[0]
            ext = _EXT.get(rtype, "bin")
            full = f"{name}.{ext}"
            if full in seen:
                seen[full] += 1
                full = f"{name}_{seen[full]}.{ext}"
            else:
                seen[full] = 0
            out.append((full, body))
        p = o + hdr + size
    return out


def _rw_header(data: bytes, o: int) -> bool:
    t, size, lib = struct.unpack_from("<3I", data, o)
    new_style = (lib & 0xFFFF) == 0xFFFF and lib >> 16 <= 0x3FFF
    return (
        0 < t < 0x100 and 0 < size <= len(data) and (new_style or 0x1800_0000 <= lib < 0x1C10_0000)
    )


# see the note in gcrip/plugins/afs.py: a container is only registered when it also carries a
# detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
