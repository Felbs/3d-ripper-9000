"""WSYS - JAudio wave bank descriptor (inside ``JaiInit.aaf``).

Layout per ``JASystem::WSParser`` (JASWSParser.cpp / .h), all big-endian and
every offset relative to the WSYS blob start:

    header   "WSYS", size, id, 0, +0x10 archive-bank offset, +0x14 ctrl-group offset
    WINF     "WINF", count, then archive offsets -> TWaveArchive
    archive  char file_name[0x74] (the ``Banks/*.aw`` file), then u32 wave offsets
    WBCT     "WBCT", -1, group count, scene offsets -> TCtrlScene (+0x0C ctrl offset)
    C-DF     "C-DF", wave count, ctrl-wave offsets -> u32 whose low 16 bits are the
             wave *id* used by IBNK velocity regions
    TWave    +0x00 u8 unknown (0xFF on disc), +0x01 u8 format, +0x02 u8 base key,
             +0x04 f32 sample rate, +0x08 u32 offset in the .aw, +0x0C u32 byte size,
             +0x10 u32 loop flag, +0x14 u32 loop start, +0x18 u32 loop end,
             +0x1C u32 sample count, +0x20/+0x22 s16 ADPCM history at the loop,
             +0x28 int

Formats: 0 = ADPCM4 (9-byte frames / 16 samples, the AFC codec), 1 = ADPCM2
(5-byte frames / 16 samples), 2 = PCM8, 3 = PCM16.  The .aw files are raw
sample data with no header; this table is the only description of them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import afc

FORMAT_ADPCM4 = 0
FORMAT_ADPCM2 = 1
FORMAT_PCM8 = 2
FORMAT_PCM16 = 3


@dataclass(frozen=True)
class Wave:
    wave_id: int
    format: int
    key: int
    unknown: int
    rate: float
    offset: int
    size: int
    loop: bool
    loop_start: int
    loop_end: int
    sample_count: int
    hist1: int
    hist2: int

    @property
    def seconds(self) -> float:
        return self.sample_count / self.rate if self.rate else 0.0


@dataclass
class WaveGroup:
    aw_name: str
    waves: dict[int, Wave] = field(default_factory=dict)  # wave id -> wave


@dataclass
class WaveBank:
    bank_id: int
    groups: list[WaveGroup] = field(default_factory=list)

    def find(self, wave_id: int) -> tuple[WaveGroup, Wave] | None:
        for g in self.groups:
            w = g.waves.get(wave_id)
            if w is not None:
                return g, w
        return None

    @property
    def wave_count(self) -> int:
        return sum(len(g.waves) for g in self.groups)


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def parse(data: bytes) -> WaveBank:
    if data[:4] != b"WSYS":
        raise ValueError("not a WSYS blob")
    bank = WaveBank(_u32(data, 8))
    arch_bank_off = _u32(data, 0x10)
    ctrl_group_off = _u32(data, 0x14)
    group_count = _u32(data, ctrl_group_off + 8)
    for g in range(group_count):
        arch_off = _u32(data, arch_bank_off + 8 + 4 * g)
        name = data[arch_off : arch_off + 0x74].split(b"\0", 1)[0].decode("ascii", "replace")
        scene_off = _u32(data, ctrl_group_off + 0x0C + 4 * g)
        ctrl_off = _u32(data, scene_off + 0x0C)
        wave_count = _u32(data, ctrl_off + 4)
        group = WaveGroup(name)
        for n in range(wave_count):
            wave_off = _u32(data, arch_off + 0x74 + 4 * n)
            ctrl_wave_off = _u32(data, ctrl_off + 8 + 4 * n)
            wave_id = _u32(data, ctrl_wave_off) & 0xFFFF
            f = struct.unpack_from(">BBBxfIIIIIIhh", data, wave_off)
            group.waves[wave_id] = Wave(
                wave_id, f[1], f[2], f[0], f[3], f[4], f[5], bool(f[6]), f[7], f[8], f[9],
                f[10], f[11],
            )
        bank.groups.append(group)
    return bank


# JAudio ADPCM2: 5-byte frames, byte 0 = shift/coef header, bytes 1..4 = 16 x 2-bit samples.
_CRUMB = (0, 1, -2, -1)


def _decode_adpcm2(body: bytes, nframes: int) -> list[int]:
    out = [0] * (nframes * 16)
    h1 = h2 = 0
    o = 0
    for f in range(nframes):
        head = body[f * 5]
        mul = 2048 << (head >> 4)
        c1, c2 = afc.COEFS[head & 0xF]
        for b in body[f * 5 + 1 : f * 5 + 5]:
            for sh in (6, 4, 2, 0):
                s = (_CRUMB[(b >> sh) & 3] * mul + c1 * h1 + c2 * h2) >> 11
                s = max(-32768, min(32767, s))
                out[o] = s
                o += 1
                h2 = h1
                h1 = s
    return out


def decode(aw: bytes, wave: Wave) -> np.ndarray:
    """Decode one wave out of its raw .aw blob -> int16 mono array (sample_count long)."""
    body = aw[wave.offset : wave.offset + wave.size]
    if wave.format == FORMAT_ADPCM4:
        nframes = len(body) // afc.FRAME_BYTES
        pcm, _, _ = afc._decode_frames(body, nframes, 0, 0)
        out = np.asarray(pcm, dtype=np.int16)
    elif wave.format == FORMAT_ADPCM2:
        out = np.asarray(_decode_adpcm2(body, len(body) // 5), dtype=np.int16)
    elif wave.format == FORMAT_PCM8:
        out = np.frombuffer(body, dtype=np.int8).astype(np.int16) << 8
    elif wave.format == FORMAT_PCM16:
        out = np.frombuffer(body[: len(body) // 2 * 2], dtype=">i2").astype(np.int16)
    else:
        raise ValueError(f"unknown wave format {wave.format}")
    if wave.sample_count and len(out) > wave.sample_count:
        out = out[: wave.sample_count]
    return out
