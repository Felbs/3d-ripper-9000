"""Artificial Mind & Movement's 2003 engine on GameCube (Scooby-Doo! Mystery Mayhem): the
per-level ``.gcr`` resource archive and the ``TEXDIC_*.txd`` texture dictionaries.

Read from the shipped ``engine_ret.elf`` + ``engine_ret.MAP``: ``EFRessourcesMgr::LoadLevel``
opens the level file as a ``DTStreamFAT`` - a table of ``DTFatRecord`` - and hands each record
to the class registered for its id in ``DTDynamicInstanciator`` (``__sinit_*`` calls to
``RegisterDynamicClass``)::

    u32 0x1dbb4, u32 records, u32, u32 (the first data offset)
    record (16)  u32 offset (from the table's end), u32 class id, u32 resource id,
                 u32 (a memory size, not the extent - a record runs to the next offset)

    class 24 EFStatic3dObjRW   the level: a RenderWare WORLD stream (0x0b)
    class 91 EF3dObjRes        a RenderWare CLUMP stream (0x10) - props, characters
    class 79 EFHAnimRes        RpHAnim animations      class 69 EFLogicCodeLib: PPC ELF code
    class 36 EFCollisionMap, 39 EFLogicCodeGC, 48 DTWaypointGrp, 73 EFAnimRes, 45 PLTypeRW ...

The dictionaries are not RW texture dictionaries but a run of ``(RW IMAGE chunk 0x18, u32 name
length, name)``: the image struct is ``u32 width, height, depth, stride`` little-endian, then
``stride x height`` bytes of pixels and, for 8-bit images, a 256 x RGBA8 palette.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import rwstream as rw

GCR_MAGIC = 0x1DBB4
RECORD = 16
CLASS_WORLD = 24
CLASS_CLUMP = 91
CLASS_NAMES = {
    24: "world",
    31: "properties",
    36: "collision",
    39: "logic",
    45: "particles",
    48: "waypoints",
    60: "descriptor",
    69: "code",
    72: "data",
    73: "anim",
    79: "hanim",
    82: "cutscene",
    91: "obj",
}
IMAGE = 0x18
MAX_RECORDS = 1 << 16


@dataclass
class Record:
    offset: int  # absolute, in the file
    end: int
    class_id: int
    resource: int


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def is_gcr(head: bytes, size: int) -> bool:
    if len(head) < 32 or size < 32:
        return False
    magic, count, _, first = struct.unpack_from(">4I", head, 0)
    if magic != GCR_MAGIC or not 0 < count <= MAX_RECORDS or 16 + RECORD * count > size:
        return False
    off, cls, _res, _size = struct.unpack_from(">4I", head, 16)
    return off == 0 and cls in CLASS_NAMES and first + 16 + RECORD * count <= size + 16


def records(data: bytes) -> list[Record]:
    count = _u32(data, 4)
    base = 16 + RECORD * count
    rows = []
    for i in range(min(count, MAX_RECORDS)):
        at = 16 + RECORD * i
        if at + RECORD > len(data):
            break
        off, cls, res, _size = struct.unpack_from(">4I", data, at)
        if base + off <= len(data):
            rows.append((base + off, cls, res))
    rows.sort()
    out = []
    for k, (off, cls, res) in enumerate(rows):
        end = rows[k + 1][0] if k + 1 < len(rows) else len(data)
        out.append(Record(off, end, cls, res))
    return out


def _stream_extent(data: bytes, rec: Record) -> int:
    """A RenderWare record's real end: its top chunk's size (the table's extent includes the
    padding to the next record)."""
    if rec.offset + 12 > len(data):
        return rec.end
    _t, size, _v = struct.unpack_from("<3I", data, rec.offset)
    return min(rec.end, rec.offset + 12 + size)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """The RenderWare members: ``world.bsp`` and ``obj_<id>.dff``.  Everything else in the
    table is code, animation, collision or script data."""
    out = []
    for rec in records(data):
        if rec.class_id == CLASS_WORLD and rw.looks_like_stream(
            data[rec.offset : rec.offset + 12], rec.end - rec.offset, (rw.WORLD,)
        ):
            out.append(
                (
                    f"world_{rec.resource & 0xFFFFFFFF:x}.bsp",
                    data[rec.offset : _stream_extent(data, rec)],
                )
            )
        elif rec.class_id == CLASS_CLUMP and rw.looks_like_stream(
            data[rec.offset : rec.offset + 12], rec.end - rec.offset, (rw.CLUMP,)
        ):
            out.append((f"obj_{rec.resource:x}.dff", data[rec.offset : _stream_extent(data, rec)]))
    return out


# ---------------------------------------------------------------------------
# TEXDIC_*.txd: RW image chunks with names
# ---------------------------------------------------------------------------


def is_texdic(head: bytes) -> bool:
    if len(head) < 40:
        return False
    t, size, _lib, st, st_size = struct.unpack_from("<5I", head, 0)
    return t == IMAGE and st == rw.STRUCT and st_size == 16 and size >= 28


def _images(data: bytes):
    p = 0
    while p + 12 <= len(data):
        t, size, _lib = struct.unpack_from("<3I", data, p)
        if t != IMAGE or p + 12 + size > len(data):
            break
        q = p + 12 + size
        if q + 4 > len(data):
            break
        n = struct.unpack_from("<I", data, q)[0]
        if n > 256 or q + 4 + n > len(data):
            break
        name = data[q + 4 : q + 4 + n].split(b"\0")[0].decode("latin-1")
        yield name, p + 12, p + 12 + size
        p = q + 4 + n


def texdic_names(data: bytes) -> list[str]:
    return [name for name, _, _ in _images(data)]


def _decode_image(data: bytes, at: int, end: int) -> np.ndarray | None:
    st, st_size, _lib = struct.unpack_from("<3I", data, at)
    if st != rw.STRUCT or st_size < 16:
        return None
    w, h, depth, stride = struct.unpack_from("<4I", data, at + 12)
    p = at + 12 + st_size
    if not (0 < w <= 4096 and 0 < h <= 4096) or p + stride * h > end:
        return None
    if depth == 32:
        px = np.frombuffer(data, np.uint8, stride * h, p).reshape(h, stride)[:, : w * 4]
        return px.reshape(h, w, 4).copy()
    if depth in (4, 8):
        n = 16 if depth == 4 else 256
        pal_at = p + stride * h
        if pal_at + 4 * n > end:
            return None
        palette = np.frombuffer(data, np.uint8, 4 * n, pal_at).reshape(n, 4)
        rows = np.frombuffer(data, np.uint8, stride * h, p).reshape(h, stride)
        if depth == 4:
            idx = np.stack([rows >> 4, rows & 15], axis=2).reshape(h, -1)[:, :w]
        else:
            idx = rows[:, :w]
        return palette[idx]
    return None


def texdic_images(data: bytes) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name, at, end in _images(data):
        img = _decode_image(data, at, end)
        if img is not None:
            out.setdefault(name, img)
    return out
