"""IBNK - JAudio instrument bank (inside ``JaiInit.aaf``).

Layout per ``JASystem::BNKParser`` (JASBNKParser.cpp / .h); offsets are
relative to the IBNK blob start:

    header  "IBNK", size, +0x08 virtual bank id, +0x20 "BANK",
            +0x24 u32 instrument offsets[128], +0x3B4 u32 percussion-set offsets[12]
    INST    +0x08 f32 volume, +0x0C f32 pitch, +0x10 u32 osc offsets[2],
            +0x18 rand offsets[2], +0x20 sense offsets[2], +0x28 key-region count,
            +0x2C key-region offsets[]
    keymap  +0x00 u8 highest key of the region, +0x04 u32 velocity-region count,
            +0x08 u32 velocity-region offsets[]
    vmap    +0x00 u8 highest velocity, +0x04 u32 wave id (low 16 bits),
            +0x08 f32 volume, +0x0C f32 pitch
    OSC     +0x00 u8 target (0 volume, 1 pitch, 2 pan, 3 fxmix, 4 dolby), +0x04 f32 rate,
            +0x08 table offset, +0x0C release-table offset, +0x10 f32 width, +0x14 f32 vertex
            tables are (s16 mode, s16 time, s16 value) rows, ending at the first mode > 10
            (13 = loop to row `value`, 14 = hold, 15 = stop; 0..3 = interpolation shapes)
    PERC/PER2 +0x88 u32 pmap offsets[128]; PER2 adds +0x288 s8 pan[128], +0x308 u16 release[128]
    pmap    +0x00 f32 volume, +0x04 f32 pitch, +0x08 rand offsets[2],
            +0x10 u32 velocity-region count, +0x14 offsets[]

Program numbers 0..127 are instruments, 0xE4 + n selects percussion set n
(``bank->setInst(i + 0xE4, drumset)``).  The key/velocity lookup is "first
region whose upper bound is >= key/velocity" (``TBasicInst::getParam``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

PERCUSSION_BASE = 0xE4
OSC_VOLUME = 0
OSC_PITCH = 1


@dataclass(frozen=True)
class VelRegion:
    max_vel: int
    wave_id: int
    volume: float
    pitch: float


@dataclass(frozen=True)
class KeyRegion:
    max_key: int
    vel_regions: tuple[VelRegion, ...]


@dataclass(frozen=True)
class Oscillator:
    target: int
    rate: float
    table: tuple[tuple[int, int, int], ...] | None
    rel_table: tuple[tuple[int, int, int], ...] | None
    width: float
    vertex: float


@dataclass
class Instrument:
    volume: float = 1.0
    pitch: float = 1.0
    oscillators: list[Oscillator] = field(default_factory=list)
    key_regions: list[KeyRegion] = field(default_factory=list)

    def region(self, key: int, vel: int) -> VelRegion | None:
        for kr in self.key_regions:
            if key <= kr.max_key:
                for vr in kr.vel_regions:
                    if vel <= vr.max_vel:
                        return vr
                return None
        return None


@dataclass
class Percussion:
    volume: float = 1.0
    pitch: float = 1.0
    pan: float = 0.5
    release: int = 0  # PER2 direct release (0 = engine default)
    vel_regions: tuple[VelRegion, ...] = ()

    def region(self, vel: int) -> VelRegion | None:
        for vr in self.vel_regions:
            if vel <= vr.max_vel:
                return vr
        return None


@dataclass
class DrumSet:
    percs: dict[int, Percussion] = field(default_factory=dict)  # key -> percussion


@dataclass
class Bank:
    virtual_id: int
    instruments: dict[int, Instrument] = field(default_factory=dict)
    drum_sets: dict[int, DrumSet] = field(default_factory=dict)

    def program(self, prog: int) -> Instrument | DrumSet | None:
        if prog >= PERCUSSION_BASE:
            return self.drum_sets.get(prog - PERCUSSION_BASE)
        return self.instruments.get(prog)


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _osc_table(data: bytes, off: int) -> tuple[tuple[int, int, int], ...] | None:
    if not off:
        return None
    rows = []
    while off + 6 <= len(data):
        row = struct.unpack_from(">hhh", data, off)
        rows.append(row)
        off += 6
        if row[0] > 10:
            break
    return tuple(rows)


def _osc(data: bytes, off: int) -> Oscillator:
    target, rate, tab, rel, width, vertex = struct.unpack_from(">B3xfIIff", data, off)
    return Oscillator(target, rate, _osc_table(data, tab), _osc_table(data, rel), width, vertex)


def _vmap(data: bytes, off: int) -> VelRegion:
    max_vel, wave, vol, pitch = struct.unpack_from(">B3xIff", data, off)
    return VelRegion(max_vel, wave & 0xFFFF, vol, pitch)


def _vel_regions(data: bytes, count: int, table_off: int) -> tuple[VelRegion, ...]:
    return tuple(_vmap(data, _u32(data, table_off + 4 * k)) for k in range(count))


def _instrument(data: bytes, off: int) -> Instrument:
    vol, pitch = struct.unpack_from(">ff", data, off + 8)
    inst = Instrument(vol, pitch)
    for j in range(2):
        o = _u32(data, off + 0x10 + 4 * j)
        if o:
            inst.oscillators.append(_osc(data, o))
    count = _u32(data, off + 0x28)
    for j in range(count):
        ko = _u32(data, off + 0x2C + 4 * j)
        max_key = data[ko]
        vcount = _u32(data, ko + 4)
        inst.key_regions.append(KeyRegion(max_key, _vel_regions(data, vcount, ko + 8)))
    return inst


def _drum_set(data: bytes, off: int) -> DrumSet:
    per2 = data[off : off + 4] == b"PER2"
    ds = DrumSet()
    for key in range(128):
        po = _u32(data, off + 0x88 + 4 * key)
        if not po:
            continue
        vol, pitch = struct.unpack_from(">ff", data, po)
        vcount = _u32(data, po + 0x10)
        perc = Percussion(vol, pitch, vel_regions=_vel_regions(data, vcount, po + 0x14))
        if per2:
            pan = struct.unpack_from(">b", data, off + 0x288 + key)[0]
            perc.pan = pan / 127.0
            perc.release = struct.unpack_from(">H", data, off + 0x308 + 2 * key)[0]
        ds.percs[key] = perc
    return ds


def parse(data: bytes) -> Bank:
    if data[:4] != b"IBNK":
        raise ValueError("not an IBNK blob")
    bank = Bank(_u32(data, 8))
    for i in range(128):
        o = _u32(data, 0x24 + 4 * i)
        if o:
            bank.instruments[i] = _instrument(data, o)
    for i in range(12):
        o = _u32(data, 0x3B4 + 4 * i)
        if o:
            bank.drum_sets[i] = _drum_set(data, o)
    return bank
