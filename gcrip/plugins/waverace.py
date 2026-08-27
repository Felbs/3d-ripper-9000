"""Wave Race: Blue Storm (GWRE01): container expansion for NST's offset-table bundles.

``WRdata/**/*.env|.wea|.all|.bin`` are u32-count offset tables (``gcrip.formats.waverace_pack``).
Expanding them hands the manifest the TPL textures inside (course textures, HUD, animals) as
``<n>.tpl`` and every other member as ``<n>.<kind>`` so nested tables expand again.

Model side: the ``geo`` members (also the loose ``Misc/*.geo``) are NST's own scene format -
u16 counts (materials, nodes, meshes, ...), a u32 section table, RGBA8 material colours,
f32 node transforms, then index/vertex blobs.  The vertex and display-list layout is not
decoded here, so no Scenes are produced; ``detect`` never matches.  ``.mvm`` are replay
movies and ``.adp`` audio.
"""

from __future__ import annotations

import struct

from gcrip.formats import tpl
from gcrip.formats import waverace_pack as wp
from ripcore.scene import Scene

NAME = "waverace"

_TABLE_EXT = (".env", ".wea", ".all", ".bin", ".pak")


def is_container(name: str, head: bytes) -> bool:
    low = name.lower()
    if not low.endswith(_TABLE_EXT) or len(head) < 8:
        return False
    if head[:4] == tpl.MAGIC:
        return False
    # cheap sniff on the head only: count and the first offsets must be plausible
    (count,) = struct.unpack_from(">I", head, 0)
    if not 0 < count <= wp.MAX_MEMBERS:
        return False
    n = min(count, (len(head) - 4) // 4)
    offs = struct.unpack_from(f">{n}I", head, 4)
    return offs[0] >= 4 + count * 4 and all(b >= a for a, b in zip(offs, offs[1:], strict=False))


def _kind(blob: bytes) -> str:
    if blob[:4] == tpl.MAGIC:
        return "tpl"
    if wp.table_offsets(blob) is not None:
        return "pak"
    if len(blob) >= 0x20 and blob[:2] == b"\0\0":
        counts = struct.unpack_from(">8H", blob, 0)
        (first,) = struct.unpack_from(">I", blob, 0x10)
        if first == 0x20 and counts[0] == 0 and any(counts[1:]):
            return "geo"
    return "bin"


def expand(data: bytes) -> list[tuple[str, bytes]]:
    offs = wp.table_offsets(data)
    if offs is None:
        return []
    out = []
    for i, blob in enumerate(wp.members(data)):
        if not blob:
            continue
        out.append((f"{i:03d}.{_kind(blob)}", blob))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []
