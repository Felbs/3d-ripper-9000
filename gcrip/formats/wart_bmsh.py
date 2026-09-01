"""Warthog ``.bmsh`` meshes - the geometry resources inside a ``WART3.00`` ``.hog`` archive.

Once :mod:`gcrip.plugins.wart_hog` decompresses a member, a ``.bmsh`` is a resource header
followed by a **chain of section tables**, each table one sub-mesh::

    u32 count            sections in this table
    u32 total            bytes of section data that follow the table
    u32 size[count]      the sections, back to back after the table

``sum(size) == total`` on every table seen, and the chain of tables ends **exactly** at the end
of the member.  That pair of identities is the whole parser: they locate the tables without any
offset to trust, and a wrong start position runs off the end instead of quietly succeeding.

Within a table, section 0 is setup (GX register state and runtime pointers, relocated at load
and meaningless in the file), one section is a **GX display list**, and the rest are the vertex
arrays.  The display list is found by content - it opens with a GX primitive opcode and has to
tile its section exactly, ending on zero padding - rather than by position, because its index
is not constant across meshes.

The index stride is derived, not assumed, and so is the width of each column.  **Widths vary
within a single vertex**: the skinned meshes index position and normal with big-endian ``u16``
and the texture coordinate with ``u8``, so their lists tile at stride 5 and no single width can
read them.  Every way of splitting the stride into 1- and 2-byte columns is tried and scored by
how many columns find a home, so a stride that merely tiles loses to one that explains all of
its columns.  A column is matched to an array by requiring ``(max + 1) * element`` to equal the
section size to within its four-byte padding.  Element sizes seen: **12** for positions
(``f32`` x3), **3** for normals (``s8`` x3) and **4** for texture coordinates (``s16`` x2,
scaled by 1/16384).

**Column order is not array order.**  On the larger meshes the columns run position, normal,
texcoord against arrays in the same order, but on the smaller ones column 1 indexes the *last*
array - so the mapping is solved by the size identity rather than assumed from position.

Vertices are **de-indexed**: position and texcoord have separate index columns and separate
array lengths, so there is no single vertex list in the file, and one is built by walking the
display list once and resolving each column at every entry.

The resource header carries a bounding volume that checks the result independently::

    +0   f32[3]  half-extent      +12  f32[3]  centre      +24  f32  radius

**relative to a base that is 72 on most meshes and 92 on the variant header** four of the
sixteen samples use, so it is located by signature rather than assumed - a bounding sphere's
radius lies between the largest half-extent and the diagonal, which narrows a header to a
handful of candidates.

The check is then that the decoded geometry reproduces one of them.  It does on **16 of 16**
sampled members, and in every case **exactly one** candidate matches - centre and extent to
better than 1% of the extent.  Reading the block at a fixed 72 is what first made two meshes
look misplaced by 740 units when their geometry was right and the offset was wrong; both
sub-meshes of each agreed with each other, which is what said so.

**Nothing here rests on a triangle count**, which is all a display-list scanner can offer - the
generic one manages 4 of these 16 files and 504 triangles against 16 and 6,672.

A section may be **empty**.  Rejecting a table that contains a zero size looks like a sensible
guard and is wrong: it threw out every skinned character mesh, whose tables carry long runs of
them.  ``sum(size) == total`` and the chain reaching the member's end are the real guards, and
they hold with the zeroes in place.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

KIND_AT = 4
KIND_MESH = 10
BOUND_BYTES = 28
# the bounding block sits at 72 on most meshes and 92 on the variant header; both are attested,
# and `matching_bounds` locates it rather than trusting either
BOUND_OFFSETS = (72, 92)
MAX_SECTIONS = 64
ALIGN = 4
POSITION_ELEM = 12
UV_ELEM = 4
UV_SCALE = 1.0 / 16384.0
ELEMENTS = (3, 4, 6, 8, 12)
MAX_STRIDE = 16
# GX primitive opcodes; the low three bits select the vertex-attribute table
PRIMITIVES = (0x80, 0x90, 0x98, 0xA0)
LINES_AND_POINTS = (0xA8, 0xB0)


@dataclass
class SubMesh:
    positions: np.ndarray
    indices: np.ndarray
    uvs: np.ndarray | None = None


@dataclass
class Mesh:
    parts: list[SubMesh] = field(default_factory=list)


def is_bmsh(head: bytes) -> bool:
    if len(head) < KIND_AT + 4:
        return False
    (kind,) = struct.unpack_from(">I", head, KIND_AT)
    return kind == KIND_MESH << 24


def bounds(data: bytes, at: int) -> tuple[np.ndarray, np.ndarray, float] | None:
    """The half-extent, centre and radius stored at ``at``, if they read as a bounding volume.

    A bounding sphere's radius sits between the largest half-extent and the box diagonal, and
    that alone rejects most offsets.
    """
    if at < 0 or at + BOUND_BYTES > len(data):
        return None
    values = np.array(struct.unpack_from(">7f", data, at), np.float64)
    if not np.isfinite(values).all():
        return None
    extent, centre, radius = values[:3], values[3:6], float(values[6])
    if (extent < 0).any() or extent.max() <= 0 or radius <= 0:
        return None
    if not extent.max() - 1e-3 <= radius <= float(np.linalg.norm(extent)) * 1.001 + 1e-3:
        return None
    return extent, centre, radius


def bound_candidates(data: bytes, limit: int = 400) -> list[tuple[int, np.ndarray, np.ndarray, float]]:
    """Every offset in the header that reads as a bounding volume."""
    out = []
    for at in range(0, min(max(0, len(data) - BOUND_BYTES), limit), ALIGN):
        got = bounds(data, at)
        if got is not None:
            out.append((at, *got))
    return out


def matching_bounds(data: bytes, positions: np.ndarray, tolerance: float = 0.01) -> list[int]:
    """The header offsets whose bounding volume the geometry reproduces.

    On every sample this is exactly one offset, which is the independent confirmation that the
    display list, the stride and the column-to-array mapping are all right - none of which a
    triangle count would show.
    """
    if not len(positions):
        return []
    low, high = positions.min(0), positions.max(0)
    centre, extent = (low + high) / 2, (high - low) / 2
    slack = tolerance * max(1.0, float(extent.max()))
    return [
        at
        for at, ext, cen, _ in bound_candidates(data)
        if np.abs(cen - centre).max() < slack and np.abs(ext - extent).max() < slack
    ]


def _table(data: bytes, at: int):
    if at + 8 > len(data):
        return None
    count, total = struct.unpack_from(">2I", data, at)
    if not 0 < count <= MAX_SECTIONS or not 0 < total <= len(data):
        return None
    if at + 8 + count * 4 > len(data):
        return None
    sizes = struct.unpack_from(f">{count}I", data, at + 8)
    if any(s % ALIGN for s in sizes) or sum(sizes) != total:
        return None
    start = at + 8 + count * 4
    if start + total > len(data):
        return None
    sections, off = [], start
    for size in sizes:
        sections.append((off, size))
        off += size
    return sections, start + total


def tables(data: bytes) -> list[list[tuple[int, int]]]:
    """Every sub-mesh's sections, from the one chain that ends exactly at the member's end."""
    for begin in range(0, max(0, len(data) - 8), 4):
        chain, at = [], begin
        while at < len(data):
            got = _table(data, at)
            if got is None:
                break
            chain.append(got[0])
            at = got[1]
        if at == len(data) and chain:
            return chain
    return []


def _display_list(data: bytes, off: int, size: int, stride: int):
    """Tile a section as GX primitives, or ``None`` if this stride does not fit exactly."""
    prims, at, end = [], off, off + size
    while at < end:
        op = data[at]
        if op == 0:
            break
        kind = op & 0xF8
        if kind not in PRIMITIVES and kind not in LINES_AND_POINTS:
            return None
        if at + 3 > end:
            return None
        (n,) = struct.unpack_from(">H", data, at + 1)
        if n == 0 or at + 3 + n * stride > end:
            return None
        rows = np.frombuffer(data, np.uint8, n * stride, at + 3).reshape(n, stride)
        prims.append((kind, rows))
        at += 3 + n * stride
    while at < end and data[at] == 0:
        at += 1
    return prims if at == end and prims else None


def _columns(rows: np.ndarray, widths: tuple[int, ...]) -> list[np.ndarray]:
    """Split the display list's index bytes into columns of the given byte widths.

    **Widths vary per column, not per list.**  The skinned meshes index position and normal
    with `u16` and the texture coordinate with `u8` in the same vertex, so a single width for
    the whole list cannot read them - one such list tiles at stride 5.
    """
    out, at = [], 0
    for width in widths:
        if width == 1:
            out.append(rows[:, at].astype(np.int64))
        else:
            out.append((rows[:, at].astype(np.int64) << 8) | rows[:, at + 1])
        at += width
    return out


def _width_patterns(stride: int, max_columns: int):
    """Every way to split ``stride`` bytes into 1- and 2-byte columns, widest first."""
    if stride == 0:
        yield ()
        return
    if max_columns <= 0:
        return
    for width in (2, 1):
        if width <= stride:
            for rest in _width_patterns(stride - width, max_columns - 1):
                yield (width,) + rest


def _assign(maxima, arrays):
    """Match each index column to an array whose size equals ``(max + 1) * element`` to within
    the section's four-byte padding.  A column that matches nothing is a **matrix index** - the
    meshes drawn with more than one matrix carry one, with values running to about 250 that
    index no vertex array at all - and exactly one such column is tolerated.  Any more, or an
    unmatched column 0, means the stride is wrong, which is what keeps a bad stride from
    producing plausible nonsense."""
    used, out, loose = set(), [], 0
    for column, top in enumerate(maxima):
        need = top + 1
        pick = None
        for j, (off, size) in enumerate(arrays):
            if j in used:
                continue
            elem = size // need
            if elem in ELEMENTS and need * elem <= size < need * elem + ALIGN:
                pick = (j, off, elem)
                break
        if pick is None:
            loose += 1
            if loose > 1 or column == 0:
                return None
            out.append(None)
            continue
        used.add(pick[0])
        out.append(pick)
    return out


def _faces(kind: int, n: int) -> list[tuple[int, int, int]]:
    if kind == 0x98:
        return [(i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2) for i in range(n - 2)]
    if kind == 0xA0:
        return [(0, i + 1, i + 2) for i in range(n - 2)]
    if kind == 0x90:
        return [(i, i + 1, i + 2) for i in range(0, n - 2, 3)]
    if kind == 0x80:
        return [t for i in range(0, n - 3, 4) for t in ((i, i + 1, i + 2), (i, i + 2, i + 3))]
    return []


def _build(data, prims, widths, found):
    """De-index: one vertex an entry of the display list, faces into those entries."""
    rows = np.concatenate([r for _, r in prims])
    cols = _columns(rows, widths)
    _, pos_off, _ = found[0]
    need = int(cols[0].max()) + 1
    array = np.frombuffer(data, ">f4", need * 3, pos_off).reshape(need, 3)
    if not np.isfinite(array).all():
        return None
    positions = array[cols[0]]
    uvs = None
    for column, entry in list(zip(cols, found))[1:]:
        if entry is None:
            continue
        _, off, elem = entry
        if elem != UV_ELEM:
            continue
        count = int(column.max()) + 1
        raw = np.frombuffer(data, ">i2", count * 2, off).reshape(count, 2)
        uvs = (raw.astype(np.float32) * UV_SCALE)[column]
        break
    faces, base = [], 0
    for kind, r in prims:
        faces += [tuple(base + np.array(f)) for f in _faces(kind, len(r))]
        base += len(r)
    if not faces:
        return None
    return SubMesh(positions.astype(np.float32), np.array(faces, np.int32), uvs)


def _part(data: bytes, sections: list[tuple[int, int]]) -> SubMesh | None:
    """The sub-mesh a section table describes, or ``None``.

    Every (stride, width pattern) that tiles the display list is tried and scored by how many
    index columns find a home in the vertex arrays; the best-scoring reading wins, so a stride
    that happens to tile but leaves columns dangling loses to one that explains all of them.
    """
    for idx, (off, size) in enumerate(sections):
        if size < 3 or (data[off] & 0xF8) not in PRIMITIVES:
            continue
        arrays = [s for j, s in enumerate(sections) if j not in (0, idx) and s[1] > 0]
        if not arrays:
            continue
        best = None
        for stride in range(1, MAX_STRIDE + 1):
            prims = _display_list(data, off, size, stride)
            if not prims:
                continue
            rows = np.concatenate([r for _, r in prims])
            for widths in _width_patterns(stride, len(arrays) + 1):
                cols = _columns(rows, widths)
                found = _assign([int(c.max()) for c in cols], arrays)
                if found is None or found[0] is None or found[0][2] != POSITION_ELEM:
                    continue
                score = (sum(f is not None for f in found), len(found))
                if best is None or score > best[0]:
                    best = (score, prims, widths, found)
        if best is not None:
            part = _build(data, best[1], best[2], best[3])
            if part is not None:
                return part
    return None


def parse(data: bytes) -> Mesh | None:
    if not is_bmsh(data[:64]):
        return None
    mesh = Mesh()
    for sections in tables(data):
        part = _part(data, sections)
        if part is not None and len(part.indices):
            mesh.parts.append(part)
    return mesh if mesh.parts else None
