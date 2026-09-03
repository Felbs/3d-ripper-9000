"""Hudson ``hfs`` archives (Frogger: Ancient Shadow's ``gamedata.bin``) as a container: every
member is decoded from PRS1 (``gcrip.formats.prs1``) and split into its top-level RenderWare
chunks, so clumps, worlds and platform-independent texture dictionaries reach
``plugins.renderware`` under their own names.  Stored members (RenderWare audio, 0x0809) and
non-RenderWare payloads are dropped."""

from __future__ import annotations

import struct

from gcrip.formats import frogger_hfs, prs1
from gcrip.formats import rwstream as rw

NAME = "frogger_hfs"

CLUMP = 0x10
WORLD = 0x0B
PITEXDICT = 0x23
GROUP_START = 0x29
GROUP_END = 0x2A
EXT = {CLUMP: "dff", WORLD: "bsp", PITEXDICT: "txd"}


def is_container(name: str, head: bytes) -> bool:
    return frogger_hfs.is_hfs(head)


def split(blob: bytes) -> list[tuple[int, bytes, str]]:
    """(chunk type, chunk bytes, group name) for every top-level model/texture chunk."""
    out = []
    group = ""
    p = 0
    n = len(blob)
    while p + 12 <= n:
        t, size, lib = struct.unpack_from("<3I", blob, p)
        if p + 12 + size > n or (lib >> 16) not in (0x1803, 0x1C02, 0x1C01, 0x1400, 0x0C02, 0x1003, 0x1001):
            break
        if t == GROUP_START:
            strings = [k for k in rw.chunks(blob, p + 12, p + 12 + size) if k.type == rw.STRING]
            group = rw.read_string(blob, strings[0]) if strings else ""
        elif t == GROUP_END:
            group = ""
        elif t in EXT:
            out.append((t, blob[p : p + 12 + size], group))
        p += 12 + size
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for m in frogger_hfs.members(data):
        if m.offset + m.size > len(data):
            continue
        blob = data[m.offset : m.offset + m.size]
        if prs1.is_prs1(blob):
            try:
                blob = prs1.unpack(blob)
            except prs1.Prs1Error:
                continue
        stem = f"{m.block:02d}_{m.index:04d}"
        for k, (t, chunk, group) in enumerate(split(blob)):
            tag = f"{stem}_{k}" + (f"_{group}" if group else "")
            out.append((f"{tag}.{EXT[t]}", chunk))
    return out


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
