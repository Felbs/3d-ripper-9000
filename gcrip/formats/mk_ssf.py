"""Midway ``SEC`` archives (``.ssf``) - Mortal Kombat: Deception and Deadly Alliance.

Read with the Deception ELF's linker map (``mk_fileinfo.o``: ``load_ssf``, ``find_section_by_name``,
``get_ssf_dir_entry``).  Big-endian directory, RenderWare payloads:

  block:   "SEC ", u32 4, u32 0, u32, u32 count, u32 names bytes, u32 data bytes,
           count x (u32 type, u32 offset, u32 size, u32 name offset), names (NUL strings)
           (Deadly Alliance: u32 count, u32 data bytes, count x (type, offset, size), no names)
  offsets are from the block's own start; a type-1 (Deadly Alliance: 6) entry is a nested
  block (the root block holds one, at 0x800), 4 is a RenderWare CLUMP behind eight bytes, 3 is
  a texture:
  u8 n, name[n + 1], seven bytes, then a RenderWare Texture Native STRUCT chunk (GameCube
  raster, ``PAD128`` filler before the pixels).

The clumps are RenderWare 3.6 streams whose GEOMETRY struct is written "in place": the
material list, extension and a bare STRUCT with the GameCube native data sit inside the
declared struct (``gcrip.formats.rwstream`` reads that shape), and the game quantises with
``RpGameCubeVtxFmtSetTexCoord(S16, 11)``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.formats import rwgc
from gcrip.formats import rwstream as rw

MAGIC = b"SEC "
HEADER = 0x1C
HEADER_UNNAMED = 0x18
ENTRY = 16
ENTRY_UNNAMED = 12
NESTED, TEXTURE, CLUMP, NESTED_DA = 1, 3, 4, 6
CLUMP_PREFIX = 8
MAX_ENTRIES = 1 << 14


@dataclass
class Member:
    name: str
    kind: int
    data: bytes


def is_ssf(head: bytes) -> bool:
    return head[:4] == MAGIC and len(head) >= 8 and struct.unpack_from(">I", head, 4)[0] == 4


def _block(data: bytes, base: int, end: int, prefix: str, out: list[Member], depth: int) -> None:
    if depth > 4 or base + HEADER > end or data[base : base + 4] != MAGIC:
        return
    count, w5, w6 = struct.unpack_from(">III", data, base + 16)
    if count > MAX_ENTRIES:
        return
    # Deception: u32 count, u32 names bytes, u32 data bytes, 16-byte entries, a name table.
    # Deadly Alliance: u32 count, u32 data bytes, 12-byte entries (kind, offset, size), no names.
    named = w6 >= 16
    p = base + (HEADER if named else HEADER_UNNAMED)
    entry = ENTRY if named else ENTRY_UNNAMED
    entries = []
    for _ in range(count):
        if p + entry > end:
            return
        if named:
            entries.append(struct.unpack_from(">IIII", data, p))
        else:
            entries.append(struct.unpack_from(">III", data, p) + (0,))
        p += entry
    names = data[p : p + w5] if named else b""
    for kind, off, size, noff in entries:
        start = base + off
        stop = min(start + size, end)
        if start >= stop:
            continue
        nul = names.find(b"\0", noff)
        name = names[noff : nul if nul >= 0 else len(names)].decode("latin-1")
        if kind in (NESTED, NESTED_DA):
            _block(data, start, stop, f"{prefix}{name}/" if name else prefix, out, depth + 1)
        else:
            out.append(Member(prefix + name, kind, data[start:stop]))


def members(data: bytes) -> list[Member]:
    out: list[Member] = []
    _block(data, 0, len(data), "", out, 0)
    return out


def _texture_struct(data: bytes) -> tuple[str, rw.Chunk]:
    """(name, the Texture Native STRUCT chunk) of a type-3 member."""
    n = data[0]
    name = data[1 : 1 + n].split(b"\0")[0].decode("latin-1")
    at = 1 + n + 1 + 7
    c = rw.read_chunk(data, at, len(data))
    if c is None or c.type != rw.STRUCT:
        raise rw.RwError(f"{name}: no texture struct")
    return name, c


def texture_name(data: bytes) -> str:
    return _texture_struct(data)[0]


def parse_texture(data: bytes) -> rwgc.TextureNative:
    name, st = _texture_struct(data)
    try:
        w, h, fmt, filt, img = rwgc._decode_one(data, st, st.version < 0x33000)
        return rwgc.TextureNative(name, "", w, h, fmt, filt, img)
    except (rw.RwError, ValueError, struct.error) as e:
        return rwgc.TextureNative(name, "", 0, 0, 0, 0, None, error=str(e))
