"""GameCube disc header and FST (file system table) parsing.

Layout (all big-endian), cross-checked against Dolphin master's DiscIO
(DiscUtils.cpp, FileSystemGCWii.cpp, VolumeGC.cpp):

Disc header ("boot.bin", 0x440 bytes):
  0x000  6     game ID (console, 2-char game code, region char, 2-char maker)
  0x006  1     disc number
  0x007  1     disc version / revision
  0x008  1     audio streaming enabled
  0x009  1     stream buffer size
  0x01C  4     magic 0xC2339F3D
  0x020  0x3E0 game title (Dolphin reads 0x60 of it as the internal name)
  0x400  4     debug monitor offset
  0x404  4     debug monitor load address
  0x420  4     main.dol offset
  0x424  4     FST offset
  0x428  4     FST size
  0x42C  4     max FST size (multi-disc games)
  0x430  4     user position, 0x434 user length
bi2.bin at 0x440 (0x2000 bytes): 0x458 holds the region code (0=J, 1=U, 2=E).
Apploader at 0x2440: 0x10-byte date string, sizes at +0x14 / +0x18.

FST: N entries of 12 bytes, then the string table.
  u32  flags<<24 | name_offset   (flags: 0 = file, 1 = directory)
  u32  file offset               (dirs: index of parent entry)
  u32  file size                 (dirs: index of next entry after this dir;
                                  root: total entry count)
There is no offset shift on GameCube (Dolphin's shift of 2 is Wii-only).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FST_ENTRY_SIZE = 12
HEADER_SIZE = 0x440
BI2_OFFSET = 0x440
BI2_SIZE = 0x2000
APPLOADER_OFFSET = 0x2440

_REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL", 3: "NTSC-K"}


@dataclass
class DiscHeader:
    game_id: str
    maker_code: str
    disc_number: int
    revision: int
    audio_streaming: bool
    stream_buffer_size: int
    title: str
    dol_offset: int
    fst_offset: int
    fst_size: int
    fst_max_size: int
    user_position: int
    user_length: int
    region: str = "unknown"
    apploader_date: str = ""

    @property
    def console(self) -> str:
        return self.game_id[0]

    @property
    def region_char(self) -> str:
        return self.game_id[3]


def cstr(b: bytes) -> str:
    """Decode a NUL-terminated Shift-JIS/ASCII string leniently."""
    b = b.split(b"\x00", 1)[0]
    for enc in ("shift_jis", "utf-8"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1")


def parse_header(data: bytes) -> DiscHeader:
    """Parse the disc header. Pass at least 0x2450 bytes to also get the bi2
    region code and the apploader date; 0x440 is enough for the basics."""
    if len(data) < HEADER_SIZE:
        raise ValueError("header data too short")
    game_id = data[0:6].decode("ascii", "replace")
    (
        dol_offset,
        fst_offset,
        fst_size,
        fst_max_size,
        user_position,
        user_length,
    ) = struct.unpack(">6I", data[0x420:0x438])
    hdr = DiscHeader(
        game_id=game_id,
        maker_code=game_id[4:6],
        disc_number=data[6],
        revision=data[7],
        audio_streaming=bool(data[8]),
        stream_buffer_size=data[9],
        title=cstr(data[0x20:0x400]).strip(),
        dol_offset=dol_offset,
        fst_offset=fst_offset,
        fst_size=fst_size,
        fst_max_size=fst_max_size,
        user_position=user_position,
        user_length=user_length,
    )
    if len(data) >= 0x45C:
        code = struct.unpack(">I", data[0x458:0x45C])[0]
        hdr.region = _REGIONS.get(code, f"unknown({code})")
    if len(data) >= APPLOADER_OFFSET + 0x10:
        hdr.apploader_date = cstr(data[APPLOADER_OFFSET : APPLOADER_OFFSET + 0x10])
    return hdr


def dol_size(dol_header: bytes) -> int:
    """Size of a DOL executable from its 0x100-byte header: the furthest end of
    any of the 7 text + 11 data sections (same rule as Dolphin's GetBootDOLSize)."""
    end = 0
    for i in range(7):
        off = struct.unpack_from(">I", dol_header, i * 4)[0]
        size = struct.unpack_from(">I", dol_header, 0x90 + i * 4)[0]
        if size:
            end = max(end, off + size)
    for i in range(11):
        off = struct.unpack_from(">I", dol_header, 0x1C + i * 4)[0]
        size = struct.unpack_from(">I", dol_header, 0xAC + i * 4)[0]
        if size:
            end = max(end, off + size)
    return end


def apploader_size(apploader_header: bytes) -> int:
    size, trailer = struct.unpack_from(">II", apploader_header, 0x14)
    return 0x20 + size + trailer


@dataclass
class FstEntry:
    index: int
    path: str  # forward-slash path relative to disc root, no leading slash
    is_dir: bool
    offset: int  # files: disc offset. dirs: parent entry index
    size: int  # files: byte size. dirs: index of next entry after the dir
    name: str = field(default="")

    @property
    def depth(self) -> int:
        return self.path.count("/")


def parse_fst(fst: bytes) -> list[FstEntry]:
    """Parse raw FST bytes into a flat, in-order list of entries with full paths.
    Entry 0 (the root) is omitted; every returned entry has a path."""
    if len(fst) < FST_ENTRY_SIZE:
        raise ValueError("FST too short")
    root_word, _, num_entries = struct.unpack_from(">III", fst, 0)
    if (root_word >> 24) != 1:
        raise ValueError("FST root entry is not a directory")
    if num_entries * FST_ENTRY_SIZE > len(fst):
        raise ValueError("FST entry count exceeds FST size")
    strings_base = num_entries * FST_ENTRY_SIZE

    entries: list[FstEntry] = []
    stack: list[tuple[int, str]] = [(num_entries, "")]  # (end_index, dir_path)
    for i in range(1, num_entries):
        while len(stack) > 1 and i >= stack[-1][0]:
            stack.pop()
        w, off, size = struct.unpack_from(">III", fst, i * FST_ENTRY_SIZE)
        is_dir = (w >> 24) != 0
        name_off = strings_base + (w & 0xFFFFFF)
        end = fst.find(b"\x00", name_off)
        name = cstr(fst[name_off : end if end >= 0 else len(fst)])
        parent = stack[-1][1]
        path = f"{parent}/{name}" if parent else name
        entries.append(
            FstEntry(index=i, path=path, is_dir=is_dir, offset=off, size=size, name=name)
        )
        if is_dir:
            stack.append((size, path))
    return entries
