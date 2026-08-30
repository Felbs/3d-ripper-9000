"""High Voltage Software ``FSTA`` archives - the ``.jam`` files of The Grim Adventures of Billy
& Mandy and Codename: Kids Next Door (155 across the two discs).  Members open ``HVSI``, the
studio's initials.

Header, little-endian::

    +0   char magic[4]        "FSTA"
    +4   u32 checksum
    +8   u32 directory size
    +12  char compression[16] "none" on every file seen
    +28  u16 name count
    +30  u16 extension count
    +32  char names[count][8]      fixed 8-byte, NUL-padded: ART, AUDIO, BBAY4, CAST, ...
    ...  char exts[count][4]       fixed 4-byte: "", AGD, AGM, AGS, AGT, ... GMS, MNG, TPL, VFX

A member is named by a pair of indexes into those two tables, so the file name is
``<name>.<ext>`` - and one of the extensions is ``TPL``, Nintendo's texture format, which gcrip
already decodes.

The entry table is **not uniform**: the ``MNG`` group is twelve bytes per entry
(``u16 name | u16 ext | u32 offset | u32 size``) but other groups pack differently, and the
per-group index that would say which is where has not been decoded.  Rather than guess a stride
this reads the directory for anything that satisfies all four constraints at once - both
indexes in range, a non-zero size, an offset past the directory that is **0x800-aligned**, and
the member fitting inside the file.  Members are keyed by offset so a record cannot be counted
twice.

That is a scan rather than a walk, but a strict one, and what it recovers looks right: over 25
archives per disc it finds 699 members on Billy & Mandy and 808 on Kids Next Door, whose first
four bytes are real headers throughout - ``RotT``, ``ISVH``, ``Node``, ``Surf``, ``Set\\r``,
``Stag``, and the TPL magic ``00 20 AF 30`` on every member the extension table calls ``TPL``.

The ``TPL`` members are **not stock Nintendo TPL** and do not decode with
:func:`gcrip.formats.tpl.parse`: the variant carries an extra ``u32`` at +8, so what the normal
reader takes for the image-table offset is zero and the one after it (0x14) is not a table
either.  The image header itself is plain - at 0x18 of the member, ``ZOMBIEG1`` reads
``height 64, width 64, format 0x0e (CMPR), data offset 0x6c`` - and those offsets are relative
to the member, not to the archive.  Finishing that variant is what will turn these two discs'
textures on.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"FSTA"
NAMES_AT = 0x20
NAME_LEN = 8
EXT_LEN = 4
SECTOR = 0x800
MAX_NAMES = 4096
MAX_EXTS = 256


@dataclass
class Entry:
    name: str
    ext: str
    offset: int
    size: int

    @property
    def filename(self) -> str:
        return f"{self.name}.{self.ext}" if self.ext else self.name


def is_fsta(head: bytes) -> bool:
    if len(head) < NAMES_AT or head[:4] != MAGIC:
        return False
    names, exts = struct.unpack_from("<2H", head, 28)
    return 0 < names <= MAX_NAMES and 0 < exts <= MAX_EXTS


def entries(data: bytes) -> list[Entry]:
    if not is_fsta(data[:NAMES_AT]):
        return []
    directory = struct.unpack_from("<I", data, 8)[0]
    count, ext_count = struct.unpack_from("<2H", data, 28)
    ext_at = NAMES_AT + count * NAME_LEN
    table = ext_at + ext_count * EXT_LEN
    if not (table <= directory <= len(data)):
        return []
    names = [
        data[NAMES_AT + i * NAME_LEN : NAMES_AT + (i + 1) * NAME_LEN].split(b"\0")[0]
        for i in range(count)
    ]
    exts = [
        data[ext_at + i * EXT_LEN : ext_at + (i + 1) * EXT_LEN].split(b"\0")[0]
        for i in range(ext_count)
    ]
    found: dict[int, Entry] = {}
    for p in range(table, directory - 11):
        ni, ei, offset, size = struct.unpack_from("<2H2I", data, p)
        if ni >= count or ei >= ext_count or size == 0:
            continue
        if offset < directory or offset % SECTOR or offset + size > len(data):
            continue
        found.setdefault(
            offset,
            Entry(
                names[ni].decode("latin-1", "replace"),
                exts[ei].decode("latin-1", "replace"),
                offset,
                size,
            ),
        )
    return sorted(found.values(), key=lambda e: e.offset)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    seen: dict[str, int] = {}
    for e in entries(data):
        name = e.filename
        n = seen.get(name.lower(), 0)
        seen[name.lower()] = n + 1
        if n:
            stem, _dot, ext = name.rpartition(".")
            name = f"{stem}_{n:03d}.{ext}" if stem else f"{name}_{n:03d}"
        out.append((name, data[e.offset : e.offset + e.size]))
    return out
