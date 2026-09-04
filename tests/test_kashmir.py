"""Kashmir .dat scenes - City Racer, Taxi 3, Speed Challenge."""

import struct

import numpy as np

from gcrip.formats import kashmir
from gcrip.plugins import kashmir as plugin


def _chunk(kind, x, payload):
    return struct.pack("<3I", kind, x, len(payload)) + payload


MESH_ID = bytes(range(8))
MAT_A = b"A" * 8
MAT_B = b"B" * 8
ROOT = b"R" * 8
CHILD = b"C" * 8


def build_mesh(ident=MESH_ID, tmap=False):
    pts = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
    tris = [((0, 1, 2), (0, 1, 2), 0), ((0, 2, 3), (0, 2, 3), 1)]
    p = ident + bytes([14]) + struct.pack("<I", len(pts))
    p += b"".join(struct.pack("<3f", *v) for v in pts)
    p += struct.pack("<I", len(tris))
    for v, u, m in tris:
        p += struct.pack("<3H3HB", *v, *u, m)
    p += struct.pack("<I", len(uvs)) + b"".join(struct.pack("<2f", *u) for u in uvs)
    if tmap:
        p += b"TMAP\x01\x02" + b"".join(struct.pack("<3H", *u) for _, u, _ in tris)
    return p


def build_gc_texture(width=8, height=8):
    # an I8 (format 1) picture: 8x4 tiles, one byte a pixel, a gradient
    from gcrip.formats import gx_texture

    fmt = 1
    size = gx_texture.encoded_size(fmt, width, height)
    head = b"\0" + kashmir.GC_TAG + struct.pack(">9I", width, height, size, fmt, 0, 0, 5, 1, 0)
    head += struct.pack("<2H", 7, 0)
    assert len(head) == kashmir.GC_HEADER
    return head + bytes(range(size))[:size].ljust(size, b"\0")


def build_node(ident, parent, mesh, pos, rot, materials):
    p = ident + parent + mesh + bytes(2)
    p += struct.pack("<3f", *pos) + struct.pack("<3f", *rot)
    p += struct.pack("<I", len(materials)) + b"".join(materials) + struct.pack("<I", 0)
    return p


def build(author=b"tester", tmap=False, rotate=False):
    tail = author + b"\0" + b"Created/Modified using Kashmir\0" + bytes(13)
    n = len(tail) + 0x20 - kashmir.HEADER_BASE
    head = kashmir.MAGIC + struct.pack("<7I", 2, 0, 1000, 0, n, 0, 0) + tail
    assert len(head) == kashmir.HEADER_BASE + n
    mat_a = MAT_A + bytes(28) + b"skin.tga\0"
    mat_b = MAT_B + bytes(28)  # untextured
    body = _chunk(1, 101, build_mesh(tmap=tmap))
    body += _chunk(2, 0, mat_a) + _chunk(3, 0, build_gc_texture()) + _chunk(8, 0, MAT_A + b"skin\0")
    body += _chunk(2, 0, mat_b) + _chunk(8, 0, MAT_B + b"plain\0")
    body += _chunk(4, 100, build_node(ROOT, bytes(8), bytes(8), (10, 0, 0), (0, 0, 0), []))
    rot = (0, np.pi / 2, 0) if rotate else (0, 0, 0)
    body += _chunk(4, 100, build_node(CHILD, ROOT, MESH_ID, (0, 2, 0), rot, [MAT_A, MAT_B]))
    body += _chunk(8, 0, CHILD + b"quad\0")
    body += _chunk(102, 0, bytes(24))
    return head + body


def test_detect_needs_the_magic_and_version():
    data = build()
    assert kashmir.is_kashmir(data[:64])
    assert plugin.detect("Data/Cars/x.dat", data[:64], len(data))
    assert not plugin.detect("Data/Cars/x.dat", b"\0" * 64, 64)
    assert not plugin.detect("x.bin", data[:64], len(data))


def test_chunks_walk_from_the_header_length():
    kinds = [k for k, _, _ in kashmir.chunks(build())]
    assert kinds == [1, 2, 3, 8, 2, 8, 4, 4, 8]


def test_mesh_reads_vertices_triangles_and_uv_indices():
    m = kashmir.mesh(build_mesh())
    assert m is not None and m.positions.shape == (4, 3) and m.triangles.shape == (2, 3)
    assert m.uv_indices.tolist() == [[0, 1, 2], [0, 2, 3]] and m.materials.tolist() == [0, 1]
    assert np.allclose(m.uvs[2], (1.0, 1.0))
    # the optional TMAP block after the uvs does not break the read
    assert kashmir.mesh(build_mesh(tmap=True)) is not None
    assert kashmir.mesh(build_mesh()[:-3]) is None


def test_parse_links_textures_to_materials_and_names_objects():
    sc = kashmir.parse(build())
    assert sc is not None and sc.author == "tester"
    assert sc.materials == {MAT_A: "skin.tga", MAT_B: None}
    assert list(sc.textures) == ["skin.tga"] and sc.textures["skin.tga"].shape == (8, 8, 4)
    assert sc.names[CHILD] == "quad" and sc.nodes[CHILD].parent == ROOT
    assert sc.nodes[CHILD].materials == [MAT_A, MAT_B]


def test_world_chains_parents_and_negates_the_angles():
    sc = kashmir.parse(build(rotate=True))
    rot, pos = kashmir.world(sc, CHILD)
    assert np.allclose(pos, (10, 2, 0))
    # yaw of pi/2 read as Ry(-pi/2): +x goes to +z
    assert np.allclose(rot @ np.array([1.0, 0, 0]), (0, 0, 1), atol=1e-6)


def test_plugin_places_the_mesh_and_binds_the_texture():
    scenes = plugin.extract(build(), "Data/Cars/x.dat", None)
    assert len(scenes) == 1
    sc = scenes[0]
    assert len(sc.primitives) == 2 and sc.extras["placed"] == 1
    textured = [p for p in sc.primitives if sc.materials[p.material].texture]
    assert len(textured) == 1 and "skin.tga" in sc.textures
    assert np.allclose(textured[0].positions.min(0), (10, 2, 0))


def test_standalone_gc_pictures_are_textures():
    data = build_gc_texture()
    assert plugin.detect("Data/Cars/S1.tga", data[:64], len(data))
    scenes = plugin.extract(data, "Data/Cars/S1.tga", None)
    assert len(scenes) == 1 and scenes[0].extras["textures_only"]
    assert scenes[0].textures["S1"].shape == (8, 8, 4)
