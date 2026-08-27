"""Wave Race: Blue Storm (GWRE01) offset-table containers.

NST packed nearly everything under ``WRdata`` as a plain table: u32 member count, then that
many ascending u32 absolute offsets; each member runs to the next offset (the last to the end
of the file).  Some files pad the header to 0x20 with ``0xCD`` bytes.  ``.env`` (course
environments), ``.wea`` (weather variants), ``.all`` (animal / menu bundles), ``.bin`` (HUD,
signals, textures) all use it, and members nest (a member can itself be a table).

Member payloads seen: TPL textures (``0020AF30``), NST ``geo`` scenes (u16 counts + offset
table, see ``gcrip.plugins.waverace``), animation and placement blobs.
"""

from __future__ import annotations

import struct

MAX_MEMBERS = 4096


def table_offsets(data: bytes) -> list[int] | None:
    """Offsets of the members if ``data`` is an offset-table container, else None."""
    if len(data) < 8:
        return None
    (count,) = struct.unpack_from(">I", data, 0)
    if not 0 < count <= MAX_MEMBERS or 4 + count * 4 > len(data):
        return None
    offs = list(struct.unpack_from(f">{count}I", data, 4))
    if offs[0] < 4 + count * 4 or offs[-1] > len(data):
        return None
    if any(b < a for a, b in zip(offs, offs[1:], strict=False)):
        return None
    return offs


def is_table(head: bytes, size: int) -> bool:
    if len(head) < 8 or size < 8:
        return False
    (count,) = struct.unpack_from(">I", head, 0)
    if not 0 < count <= MAX_MEMBERS or 4 + count * 4 > size:
        return False
    n = min(count, (len(head) - 4) // 4)
    if n < 1:
        return False
    offs = struct.unpack_from(f">{n}I", head, 4)
    if offs[0] < 4 + count * 4 or offs[0] > size:
        return False
    ascending = all(b >= a for a, b in zip(offs, offs[1:], strict=False))
    return ascending and all(o <= size for o in offs)


def members(data: bytes) -> list[bytes]:
    offs = table_offsets(data)
    if offs is None:
        raise ValueError("not an offset-table container")
    out = []
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(data)
        out.append(data[o:end])
    return out
