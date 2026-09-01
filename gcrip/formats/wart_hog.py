"""``WART3.00`` ``.hog`` archives - Warthog's engine, on Animaniacs, Looney Tunes: Back in
Action and Harry Potter and the Sorcerer's Stone.

101 archives across the three discs hold **138,326 named members**, among them 19,156
``.bmsh`` meshes, 29,047 ``.btga`` textures, 3,286 ``.bskl`` skeletons and 10,509 ``.anm``
animations.  Both the directory and the member codec are solved; see ``decompress`` for the codec.

Big-endian throughout::

    +0   char magic[8]        "WART3.00"
    +8   u32  member count
    +12  u32  name table offset
    +16  u32  file-name section bytes
    +20  u32  directory-name section bytes
    +24  the records, 24 bytes each:
             u32 data offset
             u32 packed size
             u32 unpacked size
             u32 hash
             u32 file name offset    from name table + directory bytes
             u32 directory name offset

The name table is two runs of NUL-terminated strings: the directories first (each ending in a
slash), then the file names, and a record names one of each - so a member's path is
``dirs[record.dir] + files[record.name]``.

**The field order is the trap.**  Read as if the records began at +16, every offset and size
still chains perfectly - member N ends exactly where member N+1 begins - because the two name
words merely shift the whole window by eight bytes.  What gives it away is the payload: under
the wrong order Animaniacs' two ``.btga`` fonts unpack to 9,602 bytes and its two ``.tnf``
metrics files to 131,168, which is backwards.  Under the right one both textures are 131,168
and both metrics files 9,602.  *Contiguity confirms the stride, not the field order.*

The directory-bytes word is byte-swapped on some archives - Animaniacs stores 30 as
``00 00 00 1e`` and Looney Tunes stores 147 as ``93 00 00 00``.  Rather than trust either, the
value is accepted only if it lands just past a NUL in the name table, and byte-swapped if not.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"WART3.00"
HEADER = 24
ENTRY = 24
MAX_COUNT = 1 << 20
LITERAL_RUN = 0xE0
HIGH_FORM = 0x80
LONG_FORM = 0xC0
LIT_MASK = 3
LONG_LEN_HIGH = 0x1C
RUN_MASK = 0x1F
LEN_BIAS = 3
HIGH_LEN_BIAS = 4
LONG_LEN_BIAS = 5
LOW_LEN_MASK = 7
LOW_OFF_MASK = 0x60
OFF_BIAS = 1


@dataclass
class Member:
    name: str
    offset: int
    packed: int
    unpacked: int
    hash: int


def is_wart_hog(head: bytes) -> bool:
    """``head`` may be as little as the 64 bytes ``classify`` sniffs."""
    return head[:8] == MAGIC


def _dir_bytes(word: int, table: bytes) -> int | None:
    for value in (word, struct.unpack("<I", struct.pack(">I", word))[0]):
        if 0 < value < len(table) and not table[value - 1]:
            return value
    return None


def _string(table: bytes, at: int) -> str | None:
    if not 0 <= at < len(table):
        return None
    end = table.find(b"\0", at)
    return table[at:end].decode("latin-1") if end > at else None


def members(data: bytes) -> list[Member]:
    if not is_wart_hog(data[:8]) or len(data) < HEADER:
        return []
    count, names_at, _files, dir_word = struct.unpack_from(">4I", data, 8)
    if not 0 < count <= MAX_COUNT or not HEADER < names_at < len(data):
        return []
    if HEADER + count * ENTRY > names_at:
        return []
    table = data[names_at:]
    dir_bytes = _dir_bytes(dir_word, table)
    if dir_bytes is None:
        return []
    out = []
    for i in range(count):
        offset, packed, unpacked, digest, name_at, dir_at = struct.unpack_from(
            ">6I", data, HEADER + i * ENTRY
        )
        name = _string(table, dir_bytes + name_at)
        folder = _string(table, dir_at)
        if name is None:
            continue
        out.append(Member((folder or "") + name, offset, packed, unpacked, digest))
    return out


def decompress(data: bytes, want: int) -> bytes | None:
    """The member codec.  ``None`` unless the stream yields exactly ``want`` bytes.

    Four token forms, all big-endian in spirit but byte-oriented.  Every match form carries its
    own literals, which are emitted **before** the copy, and the copy is self-referencing, so a
    length may exceed its offset (that is how runs are encoded)::

        t >= 0xE0    literal run of ((t & 0x1f) + 1) * 4 bytes
        t <  0x80    lits = t & 3    len = ((t >> 2) & 7) + 3   off = ((t & 0x60) << 3 | b) + 1
        0x80..0xBF   lits = a >> 6   len = (t & 0x3f) + 4       off = ((a & 0x3f) << 8 | b) + 1
        0xC0..0xDF   lits = t & 3    len = ((t & 0x1c) << 6 | c) + 5   off = (a << 8 | b) + 1

    The three forms are one design: a short match with a 10-bit window, a longer match with a
    14-bit window, and a long match with an explicit length byte and a full 16-bit window.  The
    operand bytes follow the token, then the literal bytes.

    **The low form is where this stayed stuck for four sessions.**  ``len = (t >> 2) + 3`` and
    ``off = b + 1`` fit every token in the small vectors and are both wrong: the length is only
    three bits and bits 5-6 of the token are the offset's high bits.  Nothing showed it until a
    token with bit 5 set turned up - ``0x34 0x61`` in ``frontend_scroll.lvl``, which needs
    offset 354 to copy ``Number, `` and gets 98 under ``b + 1``.  Every earlier vector happened
    to have those bits clear, so a rule fitted to them looked general and was not.

    **Two masks were a byte too narrow and only binary members showed it.**  The run count is
    five bits, not four - ``0xF0``-``0xFF`` are runs of 68 to 128 bytes - and in the text
    members those tokens only ever land as the final run, where the end of the stream truncates
    them to the right length anyway.  Likewise the long form's length carries the token's bits
    2-4, which text never exercised because it never needed a match over 260 bytes.  Both were
    invisible in every text vector and cost two thirds of a real archive.

    Verified on eight members of Animaniacs' ``frontend.hog``: all eight decode to **exactly**
    their declared size, and the three ``frontend_cog*.lvl`` - 199 packed bytes each, differing
    at one stream byte - give three 386-byte texts differing at exactly one character, the
    ``1``/``2``/``3`` of ``{frontend_cog1}``.  ``general_eng.loc`` comes out as the game's
    localisation table and ``scriptfns.txt`` as its scripting reference, both closing cleanly.
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n and len(out) < want:
        token = data[i]
        i += 1
        if token >= LITERAL_RUN:
            # the last run of a member may be cut short by the end of the stream
            run = min(((token & RUN_MASK) + 1) * 4, n - i)
            out += data[i : i + run]
            i += run
            continue
        if token < HIGH_FORM:
            operands, literals = 1, token & LIT_MASK
            length = ((token >> 2) & LOW_LEN_MASK) + LEN_BIAS
        elif token < LONG_FORM:
            operands, literals = 2, (data[i] >> 6 if i < n else 0)
            length = (token & 0x3F) + HIGH_LEN_BIAS
        else:
            operands, literals = 3, token & LIT_MASK
            length = (
                ((token & LONG_LEN_HIGH) << 6 | data[i + 2]) + LONG_LEN_BIAS
                if i + 2 < n
                else 0
            )
        if i + operands + literals > n:
            return None
        if operands == 1:
            offset = ((token & LOW_OFF_MASK) << 3 | data[i]) + OFF_BIAS
        elif operands == 2:
            offset = ((data[i] & 0x3F) << 8 | data[i + 1]) + OFF_BIAS
        else:
            offset = (data[i] << 8 | data[i + 1]) + OFF_BIAS
        i += operands
        out += data[i : i + literals]
        i += literals
        if not 0 < offset <= len(out):
            return None
        for _ in range(length):
            out.append(out[-offset])
    return bytes(out) if len(out) == want else None
