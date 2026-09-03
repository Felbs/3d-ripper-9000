"""Edge of Reality ``Datasets`` members - the nested resource packs of The Sims (2003), The Sims
Bustin' Out, The Urbz, Shark Tale and Over the Hedge.  A dataset carries a level's or an
object's textures, shaders, models, characters and animations as named sections, and on these
discs it is where the models live (the older two have *only* datasets in their index).

Three layouts of the same idea::

  Sims / Bustin' Out    name\\0, u32 sections, sections x (name\\0, u32 count, entries)
  Shark Tale / Hedge    12 zero bytes, u8 sections, name\\0, sections as above
  The Urbz              u32 9, name[64], u32 count, count x (category[32], entry)
  entry                 u32 name hash, u32 size, u32 padding, size + padding bytes

The entry payload is wrapped per game (``wrapper`` below), and the reader in
``gcrip.formats.edge_model`` takes the wrapper apart:

  textures  "LFXT" [Bustin' Out: u32 7, 12 zero bytes | Urbz: u32 8, u32 size] name\\0 header pixels
            header: the 32-byte ETextureDef on The Urbz, otherwise the 20-byte
            ``u8 fmt, u8 bpp, u16 w, u16 h, u8, u8 palette bpp, u16 palette entries, u32 flags,
            u32, u16 mips``
  models    Sims / Shark Tale / Hedge: u32, u16, name\\0, then the model with no node arrays;
            Bustin' Out: u32, u16, name\\0, 16 bytes, then the model;
            The Urbz: u32 version, u32 0, u32 0, u32 0, u32 size, name\\0, then the full model
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIMS, HEDGE, URBZ = "sims", "hedge", "urbz"
MAX_SECTIONS = 64
MAX_ENTRIES = 1 << 16
CATEGORY = 32
URBZ_NAME = 64


class DatasetError(ValueError):
    pass


@dataclass
class Entry:
    category: str
    hash: int
    payload: bytes


def _printable(b: bytes) -> bool:
    return bool(b) and all(32 <= c < 127 for c in b)


def _cstring(data: bytes, at: int, limit: int = 128) -> tuple[bytes, int] | None:
    end = data.find(b"\0", at, at + limit)
    if end < 0:
        return None
    return data[at:end], end + 1


def style(head: bytes) -> str | None:
    """Which layout a member follows, from its first bytes, or None."""
    if len(head) < 24:
        return None
    if head[:4] == b"\0\0\0\x09" and _printable(head[4:6]):
        end = head.find(b"\0", 4, 4 + URBZ_NAME)
        if end > 4 and all(c == 0 for c in head[end : min(len(head), 4 + URBZ_NAME)]):
            return URBZ
    if head[:12] == bytes(12) and 0 < head[12] <= MAX_SECTIONS:
        s = _cstring(head, 13, 64)
        if s is not None and _printable(s[0]):
            return HEDGE
    s = _cstring(head, 0, 64)
    if s is not None and _printable(s[0]) and len(head) >= s[1] + 5:
        count = struct.unpack_from(">I", head, s[1])[0]
        if 0 < count <= MAX_SECTIONS and _printable(head[s[1] + 4 : s[1] + 6]):
            return SIMS
    return None


def _sectioned(data: bytes, p: int, sections: int) -> list[Entry]:
    out: list[Entry] = []
    for _ in range(sections):
        s = _cstring(data, p)
        if s is None:
            raise DatasetError(f"section name runs off the member at {p}")
        name, p = s
        if p + 4 > len(data):
            raise DatasetError("section count past the end")
        count = struct.unpack_from(">I", data, p)[0]
        p += 4
        if count > MAX_ENTRIES:
            raise DatasetError(f"{count} entries in {name!r}")
        for _ in range(count):
            if p + 12 > len(data):
                raise DatasetError("entry header past the end")
            h, size, pad = struct.unpack_from(">III", data, p)
            p += 12
            if p + size + pad > len(data):
                raise DatasetError(f"entry {h:08x} of {size} bytes past the end")
            out.append(Entry(name.decode("latin-1"), h, data[p : p + size]))
            p += size + pad  # Over the Hedge pads its samples: the third word is the padding
    if p != len(data):
        raise DatasetError(f"{len(data) - p} bytes after the last section")
    return out


def entries(data: bytes) -> tuple[str, str, list[Entry]]:
    """(style, dataset name, entries) of a member."""
    kind = style(data[:96])
    if kind is None:
        raise DatasetError("not an Edge of Reality dataset")
    if kind == URBZ:
        name = data[4 : 4 + URBZ_NAME].split(b"\0")[0].decode("latin-1")
        count = struct.unpack_from(">I", data, 4 + URBZ_NAME)[0]
        if count > MAX_ENTRIES:
            raise DatasetError(f"{count} entries")
        p = 8 + URBZ_NAME
        out: list[Entry] = []
        for _ in range(count):
            if p + CATEGORY + 12 > len(data):
                raise DatasetError("entry header past the end")
            category = data[p : p + CATEGORY].split(b"\0")[0].decode("latin-1")
            h, size, pad = struct.unpack_from(">III", data, p + CATEGORY)
            p += CATEGORY + 12
            if p + size + pad > len(data):
                raise DatasetError(f"entry {h:08x} of {size} bytes past the end")
            out.append(Entry(category, h, data[p : p + size]))
            p += size + pad
        if p != len(data):
            raise DatasetError(f"{len(data) - p} bytes after the last entry")
        return kind, name, out
    if kind == HEDGE:
        sections = data[12]
        s = _cstring(data, 13)
        if s is None:
            raise DatasetError("dataset name runs off the member")
        name, p = s
        return kind, name.decode("latin-1"), _sectioned(data, p, sections)
    s = _cstring(data, 0)
    assert s is not None
    name, p = s
    sections = struct.unpack_from(">I", data, p)[0]
    return kind, name.decode("latin-1"), _sectioned(data, p + 4, sections)


# ------------------------------------------------------------------ payload wrappers

TEXTURE_TAG = b"LFXT"
BUSTIN_OUT_TEXTURE = b"\0\0\0\x07"
URBZ_TEXTURE = b"\0\0\0\x08"


def texture_wrapper(payload: bytes) -> tuple[str, int] | None:
    """(name, offset of the texture header) for an ``LFXT`` entry, or None."""
    if payload[:4] != TEXTURE_TAG:
        return None
    if payload[4:8] == BUSTIN_OUT_TEXTURE:
        at = 20
    elif payload[4:8] == URBZ_TEXTURE:
        at = 12
    else:
        at = 4
    s = _cstring(payload, at)
    if s is None:
        return None
    return s[0].decode("latin-1"), s[1]


def model_wrapper(payload: bytes) -> tuple[str, int, int] | None:
    """(name, offset of the model data, version) for a model entry, or None."""
    if len(payload) < 12:
        return None
    if payload[4:16] == bytes(12) and payload[:4] != bytes(4):
        # The Urbz: an EDataHeader with an empty name and the version in front
        version, size = (
            struct.unpack_from(">I", payload, 0)[0],
            struct.unpack_from(">I", payload, 16)[0],
        )
        s = _cstring(payload, 20)
        if s is None or 20 + size > len(payload):
            return None
        return s[0].decode("latin-1"), s[1], version
    s = _cstring(payload, 6)
    if s is None:
        return None
    return s[0].decode("latin-1"), s[1], 0
