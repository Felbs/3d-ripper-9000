"""The N64 ROM container: header, the DMA file table, and Yaz0-compressed file access.

An N64 cartridge image has no filesystem.  Zelda-era Nintendo titles instead ship a table
called *dmadata* mapping each file's virtual address range (VROM - what game pointers refer
to) onto its physical location in the ROM, with Yaz0 compression marked per file.

Two things about that table are worth knowing before reading this module, because both cost
real time to rediscover:

* **The table states its own size.**  Entry #2 describes dmadata itself, so
  ``(vromEnd - vromStart) // 16`` is an authoritative slot count.  Walking the table until
  the entries stop looking plausible undercounts it - on Ocarina of Time such a walk stops at
  1,030 of the real 1,509 files, and on Majora's Mask at 1,158 of 1,549.
* **Majora's Mask marks deleted files.**  17 of its entries carry
  ``promStart == promEnd == 0xFFFFFFFF`` for assets dropped from the GameCube release.  A
  validity test that requires a physical address inside the ROM rejects those and splits the
  table in half.

Verified against the three ROMs on the Zelda GameCube discs: Ocarina of Time (1,509 files,
1,455 compressed), Master Quest (1,509 / 1,455) and Majora's Mask (1,549 files of which 17
deleted, 1,510 compressed).  gcrip's Yaz0 decoder handles all 2,965 compressed files with no
size disagreement - Nintendo used the same codec on both consoles.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from gcrip.formats import yaz0

Z64_MAGIC = b"\x80\x37\x12\x40"  # big-endian; .v64 and .n64 byte orders are byte-swapped
HEADER_TITLE = slice(0x20, 0x34)
HEADER_CODE = slice(0x3B, 0x3F)
ENTRY = struct.Struct(">4I")
ENTRY_SIZE = 16
DELETED = 0xFFFFFFFF
#: dmadata's own entry.  0 is the boot segment, 1 the code before the table, 2 the table.
SELF_ENTRY = 2
MAX_SLOTS = 8192


class RomError(Exception):
    pass


@dataclass(frozen=True)
class RomFile:
    """One entry of the DMA table."""

    index: int
    vrom_start: int
    vrom_end: int
    prom_start: int
    prom_end: int
    name: str = ""

    @property
    def size(self) -> int:
        """Size of the file once decompressed - VROM is always the uncompressed view."""
        return self.vrom_end - self.vrom_start

    @property
    def compressed(self) -> bool:
        return self.prom_end != 0 and not self.deleted

    @property
    def deleted(self) -> bool:
        """Majora's Mask keeps table slots for assets cut from the GameCube release."""
        return self.prom_start == DELETED

    @property
    def label(self) -> str:
        return self.name or f"file_{self.index:04d}"


def is_z64(head: bytes) -> bool:
    return head[:4] == Z64_MAGIC


def _byteswap(data: bytes) -> bytes:
    """.v64 images store 16-bit words the other way round; .n64 images 32-bit words."""
    buf = bytearray(data)
    if data[:4] == b"\x37\x80\x40\x12":
        buf[0::2], buf[1::2] = data[1::2], data[0::2]
        return bytes(buf)
    if data[:4] == b"\x40\x12\x37\x80":
        buf[0::4], buf[1::4], buf[2::4], buf[3::4] = (
            data[3::4],
            data[2::4],
            data[1::4],
            data[0::4],
        )
        return bytes(buf)
    return data


class Rom:
    """A loaded ROM: header fields, the DMA table, and file bytes on demand."""

    def __init__(self, data: bytes, name: str = ""):
        data = _byteswap(data)
        if not is_z64(data):
            raise RomError(f"not an N64 ROM (header {data[:4].hex(' ')})")
        self.data = data
        self.name = name
        self.title = data[HEADER_TITLE].decode("ascii", "replace").strip()
        self.code = data[HEADER_CODE].decode("ascii", "replace")
        self.crc1, self.crc2 = struct.unpack_from(">2I", data, 0x10)
        self.dma_offset = find_dma_table(data)
        self.files = read_dma_table(data, self.dma_offset)
        self._cache: dict[int, bytes] = {}

    # -- access ---------------------------------------------------------------

    def read(self, f: RomFile) -> bytes:
        """The file's bytes, decompressed if it is Yaz0.

        Raises RomError for a deleted entry - the bytes genuinely are not in the ROM.
        """
        if f.deleted:
            raise RomError(f"{f.label}: deleted entry (no data in this build)")
        hit = self._cache.get(f.index)
        if hit is not None:
            return hit
        if f.compressed:
            blob = self.data[f.prom_start : f.prom_end]
            if not yaz0.is_yaz0(blob):
                raise RomError(f"{f.label}: marked compressed but no Yaz0 magic")
            out = yaz0.decompress(blob)
            # the table declares the decompressed size; a mismatch means we mis-read the entry
            if len(out) != f.size:
                raise RomError(f"{f.label}: Yaz0 gave {len(out)} bytes, table says {f.size}")
        else:
            out = self.data[f.prom_start : f.prom_start + f.size]
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[f.index] = out
        return out

    def by_name(self, name: str) -> RomFile | None:
        for f in self.files:
            if f.name == name:
                return f
        return None

    def at_vrom(self, addr: int) -> RomFile | None:
        """The file containing a VROM address - how the game's own pointers resolve."""
        for f in self.files:
            if f.vrom_start <= addr < f.vrom_end:
                return f
        return None

    @property
    def live(self) -> list[RomFile]:
        return [f for f in self.files if not f.deleted]

    def summary(self) -> dict:
        live = self.live
        return {
            "title": self.title,
            "code": self.code,
            "crc": f"{self.crc1:08x}/{self.crc2:08x}",
            "bytes": len(self.data),
            "dma_offset": self.dma_offset,
            "files": len(self.files),
            "deleted": sum(1 for f in self.files if f.deleted),
            "compressed": sum(1 for f in live if f.compressed),
            "raw": sum(1 for f in live if not f.compressed),
            "named": sum(1 for f in self.files if f.name),
        }

    @classmethod
    def open(cls, path: str | Path) -> Rom:
        p = Path(path)
        return cls(p.read_bytes(), name=p.name)


# -- the DMA table ------------------------------------------------------------


def _plausible(vs: int, ve: int, ps: int, pe: int, size: int) -> bool:
    """Is this 16-byte record a usable table entry?"""
    if vs == ve == ps == pe == 0:
        return False  # unused slot, not an error
    if ps == DELETED and pe == DELETED:
        return vs < ve <= size  # deleted file: the VROM range is still declared
    if not (vs < ve <= size):
        return False
    if pe == 0:
        return ps + (ve - vs) <= size  # stored raw at prom_start
    return ps < pe <= size


def find_dma_table(data: bytes) -> int:
    """Locate dmadata by structure rather than by a per-version constant.

    The first entry describes the boot segment: it starts at VROM 0, is stored raw at
    physical 0, and is small.  Several places in a ROM look like that, so candidates are
    scored by how many well-formed entries follow, and the winner must also be
    self-consistent - entry #2 has to describe a table that reaches the candidate itself.
    """
    size = len(data)
    best = (0, -1)
    for off in range(0, min(size, 0x400000), ENTRY_SIZE):
        vs, ve, ps, pe = ENTRY.unpack_from(data, off)
        if vs != 0 or ps != 0 or pe != 0 or not (0 < ve < 0x100000):
            continue
        run = 0
        while off + (run + 1) * ENTRY_SIZE <= size:
            e = ENTRY.unpack_from(data, off + run * ENTRY_SIZE)
            if not _plausible(*e, size):
                break
            run += 1
        if run > best[0]:
            best = (run, off)
    run, off = best
    if off < 0 or run < 8:
        raise RomError("no DMA table found")
    return off


def _slot_count(data: bytes, offset: int) -> int:
    """How many slots the table has, from the entry that describes the table itself."""
    vs, ve, _ps, _pe = ENTRY.unpack_from(data, offset + SELF_ENTRY * ENTRY_SIZE)
    span = ve - vs
    if 0 < span // ENTRY_SIZE <= MAX_SLOTS and offset >= vs:
        return span // ENTRY_SIZE
    # self-description did not check out; fall back to walking, and say so by returning
    # the walked length rather than silently pretending it is authoritative
    run = 0
    while offset + (run + 1) * ENTRY_SIZE <= len(data):
        e = ENTRY.unpack_from(data, offset + run * ENTRY_SIZE)
        if not _plausible(*e, len(data)):
            break
        run += 1
    return run


def read_dma_table(data: bytes, offset: int) -> list[RomFile]:
    """Every real entry of the table at *offset* (unused all-zero slots dropped)."""
    slots = _slot_count(data, offset)
    out: list[RomFile] = []
    for i in range(slots):
        p = offset + i * ENTRY_SIZE
        if p + ENTRY_SIZE > len(data):
            break
        vs, ve, ps, pe = ENTRY.unpack_from(data, p)
        if vs == ve == ps == pe == 0:
            continue
        out.append(RomFile(len(out), vs, ve, ps, pe))
    return out
