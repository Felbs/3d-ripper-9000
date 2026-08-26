"""TGC - an embedded GameCube mini-disc (The Legend of Zelda: Collector's Edition ships the
Wind Waker demo, the Ocarina/Majora emulator bundles and the movies as ``*.tgc`` files).

Header (big-endian u32s; layout checked against Dolphin's TGCBlob.cpp and against every
TGC on the Collector's Edition disc):

  0x00 magic 0xAE0F38A2      0x04 version (0)          0x08 header size (0x8000)
  0x0C unknown (0x100000)    0x10 FST offset (real)    0x14 FST size
  0x18 FST max size          0x1C DOL offset (real)    0x20 DOL size
  0x24 file area offset      0x28 file area size       0x2C banner offset (real)
  0x30 banner size           0x34 file offset base

A normal disc header ("boot.bin", game ID + 0xC2339F3D magic at +0x1C) sits at
``header size``. The FST is a normal GameCube FST, but its file offsets are virtual:
``real = fst_offset - file_offset_base + file_area_offset`` (all relative to the start of
the TGC blob).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from gcrip.disc.fst import DiscHeader, FstEntry, parse_fst, parse_header

TGC_MAGIC = b"\xae\x0f\x38\xa2"


@dataclass
class TgcFile:
    path: str
    name: str
    offset: int  # real offset inside the TGC blob
    size: int


@dataclass
class Tgc:
    header: DiscHeader
    header_size: int
    fst_offset: int
    fst_size: int
    dol_offset: int
    dol_size: int
    file_area_offset: int
    file_offset_base: int
    files: list[TgcFile] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)


def is_tgc(data: bytes) -> bool:
    return data[:4] == TGC_MAGIC


def parse(data: bytes) -> Tgc:
    if not is_tgc(data):
        raise ValueError("not a TGC (bad magic)")
    if len(data) < 0x38:
        raise ValueError("TGC header truncated")
    (
        _magic,
        _version,
        header_size,
        _unk,
        fst_off,
        fst_size,
        _fst_max,
        dol_off,
        dol_size,
        area_off,
        _area_size,
        _bnr_off,
        _bnr_size,
        base,
    ) = struct.unpack(">14I", data[:0x38])
    hdr_blob = data[header_size : header_size + 0x2450]
    if len(hdr_blob) < 0x440:
        raise ValueError("TGC: embedded disc header missing")
    header = parse_header(hdr_blob)
    if fst_off + fst_size > len(data):
        raise ValueError("TGC: FST extends past end of blob")
    entries: list[FstEntry] = parse_fst(data[fst_off : fst_off + fst_size])
    t = Tgc(
        header=header,
        header_size=header_size,
        fst_offset=fst_off,
        fst_size=fst_size,
        dol_offset=dol_off,
        dol_size=dol_size,
        file_area_offset=area_off,
        file_offset_base=base,
    )
    for e in entries:
        if e.is_dir:
            t.dirs.append(e.path)
            continue
        real = e.offset - base + area_off
        if real < 0 or real + e.size > len(data):
            raise ValueError(f"TGC: {e.path} maps outside the blob ({real:#x}+{e.size:#x})")
        t.files.append(TgcFile(path=e.path, name=e.name, offset=real, size=e.size))
    return t
