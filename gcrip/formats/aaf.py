"""AAF - JAudio init file (``Audiores/JaiInit.aaf`` in Wind Waker).

Layout per ``JAInter::InitData::checkInitDataOnMemory`` (JAIInitData.cpp): a list
of big-endian u32 chunks, ``type`` followed by a payload; type 0 ends the file.

    1  sound table      (offset, size, 0)  -> BST-like table, see :func:`parse_sound_table`
    2  instrument banks zero-terminated (offset, size, wave_bank_index) triplets -> IBNK
    3  wave banks       zero-terminated (offset, size, flags) triplets -> WSYS
    4  "Hed" file       (unused)
    5  stream list      (offset, size, 0)  -> 0x30-byte entries, name at +0x10
    6  scene table, 7 FX scene table, 8 misc blob

Chunk 2's third word is what ``JAInter::BankWave::init`` passes to
``BankMgr::assignWaveBank`` - the WSYS index that IBNK draws its samples from.
The physical bank index is the list position; the *virtual* bank number that a
sequence selects (register 0x20) is the u32 at +0x08 of the IBNK blob
(``registBankBNK`` -> ``setVir2PhyTable``).

Sound table (``JAInter::SoundTable::init``): bytes 0-3 = version/format bytes,
then 18 categories of (u16 count at 6+4i, u16 first index at 8+4i); entries are
0x10-byte ``SoundInfo`` records starting at +0x50.  Category 16 is the sequences
(``JA_BGM_*``, id & 0x3FF is the entry), category 17 the streams; ``mOffsetNo``
(+0x06) of a sequence entry is the file index inside ``Seqs/JaiSeqs.arc``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SOUND_TABLE = 1
BANK_LIST = 2
WAVE_BANK_LIST = 3
STREAM_LIST = 5
SCENE_TABLE = 6
SEQUENCE_CATEGORY = 16
STREAM_CATEGORY = 17


@dataclass(frozen=True)
class BankEntry:
    offset: int
    size: int
    wave_bank: int  # WSYS index (chunk 3 position) this IBNK uses
    virtual_id: int  # bank number as selected by sequences (IBNK +0x08)


@dataclass(frozen=True)
class WaveBankEntry:
    offset: int
    size: int
    flags: int  # 0 = simple bank, 1/2 = basic (grouped) bank


@dataclass(frozen=True)
class StreamEntry:
    index: int
    name: str
    raw: bytes


@dataclass(frozen=True)
class SoundInfo:
    flag: int
    priority: int
    offset_no: int  # sequence: file index in JaiSeqs.arc; stream: 0xFFFF
    pitch: int
    volume: int


@dataclass
class Aaf:
    banks: list[BankEntry] = field(default_factory=list)
    wave_banks: list[WaveBankEntry] = field(default_factory=list)
    streams: list[StreamEntry] = field(default_factory=list)
    sound_table: dict[int, list[SoundInfo]] = field(default_factory=dict)
    chunks: dict[int, tuple[int, int, int]] = field(default_factory=dict)  # other chunks

    def bank_data(self, data: bytes, index: int) -> bytes:
        e = self.banks[index]
        return data[e.offset : e.offset + e.size]

    def wave_bank_data(self, data: bytes, index: int) -> bytes:
        e = self.wave_banks[index]
        return data[e.offset : e.offset + e.size]

    def physical_bank(self, virtual_id: int) -> int | None:
        """Sequence bank number -> position in :attr:`banks` (BankMgr::getPhysicalNumber)."""
        for i, b in enumerate(self.banks):
            if b.virtual_id == virtual_id:
                return i
        return None

    def sequence_file_index(self, bgm_id: int) -> int | None:
        """JA_BGM_* id (0x8000xxxx or bare index) -> file index in JaiSeqs.arc."""
        seqs = self.sound_table.get(SEQUENCE_CATEGORY, [])
        n = bgm_id & 0x3FF
        if n < len(seqs):
            return seqs[n].offset_no
        return None


def parse_sound_table(table: bytes) -> dict[int, list[SoundInfo]]:
    out: dict[int, list[SoundInfo]] = {}
    for cat in range(18):
        count, start = struct.unpack_from(">HH", table, 6 + cat * 4)
        entries = []
        for n in range(count):
            p = 0x50 + (start + n) * 0x10
            if p + 0x10 > len(table):
                break
            flag, prio, _, off_no, pitch, vol = struct.unpack_from(">IBBHII", table, p)
            entries.append(SoundInfo(flag, prio, off_no, pitch, vol))
        if entries:
            out[cat] = entries
    return out


def parse(data: bytes) -> Aaf:
    words = struct.unpack(f">{len(data) // 4}I", data[: len(data) // 4 * 4])
    aaf = Aaf()
    i = 0
    while i < len(words):
        kind = words[i]
        i += 1
        if kind == 0:
            break
        if kind in (BANK_LIST, WAVE_BANK_LIST):
            while i + 2 < len(words) and words[i]:
                off, size, extra = words[i : i + 3]
                i += 3
                if kind == BANK_LIST:
                    vid = struct.unpack_from(">I", data, off + 8)[0] if size >= 12 else 0xFFFF
                    aaf.banks.append(BankEntry(off, size, extra, vid))
                else:
                    aaf.wave_banks.append(WaveBankEntry(off, size, extra))
            i += 1
            continue
        if i + 2 >= len(words):
            break
        off, size, extra = words[i : i + 3]
        i += 3
        aaf.chunks[kind] = (off, size, extra)
        if kind == SOUND_TABLE:
            aaf.sound_table = parse_sound_table(data[off : off + size])
        elif kind == STREAM_LIST:
            for n, p in enumerate(range(off, off + size - 0x2F, 0x30)):
                raw = data[p : p + 0x30]
                name = raw[0x10:0x20].split(b"\0", 1)[0].decode("ascii", "replace")
                aaf.streams.append(StreamEntry(n, name, raw))
    return aaf
