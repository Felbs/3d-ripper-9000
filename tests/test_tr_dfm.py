"""Terminal Reality ``_dfm`` header and part table (gcrip.formats.tr_dfm)."""

from __future__ import annotations

import struct

from gcrip.formats import tr_dfm

BAADF00D = bytes.fromhex("0df0adba") * 24


def make_dfm(parts: list[tuple[str, int, tuple]], bones: int = 82,
             skeleton: str = "SOLDIER_DEFAULT.SKL") -> bytes:
    out = bytearray(struct.pack("<6I", 2, 1, len(parts), bones, 1, 0))
    raw = skeleton.encode("latin-1")
    field = raw + b"\0" + BAADF00D[: tr_dfm.HEADER - 24 - len(raw) - 1]
    out += field[: tr_dfm.HEADER - 24]
    assert len(out) == tr_dfm.HEADER
    for name, bone, box in parts:
        nm = name.encode("latin-1")
        out += (nm + b"\0" * (tr_dfm.NAME - len(nm)))[: tr_dfm.NAME]
        out += struct.pack("<I", bone)
        out += struct.pack("<6f", *box)
    return bytes(out)


PARTS = [
    ("binoculars2", 68, (-0.499, -0.519, -0.206, -0.270, 0.008, 0.303)),
    ("canteen", 32, (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)),
    ("gasmask", 5, (0.0, 0.0, 0.0, 0.5, 0.25, 0.125)),
]


def test_reads_the_part_table():
    m = tr_dfm.mesh(make_dfm(PARTS))
    assert m is not None
    assert m.bone_count == 82
    assert m.skeleton == "SOLDIER_DEFAULT.SKL"
    assert [p.name for p in m.parts] == ["binoculars2", "canteen", "gasmask"]
    assert [p.bone for p in m.parts] == [68, 32, 5]


def test_every_box_is_a_box():
    """min <= max on all three axes, on every record - the check that pins the 58-byte stride."""
    m = tr_dfm.mesh(make_dfm(PARTS))
    for p in m.parts:
        for lo, hi in zip(p.box_min, p.box_max):
            assert lo <= hi


def test_an_inverted_box_is_rejected():
    bad = list(PARTS)
    bad[1] = ("canteen", 32, (1.0, 1.0, 1.0, -1.0, -1.0, -1.0))
    assert tr_dfm.mesh(make_dfm(bad)) is None


def test_a_bone_outside_the_skeleton_is_rejected():
    bad = list(PARTS)
    bad[0] = ("binoculars2", 999, PARTS[0][2])
    assert tr_dfm.mesh(make_dfm(bad)) is None


def test_detection_and_truncation():
    data = make_dfm(PARTS)
    assert tr_dfm.is_dfm(data[:16])
    assert not tr_dfm.is_dfm(struct.pack("<4I", 7, 1, 3, 82))
    assert tr_dfm.mesh(data[:-10]) is None


def test_the_stride_is_fifty_eight():
    """30-byte name, u32 bone, six floats - and 59 parts end at 3,526 on soldier.dfm."""
    assert tr_dfm.NAME + 4 + 24 == tr_dfm.STRIDE
    assert tr_dfm.HEADER + 59 * tr_dfm.STRIDE == 3526


# -- the geometry blocks --------------------------------------------------------------------


def make_block(a: int, b: int, verts, tris, bones: int = 82) -> bytes:
    """One sub-mesh block: header, `verts` bytes of vertex data, then the triangle list."""
    payload = len(verts) + tr_dfm.PAYLOAD_BIAS
    n = len(verts) // tr_dfm.RIGID_STRIDE
    head = struct.pack(
        "<10I", a, b, 2, payload, tr_dfm.PAYLOAD_BIAS, n, len(tris), bones, 0, tr_dfm.BLOCK_TAIL
    )
    body = bytearray(head) + bytes(verts)
    for t in tris:
        body += struct.pack("<3H", *t)
    return bytes(body)


def rigid_vertices(n: int) -> bytes:
    """`n` twenty-byte records carrying the constants the real ones do."""
    out = bytearray()
    for i in range(n):
        rec = bytearray(bytes([(i * 37 + k * 11) & 0xFF for k in range(tr_dfm.RIGID_STRIDE)]))
        rec[3], rec[4], rec[15], rec[16], rec[17] = 0x04, 0x00, 0x44, 0x01, 0xFE
        out += rec
    return bytes(out)


def strip(n: int) -> list[tuple[int, int, int]]:
    """A triangle list that uses every vertex, so the largest index is n - 1."""
    return [(i, i + 1, i + 2) for i in range(n - 2)]


def make_geometry(parts, blocks, bones: int = 82) -> bytes:
    body = make_dfm(parts, bones=bones)
    for a, b, n in blocks:
        body += make_block(a, b, rigid_vertices(n), strip(n), bones)
    return body


def test_blocks_are_found_and_tile_to_the_end_of_the_file():
    data = make_geometry(PARTS, [(0, 1, 12), (3, 4, 25), (7, 7, 8)])
    found = tr_dfm.blocks(data)
    assert [b.vertices for b in found] == [12, 25, 8]
    assert [b.triangles for b in found] == [10, 23, 6]
    assert tr_dfm.tiles(data, found), [(b.offset, b.end) for b in found]


def test_the_rigid_stride_is_read_off_the_payload_word():
    data = make_geometry(PARTS, [(0, 1, 12)])
    b = tr_dfm.blocks(data)[0]
    assert b.rigid
    assert b.vertex_bytes == 12 * tr_dfm.RIGID_STRIDE
    assert b.index_at == b.vertex_at + b.vertex_bytes


def test_a_wider_block_is_not_called_rigid():
    """The skinned blocks carry a variable-length influence list, so the stride is not 20."""
    data = make_dfm(PARTS) + make_block(0, 1, b"\x11" * 137, strip(6))
    b = tr_dfm.blocks(data)[0]
    assert not b.rigid
    assert b.vertex_bytes == 137


def test_every_index_lands_inside_its_own_block():
    data = make_geometry(PARTS, [(0, 1, 12), (3, 4, 25)])
    for b in tr_dfm.blocks(data):
        assert tr_dfm.indices(data, b).max() == b.vertices - 1


def test_both_block_identities_hold_and_can_fail():
    from gcrip import identities

    data = make_geometry(PARTS, [(0, 1, 12), (3, 4, 25)])
    results = {r.identity.name: r for r in identities.check(tr_dfm, data)}
    assert results["the geometry blocks tile"].held is True
    assert results["every triangle indexes its own block"].held is True

    # a block that claims one vertex too many no longer indexes 0..n-1, and stops tiling
    hurt = bytearray(data)
    at = tr_dfm.blocks(data)[0].offset
    struct.pack_into("<I", hurt, at + 20, 13)
    hurt_results = {r.identity.name: r for r in identities.check(tr_dfm, bytes(hurt))}
    assert hurt_results["every triangle indexes its own block"].held is False


def test_a_block_whose_payload_lies_breaks_the_tiling():
    data = make_geometry(PARTS, [(0, 1, 12), (3, 4, 25)])
    hurt = bytearray(data)
    at = tr_dfm.blocks(data)[0].offset
    struct.pack_into("<I", hurt, at + 12, 12 * tr_dfm.RIGID_STRIDE + 8)
    found = tr_dfm.blocks(bytes(hurt))
    assert not tr_dfm.tiles(bytes(hurt), found)
