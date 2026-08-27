"""Retro Studios PAK archives (Metroid Prime, Metroid Prime 2: Echoes). Layout checked
against the GameCube discs' Metroid*.pak files.

  u16 major (3), u16 minor (5), u32 0
  u32 named count; per entry: fourcc type, u32 id, u32 name length, name (no NUL)
  u32 resource count; per entry (0x14 bytes): u32 compressed flag, fourcc type, u32 id,
      u32 size (32-byte aligned, 0xFF padded), u32 absolute offset
Compressed resources: u32 decompressed size, then a zlib stream (Prime 1) or Retro's
segmented LZO1X (Echoes: repeated s16 segment size + payload, negative = stored raw,
0x4000 bytes per segment). Both games label their PAKs version 3.5; the codec is sniffed
from the zlib header bytes.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field

from gcrip.formats import lzo

MAGIC = b"\x00\x03\x00\x05"
_ID_RE = re.compile(r"0x([0-9A-Fa-f]{8})\.([A-Za-z0-9]{4})$")


class PakError(ValueError):
    pass


@dataclass
class Resource:
    type: str
    id: int
    offset: int
    size: int
    compressed: bool
    name: str | None = None


@dataclass
class Pak:
    resources: list[Resource] = field(default_factory=list)
    names: dict[tuple[str, int], str] = field(default_factory=dict)

    def find(self, type_: str, id_: int) -> Resource | None:
        for r in self.resources:
            if r.id == id_ and r.type == type_:
                return r
        return None


def is_pak(name: str, head: bytes) -> bool:
    return name.lower().endswith(".pak") and head[:8] == MAGIC + b"\x00\x00\x00\x00"


def parse(data: bytes) -> Pak:
    if data[:4] != MAGIC:
        raise PakError("not a Retro PAK (version != 3.5)")
    pak = Pak()
    (n_named,) = struct.unpack_from(">I", data, 8)
    pos = 12
    for _ in range(n_named):
        type_, id_, nlen = struct.unpack_from(">4sII", data, pos)
        pos += 12
        name = data[pos : pos + nlen].decode("ascii", "replace")
        pos += nlen
        pak.names[(type_.decode("ascii", "replace"), id_)] = name
    (n_res,) = struct.unpack_from(">I", data, pos)
    pos += 4
    seen: set[tuple[str, int]] = set()
    for _ in range(n_res):
        comp, type_, id_, size, off = struct.unpack_from(">I4sIII", data, pos)
        pos += 0x14
        t = type_.decode("ascii", "replace")
        if (t, id_) in seen:  # PAKs list some resources twice (streaming duplicates)
            continue
        seen.add((t, id_))
        if off + size > len(data):
            raise PakError(f"resource {t} {id_:08X} runs past the end of the file")
        pak.resources.append(Resource(t, id_, off, size, comp != 0, pak.names.get((t, id_))))
    return pak


def resource_name(r: Resource) -> str:
    """Manifest file name: `<name>_0x<id>.<TYPE>` for named resources, `0x<id>.<TYPE>` else.
    The id always stays in the name so cross references (TXTR ids in a CMDL) resolve."""
    if r.name:
        safe = re.sub(r"[^A-Za-z0-9_.\-]+", "_", r.name).strip("_")
        if safe:
            return f"{safe}_0x{r.id:08X}.{r.type}"
    return f"0x{r.id:08X}.{r.type}"


def parse_name(name: str) -> tuple[str, int] | None:
    """Inverse of resource_name on a basename: (type, id) or None."""
    m = _ID_RE.search(name)
    if not m:
        return None
    return m.group(2), int(m.group(1), 16)


def read(data: bytes, r: Resource) -> bytes:
    raw = data[r.offset : r.offset + r.size]
    if not r.compressed:
        return raw
    return decompress(raw)


def decompress(raw: bytes) -> bytes:
    (total,) = struct.unpack_from(">I", raw, 0)
    body = raw[4:]
    looks_zlib = len(body) >= 2 and body[0] == 0x78 and ((body[0] << 8) | body[1]) % 31 == 0
    codecs = [_zlib, _lzo] if looks_zlib else [_lzo, _zlib]
    err: Exception | None = None
    for codec in codecs:
        try:
            out = codec(body, total)
        except (zlib.error, lzo.LzoError) as e:
            err = e
            continue
        if len(out) == total:
            return out
        err = PakError(f"decompressed {len(out)} bytes, expected {total}")
    raise PakError(f"resource decompression failed: {err}")


def _zlib(body: bytes, total: int) -> bytes:
    return zlib.decompress(body)


def _lzo(body: bytes, total: int) -> bytes:
    return lzo.decompress_segmented(body, total)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    pak = parse(data)
    return [(resource_name(r), read(data, r)) for r in pak.resources]
