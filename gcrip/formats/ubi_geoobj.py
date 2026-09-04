"""Batman: Rise of Sin Tzu geometric objects - ``binary_vr/<level>/3d/gli/geoobj.bin`` out of
the ``.fat`` / ``.000`` archives (:mod:`gcrip.formats.ubi_fat`).

The file is ``u32 count`` then records ``u32 size, "x86\\0", payload`` (size counts the tag) -
the PC layout kept on GameCube, **little-endian**.  A record is one object: a header of
byte-packed counts (``u32 vertices`` at +0x1e, per-element vertex and strip-triangle counts)
and then elements, each

    vertices x 36   f32 x y z, f32 nx ny nz, f32 u v, u8 r g b a
    u32 corners, u8, u16 name length, "<file>.gmt^GameMaterial:<name>\\0", u16[corners]

where the corners are one triangle strip.  The reader does not decode the header's packing;
it finds each element by its run of unit-normal vertices (three or more) and validates the
index block that follows (the name ends in NUL, no corner past the run).  The bat museum's
312 objects give 387 elements / 86,384 triangles; the Batcycle's nine elements agree with
their vertex normals at 0.93-1.00.

Batman: Vengeance's ``.flt`` flat files share the archive but not this layout - their vertex
records are 24 bytes and carry no unit normals - so they are still open.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

TAG = b"x86\0"
VERTEX = 36
MIN_RUN = 3
SEARCH = 4096
MAX_NAME = 512


@dataclass
class Element:
    name: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray
    indices: np.ndarray  # triangle list


@dataclass
class Model:
    elements: list[Element] = field(default_factory=list)


def is_geoobj(head: bytes, size: int) -> bool:
    if len(head) < 12 or head[8:12] != TAG:
        return False
    count, first = struct.unpack_from("<2I", head, 0)
    return 0 < count < 65536 and 4 < first <= size


def records(data: bytes):
    o = 4
    while o + 8 <= len(data):
        size = struct.unpack_from("<I", data, o)[0]
        if data[o + 4 : o + 8] != TAG or size < 4 or o + 4 + size > len(data):
            return
        yield data[o + 8 : o + 4 + size]
        o += 4 + size


def _run(p: bytes, o: int, limit: int | None = None) -> int:
    n = (len(p) - o) // VERTEX
    if limit:
        n = min(n, limit)
    if n <= 0:
        return 0
    v = np.frombuffer(p, "<f4", n * 9, o).reshape(n, 9)
    with np.errstate(all="ignore"):
        ok = (
            (np.abs(np.linalg.norm(v[:, 3:6], axis=1) - 1) < 0.02)
            & (np.abs(v[:, :3]) < 1e5).all(1)
            & (np.abs(v[:, 6:8]) < 64).all(1)
        )
    return int(np.argmin(ok)) if not ok.all() else n


def _strip(idx: np.ndarray) -> np.ndarray:
    a, b, c = idx[:-2], idx[1:-1], idx[2:]
    keep = (a != b) & (b != c) & (a != c)
    odd = (np.arange(len(a)) & 1).astype(bool)
    return np.where(odd[:, None], np.stack([b, a, c], 1), np.stack([a, b, c], 1))[keep]


def elements(p: bytes) -> list[Element]:
    out: list[Element] = []
    o = 0
    while o + VERTEX * MIN_RUN < len(p):
        found = None
        for s in range(o, min(o + SEARCH, len(p) - VERTEX * MIN_RUN)):
            if _run(p, s, MIN_RUN) >= MIN_RUN:
                found = s
                break
        if found is None:
            break
        n = _run(p, found)
        q = found + VERTEX * n
        if q + 7 > len(p):
            break
        corners = struct.unpack_from("<I", p, q)[0]
        length = struct.unpack_from("<H", p, q + 5)[0]
        name = p[q + 7 : q + 7 + length]
        q2 = q + 7 + length
        if (
            corners < 3
            or length > MAX_NAME
            or q2 + 2 * corners > len(p)
            or not name.endswith(b"\0")
        ):
            o = found + VERTEX
            continue
        idx = np.frombuffer(p, "<u2", corners, q2).astype(np.int64)
        if int(idx.max()) >= n:
            o = found + VERTEX
            continue
        v = np.frombuffer(p, "<f4", n * 9, found).reshape(n, 9)
        colors = np.frombuffer(p, np.uint8, n * VERTEX, found).reshape(n, VERTEX)[:, 32:36]
        tri = _strip(idx)
        if len(tri):
            out.append(
                Element(
                    name[:-1].decode("latin-1", "replace"),
                    np.ascontiguousarray(v[:, :3]).astype(np.float32),
                    np.ascontiguousarray(v[:, 3:6]).astype(np.float32),
                    np.ascontiguousarray(v[:, 6:8]).astype(np.float32),
                    (colors.astype(np.float32) / 255.0).astype(np.float32),
                    tri.ravel().astype(np.uint32),
                )
            )
        o = q2 + 2 * corners
    return out


def models(data: bytes) -> list[Model]:
    return [Model(elements(p)) for p in records(data)]


# -- .tsd textures ---------------------------------------------------------------------------

TSD_HEADER = 300  # u32 size, u32 1, u32 1, char[256] source path, then the picture header
TSD_DIMS_AT = 268
TSD_DXT1 = 0x17
TSD_RGBA8 = 0x09
TSD_C4 = (0x07, 0x0A)
PALETTE_GAP = 4
MAX_TEXTURE = 2048


def is_tsd(head: bytes, size: int) -> bool:
    if len(head) < 12:
        return False
    total, one, two = struct.unpack_from(">3I", head, 0)
    return total == size and one == 1 and two == 1 and size > TSD_HEADER


def tsd(data: bytes) -> np.ndarray | None:
    """A ``.tsd`` picture - PC layouts, not GX tiles: big-endian ``u32 width, height, kind``
    at +268 and the pixels at +300 as linear DXT1 (0x17), RGBA8 (0x09) or 4-bit indices
    (0x07 / 0x0a, low nibble first) with a 16-entry little-endian RGB565 palette after a
    4-byte gap.  Sin Tzu's ``x86`` data kept its PC pictures; the GameCube converts on load."""
    from gcrip.formats import dxt  # noqa: PLC0415 - keep the import local to the reader

    if not is_tsd(data[:12], len(data)):
        return None
    width, height, kind = struct.unpack_from(">3I", data, TSD_DIMS_AT)
    if not (0 < width <= MAX_TEXTURE and 0 < height <= MAX_TEXTURE):
        return None
    px = data[TSD_HEADER:]
    if kind == TSD_DXT1:
        need = max(width // 4, 1) * max(height // 4, 1) * 8
        return dxt.decode(px[:need], width, height, "DXT1") if len(px) >= need else None
    if kind == TSD_RGBA8:
        need = width * height * 4
        if len(px) < need:
            return None
        return np.frombuffer(px, np.uint8, need).reshape(height, width, 4).copy()
    if kind in TSD_C4:
        need = width * height // 2
        if len(px) != need + PALETTE_GAP + 32:
            return None  # the ones with mips keep their palette elsewhere - unread
        idx = np.frombuffer(px, np.uint8, need)
        pal = np.frombuffer(px, "<u2", 16, need + PALETTE_GAP).astype(np.uint32)
        colors = np.zeros((16, 4), np.uint8)
        colors[:, 0] = ((pal >> 11) & 31) * 255 // 31
        colors[:, 1] = ((pal >> 5) & 63) * 255 // 63
        colors[:, 2] = (pal & 31) * 255 // 31
        colors[:, 3] = 255
        nibbles = np.stack([idx & 15, idx >> 4], 1).ravel()
        return colors[nibbles].reshape(height, width, 4)
    return None
