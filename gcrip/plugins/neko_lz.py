"""Cocoto ``.GCN`` / ``.pc`` (gcrip.formats.neko_lz): a container of one member - the file
unpacked - so the scanners see the level rather than the LZ stream."""

from __future__ import annotations

import struct

from gcrip.formats import neko_lz

NAME = "neko_lz"
EXTENSIONS = (".gcn", ".pc")


def is_container(name: str, head: bytes) -> bool:
    # the sniff has no file size, so this accepts a header whose unpacked count exceeds its
    # packed one; expand() checks the packed count against the real size
    if not name.lower().endswith(EXTENSIONS) or len(head) < 8:
        return False
    packed, unpacked = struct.unpack_from(">2I", head, 0)
    return 0 < packed < unpacked <= neko_lz.MAX_UNPACKED


def expand(data: bytes) -> list[tuple[str, bytes]]:
    blob = neko_lz.unpack(data)
    return [("unpacked.bin", blob)] if blob else []


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
