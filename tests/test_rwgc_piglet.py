"""Piglet's RenderWare GameCube native header (gcrip.formats.rwgc.decode_native_piglet) and the
two stream-walk fixes that make it reachable (gcrip.formats.rwstream).

`renderware.py` returned scenes for 68 of Piglet's 1,001 geometry assets.  Three things were in
the way, and each has a test here:

* a FRAMELIST whose declared size overshoots the GEOMETRYLIST that follows, so the walk read
  garbage as a chunk id;
* BINMESH and NATIVEDATA written as direct children of GEOMETRY rather than inside EXTENSION;
* a native header the attribute-table reader refuses - array offsets declared, meshes tabled.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import rwgc, rwstream as rw

LIB = 0x1003FFFF


def chunk(t: int, body: bytes) -> bytes:
    return struct.pack("<3I", t, len(body), LIB) + body


def pad32(b: bytes) -> bytes:
    return b + bytes(-len(b) % 32)


def native_block(nverts: int, strips, colours: bool = True) -> bytes:
    """A Piglet-shaped native block: header with array offsets and a mesh table, then lists,
    then padded arrays."""
    rng = np.random.default_rng(3)
    pos = rng.uniform(-5, 5, (nverts, 3)).astype(">f4").tobytes()
    nrm = rng.normal(size=(nverts, 3))
    nrm = (nrm / np.linalg.norm(nrm, axis=1)[:, None]).astype(">f4").tobytes()
    col = bytes([200, 100, 50, 255] * nverts)
    uv = rng.uniform(0, 1, (nverts, 2)).astype(">f4").tobytes()
    width = 1 if nverts <= 256 else 2
    attrs = 3 + int(colours)
    lists = []
    for idx in strips:
        raw = bytearray([0x98]) + struct.pack(">H", len(idx))
        for i in idx:
            raw += (struct.pack(">B", i) if width == 1 else struct.pack(">H", i)) * attrs
        lists.append(pad32(bytes(raw)))
    lists_bytes = b"".join(lists)
    arrays = [pad32(pos), pad32(nrm)] + ([pad32(col)] if colours else []) + [pad32(uv)]
    offs = []
    at = len(lists_bytes)
    for a in arrays:
        offs.append(at)
        at += len(a)
    if colours:
        o_pos, o_nrm, o_col, o_uv = offs
    else:
        o_pos, o_nrm, o_uv = offs
        o_col = 0
    hsz = rwgc.PIGLET_HEADER_BASE + 8 * len(lists)
    head = bytearray(hsz)
    head[rwgc.PIGLET_FLAGS_AT] = rwgc.PIGLET_HAS_COLOURS if colours else 0
    struct.pack_into(">4I", head, rwgc.PIGLET_ARRAYS_AT, o_pos, o_nrm, o_col, o_uv)
    off = 0
    for i, l in enumerate(lists):
        struct.pack_into(">2I", head, rwgc.PIGLET_MESHES_AT + 8 * i, len(l), off)
        off += len(l)
    data = lists_bytes + b"".join(arrays)
    return struct.pack("<3I", rw.PLATFORM_GAMECUBE, hsz, len(data)) + bytes(head) + data


def test_the_piglet_header_decodes_positions_normals_and_strips():
    body = native_block(40, [list(range(40)), [0, 5, 10, 15]])
    assert rwgc.looks_like_piglet_native(body)
    meshes = rwgc.decode_native_piglet(body, 40)
    assert [m.mesh for m in meshes] == [0, 1]
    assert len(meshes[0].triangles) == 38
    assert len(meshes[1].triangles) == 2
    assert meshes[0].colors is not None and meshes[0].uvs is not None
    n = meshes[0].normals.astype(np.float64)
    assert np.abs(np.sqrt((n * n).sum(1)) - 1).max() < 1e-5


def test_two_byte_indices_above_256_vertices():
    body = native_block(400, [list(range(0, 400, 2))], colours=False)
    meshes = rwgc.decode_native_piglet(body, 400)
    assert meshes[0].colors is None
    assert int(meshes[0].triangles.max()) == 398


def test_a_header_whose_arrays_do_not_fit_the_vertex_count_is_refused():
    """The identity: the gap from the position array to the normal array is the vertex count
    times twelve, rounded up to 32.  A header claiming 40 vertices for a 100-vertex block
    fails it."""
    body = native_block(100, [list(range(100))])
    with pytest.raises(rw.RwError, match="position array"):
        rwgc.decode_native_piglet(body, 40)


def test_an_index_past_the_vertex_array_is_refused():
    body = bytearray(native_block(40, [list(range(40))]))
    hsz = struct.unpack_from("<I", body, 4)[0]
    body[12 + hsz + 3] = 99  # first index of the first strip
    with pytest.raises(rw.RwError, match="indexes vertex"):
        rwgc.decode_native_piglet(bytes(body), 40)


def test_the_attribute_table_reader_does_not_claim_this_header():
    body = native_block(40, [list(range(40))])
    with pytest.raises(rw.RwError):
        rwgc.decode_native(body, False)


# -- the stream-walk fixes ----------------------------------------------------------------


def test_a_chunk_size_that_overshoots_the_next_header_is_corrected():
    """28 of 146 sampled Piglet clumps declare FRAMELIST 21 bytes long of the GEOMETRYLIST
    that follows; the walk must land on the header, not inside it."""
    first = chunk(0x0E, b"\x11" * 40)
    second = chunk(0x1A, b"\x22" * 16)
    data = bytearray(first + second)
    struct.pack_into("<I", data, 4, 40 + 21)  # overshoot by 21
    got = list(rw.chunks(bytes(data), 0, len(data)))
    assert [c.type for c in got] == [0x0E, 0x1A]


def test_a_correct_chunk_size_is_left_alone():
    data = chunk(0x0E, b"\x11" * 40) + chunk(0x1A, b"\x22" * 16)
    got = list(rw.chunks(data, 0, len(data)))
    assert [c.type for c in got] == [0x0E, 0x1A]
    assert got[1].off == 12 + 40 + 12


def test_native_data_as_a_direct_child_of_geometry_is_found():
    struct_body = struct.pack("<4I", rw.GEOM_NATIVE, 1, 3, 1)
    native = native_block(3, [[0, 1, 2]])
    geom = chunk(
        0x0F,
        chunk(0x01, struct_body)
        + chunk(0x08, chunk(0x01, struct.pack("<I", 0)))
        + chunk(0x03, b"")
        + chunk(rw.NATIVEDATA, chunk(0x01, native)),
    )
    g = rw._parse_geometry(geom, next(rw.chunks(geom, 0, len(geom))))
    assert g.native is not None
    assert rwgc.looks_like_piglet_native(g.native)
