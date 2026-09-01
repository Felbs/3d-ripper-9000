"""Warthog `.bmsh` meshes - the geometry members of a WART3.00 .hog archive."""

import struct

import numpy as np

from gcrip.formats import wart_bmsh
from gcrip.plugins import wart_bmsh as plugin


def header(extent=(4.0, 2.0, 1.0), centre=(0.0, 0.0, 0.0), radius=None, kind=10, at=72):
    """A resource header carrying a bounding volume at `at`."""
    radius = float(np.linalg.norm(extent)) if radius is None else radius
    head = bytearray(max(128, at + wart_bmsh.BOUND_BYTES))
    struct.pack_into(">I", head, wart_bmsh.KIND_AT, kind << 24)
    struct.pack_into(">7f", head, at, *extent, *centre, radius)
    return head


def quad(at=72):
    """A one-section-table mesh: a triangle strip of four corners with u8 indices.

    Sections are setup, display list, positions, texcoords - which is the layout every sample
    of the format uses.
    """
    corners = [(-4.0, -2.0, 1.0), (4.0, -2.0, 1.0), (-4.0, 2.0, -1.0), (4.0, 2.0, -1.0)]
    positions = b"".join(struct.pack(">3f", *c) for c in corners)
    uvs = b"".join(struct.pack(">2h", u, v) for u, v in ((0, 0), (16384, 0), (0, 16384), (16384, 16384)))
    dl = bytes([0x98]) + struct.pack(">H", 4) + bytes([0, 0, 1, 1, 2, 2, 3, 3])
    dl += bytes(-len(dl) % 4)
    setup = bytes(16)
    sections = [setup, dl, positions, uvs]
    head = header(extent=(4.0, 2.0, 1.0), centre=(0.0, 0.0, 0.0), at=at)
    table = struct.pack(">2I", len(sections), sum(len(s) for s in sections))
    table += b"".join(struct.pack(">I", len(s)) for s in sections)
    return bytes(head) + table + b"".join(sections)


def test_a_quad_parses_to_two_triangles():
    mesh = wart_bmsh.parse(quad())
    assert mesh is not None and len(mesh.parts) == 1
    part = mesh.parts[0]
    assert len(part.indices) == 2 and len(part.positions) == 4
    assert part.uvs is not None and part.uvs.max() == 1.0


def test_the_geometry_reproduces_the_header_bounding_volume():
    """The independent check: the decoded positions have to give back the centre and extent the
    header declares, and on real members exactly one header offset matches."""
    data = quad()
    mesh = wart_bmsh.parse(data)
    positions = np.concatenate([p.positions for p in mesh.parts])
    assert wart_bmsh.matching_bounds(data, positions) == [72]


def test_the_bounding_block_is_located_not_assumed():
    """Two of thirteen real meshes carry it at 92 rather than 72.  Reading a fixed 72 made them
    look misplaced by 740 units when the geometry was right."""
    data = quad(at=92)
    mesh = wart_bmsh.parse(data)
    positions = np.concatenate([p.positions for p in mesh.parts])
    assert wart_bmsh.matching_bounds(data, positions) == [92]


def test_a_radius_outside_the_extent_is_not_a_bounding_volume():
    """The signature that locates the block: the radius lies between the largest half-extent
    and the box diagonal."""
    assert wart_bmsh.bounds(bytes(header(radius=0.5)), 72) is None
    assert wart_bmsh.bounds(bytes(header(radius=1000.0)), 72) is None
    assert wart_bmsh.bounds(bytes(header()), 72) is not None


def test_the_table_chain_has_to_end_exactly_at_the_member_end():
    """What locates the tables without any offset to trust.  A member with a byte appended has
    no chain reaching the end, so it yields nothing rather than a partial mesh."""
    assert wart_bmsh.tables(quad())
    assert not wart_bmsh.tables(quad() + b"\0")


def test_a_table_whose_sizes_do_not_sum_to_its_total_is_rejected():
    data = bytearray(quad())
    # corrupt the first section size so sum(sizes) != total
    for off in range(96, len(data) - 8, 4):
        count, total = struct.unpack_from(">2I", data, off)
        if count == 4 and total:
            struct.pack_into(">I", data, off + 8, 8)
            break
    assert not wart_bmsh.tables(bytes(data))


def test_the_plugin_builds_a_scene_with_uvs():
    (scene,) = plugin.extract(quad(), "frontend.hog/models/cog.bmsh", None)
    assert scene.name == "cog" and scene.extras["triangles"] == 2
    assert len(scene.primitives) == 1 and scene.primitives[0].uvs is not None


def test_the_plugin_declines_other_resource_kinds():
    """.btga, .bskl and .banr share the resource header and are not meshes."""
    assert not plugin.detect("x.btga", bytes(header(kind=3))[:64], 4096)
    assert plugin.extract(bytes(header(kind=3)), "x.bmsh", None) == []
