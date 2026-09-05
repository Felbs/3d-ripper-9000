"""EA ``OBG`` terrain - the ``ter`` members of the Tiger Woods ``SHOC`` archives
(:mod:`gcrip.formats.shoc`), 55 MB of them across the four discs.

Same chunk convention as its sibling ``TXG`` (:mod:`gcrip.formats.ea_txg`): ``char tag[4]``
then a ``u32`` size that **excludes** the eight-byte header.  Read the SHOC way and the walk
stops on chunk one; read this way it lands exactly on the member's last byte - 4,655 chunks on
the first one sampled, to the byte::

    OBG   char magic[4] "OBG " | u8 version[4]
    ARRA  a typed array         (5 per member)
    HEAD  56 bytes
    ELHE  an element header     (2,794)
    ELDA  an element's indices   (1,855)

An ``ARRA`` payload begins with two words that describe it::

    u32  (type << 24) | count
    u32  components << 18

so its size is `8 + count * components * 4`, which holds on **143 of 144** arrays across 48
members.  Each member carries one ``(type 2, 3 components)`` array of `f32` - the positions -
plus scalar arrays.

``ELDA`` holds **big-endian `u16` triangle strips** after an eight-byte header, indexing that
array.  1,815 of 1,855 index inside it cleanly and the other 40 reach exactly 65,535, which is
the primitive-restart marker rather than an overrun - so restarts are split, not clamped.

The strips are what make the member large: about **1.05 million triangles** in the first one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"OBG "
HEADER = 8
HEAD_SLACK = 16
RESTART = 0xFFFF
ELDA_HEADER = 8
POS_TYPE = 2
POS_COMPONENTS = 3
MAX_COUNT = 1 << 22


@dataclass
class Chunk:
    tag: bytes
    at: int
    size: int


def is_obg(head: bytes) -> bool:
    return head[:4] == MAGIC


def _tag_at(data: bytes, at: int) -> bool:
    if at + HEADER > len(data):
        return False
    tag = data[at : at + 4]
    size = struct.unpack_from(">I", data, at + 4)[0]
    return all(32 <= c < 127 for c in tag) and at + HEADER + size <= len(data)


def chunks(data: bytes) -> list[Chunk]:
    out: list[Chunk] = []
    at = HEADER
    while at + HEADER <= len(data):
        if not _tag_at(data, at):
            # The RotK / Third Age character and object flavours (01 05 / 01 07) declare
            # 16 bytes less for HEAD than it occupies, which desynchronises the walk right
            # after it.  Resync by the slack: 38 of 38 Third Age members then walk to
            # exactly their last byte.  Tiger Woods (01 04) never takes this branch.
            if _tag_at(data, at + HEAD_SLACK):
                at += HEAD_SLACK
                continue
            break
        size = struct.unpack_from(">I", data, at + 4)[0]
        out.append(Chunk(data[at : at + 4], at, size))
        at += HEADER + size
    return out


def positions(data: bytes, found: list[Chunk] | None = None) -> np.ndarray | None:
    """The one `(type 2, 3 components)` array whose values are all finite."""
    for c in found if found is not None else chunks(data):
        if c.tag != b"ARRA" or c.size < 16:
            continue
        word, shape = struct.unpack_from(">2I", data, c.at + HEADER)
        kind, count, comps = word >> 24, word & 0xFFFFFF, shape >> 18
        if kind != POS_TYPE or comps != POS_COMPONENTS or not 0 < count < MAX_COUNT:
            continue
        if HEADER + count * comps * 4 != c.size:
            continue
        got = np.frombuffer(data, ">f4", count * comps, c.at + 16).reshape(count, comps)
        if np.isfinite(got).all():
            return got
    return None


def triangles(data: bytes, vertices: int, found: list[Chunk] | None = None) -> np.ndarray:
    """Every ELDA strip flattened to triangles, restarts split and degenerates dropped."""
    out: list[np.ndarray] = []
    for c in found if found is not None else chunks(data):
        if c.tag != b"ELDA" or c.size <= ELDA_HEADER + 4:
            continue
        n = (c.size - ELDA_HEADER) // 2
        idx = np.frombuffer(data, ">u2", n, c.at + HEADER + ELDA_HEADER)
        for run in _runs(idx):
            if run.size < 3 or run.max() >= vertices:
                continue
            tri = np.stack([run[:-2], run[1:-1], run[2:]], axis=1)
            tri[1::2] = tri[1::2, ::-1]  # strips alternate winding
            keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
            if keep.any():
                out.append(tri[keep])
    return np.concatenate(out) if out else np.empty((0, 3), np.uint32)


def _runs(idx: np.ndarray) -> list[np.ndarray]:
    breaks = np.flatnonzero(idx == RESTART)
    if not breaks.size:
        return [idx]
    parts, start = [], 0
    for b in breaks:
        if b > start:
            parts.append(idx[start:b])
        start = b + 1
    if start < idx.size:
        parts.append(idx[start:])
    return parts


# -- The Lord of the Rings: The Return of the King / The Third Age -------------------------

NAMED_HEAD = b"\x00\x02"
NAMED_ATTRS = b"\x00\x03\x00\x03"
NAMED_SEARCH = 48
UV_TYPE = 1
COLOR_TYPE = 0
UV_SCALE = 1.0 / 1024.0
OBJECT_VERSION = b"\x01\x07"
#: the geometry record: ``00 01`` ends the element's property list, ``00 03`` opens the
#: corner data - ``u16 format | u16 corners``, then the corners
GEOMETRY = b"\x00\x01\x00\x03"
GEOMETRY_SEARCH = 64
#: corner width in u16 words by format code, read off The Third Age by byte-exact tiling:
#: every one of e98c02.scg's 38 ``OBG 01 07`` members admits exactly one width that lands
#: the corner data on its ELDA's last byte (minus 0 or 2 pad).  Format 3 is (position, uv,
#: colour) - the RotK layout; format 0 adds a second colour set (its two extra columns
#: always equal column 2's twin); format 4 drops the uv (its members' uv array has 1 entry).
GEOMETRY_WORDS = {3: 3, 0: 4, 4: 2}


@dataclass
class NamedElement:
    name: str
    corners: np.ndarray  # (n, 3) u16: position, uv, colour indices - one strip


def _object_elements(data: bytes, found: list[Chunk]) -> list[NamedElement]:
    """The Third Age ``OBG 01 07`` ``ELDA``: elements introduced by ``00 02`` and an 8-byte
    material id (a hash, not a name - the sibling ``txfx`` textures are all named
    ``textureN``, so there is nothing to bind by name), a property list (``00 03 <mask>``,
    sometimes ``00 05 ...``), then the geometry record ``00 01 00 03 | u16 format |
    u16 corners`` and the corner strip.  Corners normalise to the RotK (position, uv,
    colour) triple: format 0's two colour columns are always equal (206 of 206 corners on
    e98c02.scg) and format 4's missing uv column is index 0 (its uv array has one entry)."""
    out: list[NamedElement] = []
    for c in found:
        if c.tag != b"ELDA":
            continue
        p = data[c.at + HEADER : c.at + HEADER + c.size]
        at = 0
        while True:
            head = p.find(NAMED_HEAD, at)
            if head < 0:
                break
            rec = p.find(GEOMETRY, head + 2, head + 2 + GEOMETRY_SEARCH)
            if rec < 0:
                at = head + 2
                continue
            fmt, count = struct.unpack_from(">2H", p, rec + 4)
            words = GEOMETRY_WORDS.get(fmt)
            start = rec + 8
            if words is None or count < 3 or start + 2 * words * count > len(p):
                at = head + 2
                continue
            name = p[head + 2 : head + 10].hex()
            got = np.frombuffer(p, ">u2", words * count, start).reshape(count, words)
            corners = np.zeros((count, 3), ">u2")
            corners[:, 0] = got[:, 0]
            if words > 2:
                corners[:, 1] = got[:, 1]
            corners[:, 2] = got[:, words - 1] if words == 2 else got[:, 2]
            out.append(NamedElement(name, corners))
            at = start + 2 * words * count
    return out


def named_elements(data: bytes, found: list[Chunk] | None = None) -> list[NamedElement]:
    """RotK / Third Age ``ELDA``: elements introduced by ``00 02 <material>\0``, a short
    property list, ``00 03 00 03``, ``u16 corners`` and corners of three ``u16`` indices -
    position, uv (the type-1 array of packed ``s16`` pairs) and colour (the type-0 RGBA
    array) - forming one triangle strip.  Tiger Woods' ``ELDA`` carries none of this.
    The Third Age's ``01 07`` members swap the name for an 8-byte id and vary the corner
    width - those go through :func:`_object_elements`."""
    if found is None:
        found = chunks(data)
    if data[4:6] == OBJECT_VERSION:
        return _object_elements(data, found)
    out: list[NamedElement] = []
    for c in found:
        if c.tag != b"ELDA":
            continue
        p = data[c.at + HEADER : c.at + HEADER + c.size]
        at = 0
        while True:
            head = p.find(NAMED_HEAD, at)
            if head < 0:
                break
            end = p.find(b"\0", head + 2, head + 2 + 32)
            name = p[head + 2 : end] if end > 0 else b""
            if not name or not all(32 <= ch < 127 for ch in name):
                at = head + 1
                continue
            attrs = p.find(NAMED_ATTRS, end, end + NAMED_SEARCH)
            if attrs < 0:
                at = head + 1
                continue
            count = struct.unpack_from(">H", p, attrs + 4)[0]
            if count < 3 or attrs + 6 + 6 * count > len(p):
                at = head + 1
                continue
            corners = np.frombuffer(p, ">u2", 3 * count, attrs + 6).reshape(count, 3)
            out.append(NamedElement(name.decode("ascii"), corners))
            at = attrs + 6 + 6 * count
    return out


def typed_array(
    data: bytes, kind: int, found: list[Chunk] | None = None
) -> tuple[int, int, int] | None:
    """``(offset, count, components)`` of the first ARRA of the given type."""
    for c in found if found is not None else chunks(data):
        if c.tag != b"ARRA" or c.size < 16:
            continue
        word, shape = struct.unpack_from(">2I", data, c.at + HEADER)
        if word >> 24 == kind and 0 < (word & 0xFFFFFF) < MAX_COUNT:
            return c.at + 16, word & 0xFFFFFF, shape >> 18
    return None
