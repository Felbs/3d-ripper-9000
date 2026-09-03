"""RenderWare GameCube native geometry (gcrip.formats.rw_native).

`docs/OPEN.md` recorded Piglet's blocked geometry as a raw block "with no GX display lists in
it".  It is display lists.  The reader rests on two identities, and the tests below check each
holds on good data and fails on damaged data - an identity that cannot fail is not evidence.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import rw_native


def strip(indices) -> bytes:
    out = bytearray([rw_native.STRIP]) + struct.pack(">H", len(indices))
    for i in indices:
        out += struct.pack(">H", i) * 4  # one index, repeated for every attribute
    return bytes(out)


def unit_normals(n: int) -> bytes:
    rng = np.random.default_rng(7)
    v = rng.normal(size=(n, 3))
    v /= np.linalg.norm(v, axis=1)[:, None]
    return v.astype(">f4").tobytes()


def spread_positions(n: int) -> bytes:
    rng = np.random.default_rng(11)
    return (rng.uniform(-10, 10, size=(n, 3))).astype(">f4").tobytes()


def make_group(n: int, lead: int = 5) -> bytes:
    """One group: a strip using every index 0..n-1, then positions, a gap, then normals."""
    body = bytearray(strip(list(range(n))))
    body += bytes(lead)
    body += spread_positions(n)
    body += bytes(rw_native.ARRAY_GAP)
    body += unit_normals(n)
    return bytes(body)


def make_clump(payload: bytes, frame_bytes: int = 32) -> bytes:
    """A CLUMP whose chunk walk covers STRUCT and FRAMELIST and then meets the native block."""
    inner = bytearray()
    inner += struct.pack("<3I", 0x01, 12, 0x1003FFFF) + bytes(12)  # STRUCT
    inner += struct.pack("<3I", 0x0E, frame_bytes, 0x1003FFFF) + bytes(frame_bytes)
    inner += struct.pack("<3I", 0, 0, 0)  # the terminator the native block sits behind
    inner += payload
    return struct.pack("<3I", rw_native.CLUMP, len(inner), 0x1003FFFF) + bytes(inner)


def test_a_group_is_found_and_its_arrays_resolve():
    data = make_group(64)
    groups = rw_native.groups(data)
    assert len(groups) == 1
    g = groups[0]
    assert g.vertices == 64 and g.resolved
    assert g.positions_at == g.normals_at - rw_native.ARRAY_GAP - 64 * 12
    assert len(rw_native.triangles(data, g)) == 62


def test_the_indices_must_cover_the_array_exactly():
    """A strip that skips a vertex is not a group: `distinct == max + 1` is what says a
    candidate run belongs to one array, and a false run on the real file claimed 53,054
    vertices with 100 distinct values."""
    body = bytearray(strip([i for i in range(64) if i != 30]))
    body += bytes(5) + spread_positions(64) + bytes(rw_native.ARRAY_GAP) + unit_normals(64)
    assert rw_native.candidates(bytes(body)) == []


def test_all_four_index_columns_must_agree():
    out = bytearray([rw_native.STRIP]) + struct.pack(">H", 64)
    for i in range(64):
        out += struct.pack(">4H", i, i, i, (i + 1) % 64)  # one column disagrees
    out += bytes(5) + spread_positions(64) + bytes(rw_native.ARRAY_GAP) + unit_normals(64)
    assert rw_native.candidates(bytes(out)) == []


def test_a_group_whose_normals_are_not_unit_length_is_declined():
    """The positions are located *from* the normals, so without them there is nothing to
    read - the group is left out rather than guessed at."""
    body = bytearray(strip(list(range(64))))
    body += bytes(5) + spread_positions(64) + bytes(rw_native.ARRAY_GAP)
    body += (np.full((64, 3), 3.0)).astype(">f4").tobytes()
    groups = rw_native.groups(bytes(body))
    assert len(groups) == 1 and not groups[0].resolved


def test_both_identities_hold_and_are_reported():
    from gcrip import identities

    data = make_group(64)
    results = {r.identity.name: r for r in identities.check(rw_native, data)}
    assert results["the indices cover the vertex array exactly"].held is True
    assert results["the normals are unit length"].held is True
    assert "1 of 1" in results["the normals are unit length"].detail


def test_the_tail_is_found_behind_the_chunked_half():
    # big enough to clear MIN_TAIL, which is what stops a few stray bytes being read as one
    clump = make_clump(make_group(512))
    at = rw_native.tail_of(clump)
    assert at is not None
    assert clump[at] == rw_native.STRIP


def test_a_clump_with_no_native_block_is_declined():
    assert rw_native.tail_of(make_clump(bytes(16))) is None
    assert rw_native.tail_of(b"not a clump") is None


def test_the_plugin_emits_one_primitive_a_group():
    from gcrip.plugins import rw_native as plugin

    clump = make_clump(make_group(512) + bytes(8) + make_group(256))
    assert plugin.detect("p/00042.dff", clump[:64], len(clump))
    scenes = plugin.extract(clump, "p/00042.dff", None)
    assert len(scenes) == 1
    assert len(scenes[0].primitives) == 2
    assert scenes[0].triangles == 510 + 254
    for p in scenes[0].primitives:
        assert p.material < len(scenes[0].materials)
        assert p.normals is not None and len(p.normals) == len(p.positions)
        assert int(p.indices.max()) < len(p.positions)


def test_the_plugin_says_how_many_groups_it_left_out():
    from gcrip.plugins import rw_native as plugin

    good = make_group(512)
    bad = bytearray(strip(list(range(256))))
    bad += bytes(5) + spread_positions(256) + bytes(rw_native.ARRAY_GAP)
    bad += (np.full((256, 3), 2.0)).astype(">f4").tobytes()
    scenes = plugin.extract(make_clump(good + bytes(8) + bytes(bad)), "p/x.dff", None)
    assert scenes[0].warnings and "1 of 2" in scenes[0].warnings[0]
