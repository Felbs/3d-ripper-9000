"""``FSYS`` archives (gcrip.formats.fsys) - Pokemon Colosseum and Pokemon XD.  A container
only: members come out under the names the game gives them and go to whichever plugin claims
them."""

from __future__ import annotations

import struct

from gcrip.formats import fsys

NAME = "fsys"


def detect(path: str, head: bytes, size: int) -> bool:
    """A container only; both of these exist so the plugin is registered at all."""
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    return fsys.is_fsys(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Members come out decompressed.  Nearly everything on these discs is `LZSS`."""
    out = []
    seen: dict[str, int] = {}
    for m in fsys.members(data):
        blob = data[m.offset : m.offset + m.size]
        if m.compressed:
            payload = fsys.decompress(blob[fsys.LZSS_HEADER :], m.unpacked)
            if payload is None:
                continue
        else:
            # an uncompressed member repeats its own length first
            payload = blob[4:]
        stem = m.name
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        if n:
            stem = f"{stem}_{n}"
        at = fsys.hsd_offset(payload)
        if at is None:
            out.append((f"{stem}.bin", payload))
            continue
        # a model member carries a whole HAL sysdolphin archive behind a prefix - 3,680 bytes
        # on XD, 64 on Colosseum - so it comes out under a `.dat` name and the `hsd` plugin,
        # which has read that container all along, takes it from there
        size = struct.unpack_from(">I", payload, 0)[0]
        out.append((f"{stem}.dat", payload[at : at + size]))
        if at:
            out.append((f"{stem}_head.bin", payload[:at]))
    return out
