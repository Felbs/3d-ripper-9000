"""Classify disc files by magic bytes, falling back to extension.

kind is a coarse category used for organizing output; fmt is the specific format.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SNIFF_BYTES = 64


@dataclass(frozen=True)
class Classification:
    kind: str  # model, texture, material, animation, archive, compressed, audio, video,
    # executable, banner, layout, font, text, collision, unknown
    fmt: str  # short format tag, e.g. "BMD", "TPL"
    by: str  # "magic" or "ext" or "heuristic"


UNKNOWN = Classification("unknown", "", "none")

# J3D files: 'J3D1' or 'J3D2' then a 4-byte type tag.
_J3D_TYPES: dict[bytes, tuple[str, str]] = {
    b"bmd3": ("model", "BMD"),
    b"bmd2": ("model", "BMD"),
    b"bdl4": ("model", "BDL"),
    b"bmt3": ("material", "BMT"),
    b"bck1": ("animation", "BCK"),  # joint animation
    b"bca1": ("animation", "BCA"),  # joint animation (full)
    b"brk1": ("animation", "BRK"),  # register color
    b"btk1": ("animation", "BTK"),  # texture SRT
    b"btp1": ("animation", "BTP"),  # texture pattern
    b"bpk1": ("animation", "BPK"),  # color
    b"bva1": ("animation", "BVA"),  # visibility
    b"blk1": ("animation", "BLK"),  # cluster/lighting
    b"bla1": ("animation", "BLA"),
    b"bxk1": ("animation", "BXK"),
    b"bxa1": ("animation", "BXA"),
    b"bls1": ("animation", "BLS"),  # light animation (TP)
}

_MAGICS: list[tuple[bytes, Classification]] = [
    (b"\x00\x20\xaf\x30", Classification("texture", "TPL", "magic")),
    (b"RARC", Classification("archive", "RARC", "magic")),
    (b"\xae\x0f\x38\xa2", Classification("archive", "TGC", "magic")),
    (b"U\xaa8-", Classification("archive", "U8", "magic")),
    (b"Yaz0", Classification("compressed", "Yaz0", "magic")),
    (b"Yay0", Classification("compressed", "Yay0", "magic")),
    (b"STRM", Classification("audio", "AST", "magic")),
    (b" HALPST", Classification("audio", "HPS", "magic")),
    (b"RIFF", Classification("audio", "RIFF", "magic")),
    (b"AA_<", Classification("audio", "BAA", "magic")),
    (b"RSTM", Classification("audio", "BRSTM", "magic")),
    (b"THP\x00", Classification("video", "THP", "magic")),
    (b"BNR1", Classification("banner", "BNR", "magic")),
    (b"BNR2", Classification("banner", "BNR", "magic")),
    (b"SCRNblo1", Classification("layout", "BLO", "magic")),
    (b"SCRNblo2", Classification("layout", "BLO", "magic")),
    (b"FONTbfn1", Classification("font", "BFN", "magic")),
    (b"bres", Classification("model", "BRRES", "magic")),
    (b"\x7fELF", Classification("executable", "ELF", "magic")),
    (b"MESG", Classification("text", "BMG", "magic")),
    (b"COLL", Classification("collision", "COL", "magic")),
    (b"JPAC1-00", Classification("particle", "JPC", "magic")),
    (b"JPAC2-10", Classification("particle", "JPC", "magic")),
    (b"JPAC2-11", Classification("particle", "JPC", "magic")),
    (b"STB\x00", Classification("cutscene", "STB", "magic")),
    (b"MGCLbmc1", Classification("text", "BMC", "magic")),
]

_EXTENSIONS: dict[str, Classification] = {
    ".bmd": Classification("model", "BMD", "ext"),
    ".bdl": Classification("model", "BDL", "ext"),
    ".bmt": Classification("material", "BMT", "ext"),
    ".bti": Classification("texture", "BTI", "ext"),
    ".tpl": Classification("texture", "TPL", "ext"),
    ".bck": Classification("animation", "BCK", "ext"),
    ".bca": Classification("animation", "BCA", "ext"),
    ".brk": Classification("animation", "BRK", "ext"),
    ".btk": Classification("animation", "BTK", "ext"),
    ".btp": Classification("animation", "BTP", "ext"),
    ".bpk": Classification("animation", "BPK", "ext"),
    ".bva": Classification("animation", "BVA", "ext"),
    ".blk": Classification("animation", "BLK", "ext"),
    ".arc": Classification("archive", "ARC", "ext"),
    ".rarc": Classification("archive", "RARC", "ext"),
    ".tgc": Classification("archive", "TGC", "ext"),
    ".szs": Classification("compressed", "SZS", "ext"),
    ".szp": Classification("compressed", "SZP", "ext"),
    ".ast": Classification("audio", "AST", "ext"),
    ".dsp": Classification("audio", "DSP", "ext"),
    ".adp": Classification("audio", "ADP", "ext"),
    ".hps": Classification("audio", "HPS", "ext"),
    ".aw": Classification("audio", "AW", "ext"),
    ".bms": Classification("audio", "BMS", "ext"),
    ".baa": Classification("audio", "BAA", "ext"),
    ".aaf": Classification("audio", "AAF", "ext"),
    ".bnk": Classification("audio", "BNK", "ext"),
    ".wsys": Classification("audio", "WSYS", "ext"),
    ".thp": Classification("video", "THP", "ext"),
    ".dol": Classification("executable", "DOL", "ext"),
    ".rel": Classification("executable", "REL", "ext"),
    ".elf": Classification("executable", "ELF", "ext"),
    ".bnr": Classification("banner", "BNR", "ext"),
    ".blo": Classification("layout", "BLO", "ext"),
    ".bfn": Classification("font", "BFN", "ext"),
    ".bmg": Classification("text", "BMG", "ext"),
    ".txt": Classification("text", "TXT", "ext"),
    ".csv": Classification("text", "CSV", "ext"),
    ".map": Classification("text", "MAP", "ext"),
    ".ini": Classification("text", "INI", "ext"),
    ".xml": Classification("text", "XML", "ext"),
    ".col": Classification("collision", "COL", "ext"),
    ".kcl": Classification("collision", "KCL", "ext"),
    ".dzb": Classification("collision", "DZB", "ext"),
    ".dzr": Classification("stagedata", "DZR", "ext"),  # Wind Waker room layout
    ".dzs": Classification("stagedata", "DZS", "ext"),  # Wind Waker stage layout
    ".jpc": Classification("particle", "JPC", "ext"),
    ".jpa": Classification("particle", "JPA", "ext"),
    ".stb": Classification("cutscene", "STB", "ext"),
    ".afc": Classification("audio", "AFC", "ext"),
    ".bas": Classification("audio", "BAS", "ext"),  # sound animation table
    ".bmc": Classification("text", "BMC", "ext"),
    ".str": Classification("text", "STR", "ext"),
    ".ci4": Classification("texture", "RAW-CI4", "ext"),
    ".ci8": Classification("texture", "RAW-CI8", "ext"),
    ".i4": Classification("texture", "RAW-I4", "ext"),
    ".i8": Classification("texture", "RAW-I8", "ext"),
    ".ia4": Classification("texture", "RAW-IA4", "ext"),
    ".ia8": Classification("texture", "RAW-IA8", "ext"),
    ".rgb565": Classification("texture", "RAW-RGB565", "ext"),
    ".rgb5a3": Classification("texture", "RAW-RGB5A3", "ext"),
    ".rgba8": Classification("texture", "RAW-RGBA8", "ext"),
    ".cmpr": Classification("texture", "RAW-CMPR", "ext"),
}


def _looks_like_dsp(head: bytes) -> bool:
    """Standard DSP-ADPCM header: sample count, nibble count, sample rate, loop flag..."""
    if len(head) < 0x1C:
        return False
    samples, nibbles, rate, loop, fmt, loop_start, loop_end = struct.unpack_from(
        ">IIIHHII", head, 0
    )
    if not (8000 <= rate <= 96000) or samples == 0 or loop > 1 or fmt != 0:
        return False
    if loop_end > nibbles + 16 or loop_start > loop_end:
        return False
    # nibbles = ceil(samples/14)*16 (roughly); allow slack for padding
    expected = (samples + 13) // 14 * 16
    return abs(nibbles - expected) <= 32


def _looks_like_bti(head: bytes, size: int) -> bool:
    """BTI has no magic. Header: u8 format, u8 alpha, u16 w, u16 h, ..., u32 data offset @0x1C."""
    if len(head) < 0x20 or size < 0x20:
        return False
    fmt = head[0]
    w, h = struct.unpack_from(">HH", head, 2)
    data_off = struct.unpack_from(">I", head, 0x1C)[0]
    return (
        fmt in (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 14)
        and 0 < w <= 1024
        and 0 < h <= 1024
        and (data_off == 0x20 or 0x20 <= data_off < size)
    )


def classify(name: str, head: bytes, size: int | None = None) -> Classification:
    """Classify a file from its name and the first SNIFF_BYTES of content."""
    if size is None:
        size = len(head)
    if head[:3] == b"J3D" and len(head) >= 8:
        kind_fmt = _J3D_TYPES.get(head[4:8])
        if kind_fmt:
            return Classification(kind_fmt[0], kind_fmt[1], "magic")
        return Classification("unknown", "J3D:" + head[4:8].decode("ascii", "replace"), "magic")
    for magic, cls in _MAGICS:
        if head.startswith(magic):
            return cls
    lower = name.lower()
    dot = lower.rfind(".")
    ext = lower[dot:] if dot >= 0 else ""
    if ext == ".dsp" and _looks_like_dsp(head):
        return Classification("audio", "DSP", "magic")
    if ext == ".bti" and _looks_like_bti(head, size):
        return Classification("texture", "BTI", "magic")
    if ext in _EXTENSIONS:
        return _EXTENSIONS[ext]
    if ext == "" and _looks_like_dsp(head):
        return Classification("audio", "DSP", "heuristic")
    if ext == "" and head[:2].isdigit() and head[2:3] == b"/":
        return Classification("text", "TXT", "heuristic")  # e.g. COPYDATE
    return UNKNOWN
