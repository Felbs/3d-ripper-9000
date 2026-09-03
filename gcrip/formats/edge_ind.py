"""Edge of Reality ``index.ind`` + ``.arc`` - The Sims, Shark Tale, Over the Hedge.

Three discs with **fourteen to nineteen files each** and almost all of the bytes in a handful
of unnamed ``.arc`` blobs, which is why they reported two textures apiece.  The directory for
every one of them is the single ``index.ind`` beside them.

Big-endian throughout.  The index is a flat list of segments::

    +0    u32 count
    +4    (count + 1) u32 offsets into this file, ascending; the last is the file length

The segments alternate: a short printable **category name**, then that category's **table**.
The names say exactly where everything is - ``Levels``, ``QuickDatas``, ``Graphs``,
``QDMetadatas``, ``Characters``, ``Models``, ``Occluders``, ``Animations``, ``BonePositions``,
``Havoks``, ``Fonts``, ``Movies``, ``PclEffects``, ``Shaders``, ``Textures``, ``Sounds``,
``Binaries``, ``Samples``, ``AudioStreams``, ``Programs``, ``DataBuilders``, ``Datasets``.

A table is **not** an array of twelve-byte records, though it measures as one::

    u32 count
    count * u32   name hashes, strictly ascending
    count * (u32 offset, u32 size)

``4 + count * 12`` is the same either way, and reading it interleaved gives three columns of
plausible-looking 32-bit numbers - none of them ascending, all of them nonsense.  The giveaway
is that the *first* ``count`` words are sorted: it is a binary-search table with the payload
locations after it, not a record array.

**Which archive a category lives in is its own name, truncated to eight characters** -
``AudioStreams`` to ``audiostr.arc``, ``QuickDatas`` to ``quickdat.arc``, ``RleTextures`` to
``rletextu.arc``.  That is a guess made safe by an exact check: the category's
``max(offset + size)`` has to equal the archive's length.  It does, to the byte:

    Over the Hedge   Levels 2,894,207   Movies 574,376,316   Samples 61,154,604
                     AudioStreams 216,477,632   Datasets 399,527,193
    The Sims         Movies 101,379,296   Samples 113,860,974   AudioStreams 150,309,798

A category with no matching archive - ``Models`` and ``Textures`` on Over the Hedge, which has
no ``models.arc`` - is left alone rather than pointed at the wrong file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = 4
MAX_SEGMENTS = 1 << 12
MAX_NAME = 16
MAX_ENTRIES = 1 << 20
STEM = 8
RECORD = 12


@dataclass
class Entry:
    hash: int
    offset: int
    size: int


def _segments(data: bytes) -> list[tuple[int, int]] | None:
    if len(data) < HEADER + 8:
        return None
    count = struct.unpack_from(">I", data, 0)[0]
    if not (0 < count <= MAX_SEGMENTS):
        return None
    end = HEADER + (count + 1) * 4
    if end > len(data):
        return None
    offsets = list(struct.unpack_from(f">{count + 1}I", data, HEADER))
    if offsets[0] != end or offsets[-1] != len(data):
        return None
    if any(a > b for a, b in zip(offsets, offsets[1:], strict=False)):
        return None
    return list(zip(offsets, offsets[1:], strict=False))


def is_index(data: bytes) -> bool:
    return _segments(data) is not None


LATE_HEADER = 20  # The Sims 2 Pets: u32 0, u32 count, u32 table bytes, u32 capacity, u32 0


def _table(seg: bytes) -> list[Entry] | None:
    if len(seg) < 4:
        return None
    count = struct.unpack_from(">I", seg, 0)[0]
    at = 4
    if count == 0 and len(seg) >= LATE_HEADER:
        count, table_bytes = struct.unpack_from(">II", seg, 4)
        if table_bytes != len(seg):
            return None
        at = LATE_HEADER
    if not (0 < count <= MAX_ENTRIES) or len(seg) - at != count * RECORD:
        return None
    hashes = struct.unpack_from(f">{count}I", seg, at)
    if any(a >= b for a, b in zip(hashes, hashes[1:], strict=False)):
        return None  # the sorted hash array is what distinguishes this from a record array
    pairs = struct.unpack_from(f">{2 * count}I", seg, at + count * 4)
    return [Entry(hashes[i], pairs[2 * i], pairs[2 * i + 1]) for i in range(count)]


def categories(data: bytes) -> dict[str, list[Entry]]:
    """Every category the index names, with its entries."""
    spans = _segments(data)
    if spans is None:
        return {}
    out: dict[str, list[Entry]] = {}
    label: str | None = None
    for start, stop in spans:
        seg = data[start:stop]
        if 0 < len(seg) <= MAX_NAME and all(c == 0 or 32 <= c < 127 for c in seg):
            label = seg.split(b"\x00", 1)[0].decode("latin-1")
            continue
        table = _table(seg)
        if table is not None and label:
            out[label] = table
        label = None
    return out


def stem_of(category: str) -> str:
    """``AudioStreams`` -> ``audiostr``: the archive name is the category truncated to eight."""
    return category.lower()[:STEM]


PAD_ALLOWANCE = 1 << 16


def fits(entries: list[Entry], archive_size: int) -> bool:
    """The category's entries have to account for the archive, give or take its padding.

    Eleven of the sixteen category/archive pairs across the three discs land on the byte; the
    other five stop 156 to 64,357 bytes short of a padded tail, the worst being 0.73% of an
    8.7 MB archive.  Demanding an exact match - which Over the Hedge happens to give on all
    five of its archives - silently rejects both of the other discs.

    The allowance stays a real check because a *wrong* pairing misses by a different order of
    magnitude entirely: Over the Hedge's ``Models`` ends at 73 MB against a 399 MB
    ``datasets.arc``.
    """
    if not entries:
        return False
    end = max(e.offset + e.size for e in entries)
    if end > archive_size:
        return False
    return archive_size - end <= max(PAD_ALLOWANCE, archive_size // 64)
