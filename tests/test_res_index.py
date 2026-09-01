"""The `indx` section of a `res` file - a name directory for the other sections."""

import struct

from gcrip.formats import res


def build(name=b"menus/train_game/bobblehead_texture.tif", tag=b"surf", bad_tag=False):
    """A res file holding one `surf`, one `strg` and one `indx` that names the surf.

    Both offsets in an index entry are **self-relative** - measured from the field's own
    position, the same convention `rdms` uses for its array offsets.
    """
    data_off = 0x1000
    strings = name + b"\0"
    surf = b"TEXTUREBYTES!"
    index = bytearray(res.INDEX_HEADER + res.INDEX_ENTRY)
    # indx before strg, as the real files have it, so the name offset runs forward
    payloads = [(b"surf", 4, surf), (b"indx", 44, bytes(index)), (b"strg", 28, bytes(strings))]
    body = bytearray()
    entries = []
    for t, ident, blob in payloads:
        entries.append((ident, t, len(body), len(blob)))
        body += blob
    dir_off = data_off + 0x1000
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, t, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, t, off, size, 0)
    blob = bytearray(bytes(out) + bytes(dirbuf))

    surf_at = data_off + entries[0][2]
    indx_at = data_off + entries[1][2]
    strg_at = data_off + entries[2][2]
    field = indx_at + res.INDEX_HEADER
    struct.pack_into(">I", blob, indx_at, 1)
    struct.pack_into(">I", blob, indx_at + 4, 4)
    struct.pack_into(">I", blob, field, strg_at - field)  # name offset, self-relative
    struct.pack_into(">4s", blob, field + 4, b"node" if bad_tag else tag)
    struct.pack_into(">i", blob, field + 8, surf_at - (field + 8))  # section delta
    return bytes(blob)


def test_the_index_names_a_section():
    (entry,) = res.index_entries(build())
    assert entry.tag == "surf"
    assert entry.name == "menus/train_game/bobblehead_texture.tif"
    secs = {s.offset: s.tag for s in res.sections(build())}
    assert secs[entry.offset] == "surf"


def test_both_offsets_are_self_relative():
    """Measured from the `indx` section's start instead, none of Lemony Snicket's six names
    lands on a string - which is what identified the convention."""
    data = build()
    (entry,) = res.index_entries(data)
    index = next(s for s in res.sections(data) if s.tag == "indx")
    field = index.offset + res.INDEX_HEADER
    (stored,) = struct.unpack_from(">I", data, field)
    assert field + stored != index.offset + stored  # the two bases genuinely differ
    assert entry.name.endswith(".tif")


def test_an_entry_whose_tag_disagrees_with_its_target_is_dropped():
    """The two self-relative offsets are the check: a misread entry drops out rather than
    naming the wrong section."""
    assert res.index_entries(build(bad_tag=True)) == []


def test_a_file_without_an_index_is_not_an_error():
    from tests.test_res import build as plain

    assert res.index_entries(plain()) == []


def test_expand_uses_the_name_where_there_is_one():
    members = dict(res.expand(build()))
    assert any(n.startswith("000_surf_bobblehead_texture") for n in members)
    # the tag infix survives, because the plugin screens members on it
    assert all("_surf_" in n or "_strg_" in n or "_indx_" in n for n in members)


def build_scene():
    """A res file with one `node` that points at two `rdms` sections.

    The reference is the format's usual self-relative offset: the word's value plus its own
    position lands on the section.
    """
    data_off = 0x1000
    node = bytearray(160)
    payloads = [(b"rdms", 4, b"MESH-ONE"), (b"rdms", 8, b"MESH-TWO"), (b"node", 12, bytes(node))]
    body = bytearray()
    entries = []
    for t, ident, blob in payloads:
        entries.append((ident, t, len(body), len(blob)))
        body += blob
    dir_off = data_off + 0x1000
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, t, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, t, off, size, 0)
    blob = bytearray(bytes(out) + bytes(dirbuf))
    one = data_off + entries[0][2]
    two = data_off + entries[1][2]
    node_at = data_off + entries[2][2]
    for slot, target in ((48, one), (100, two)):     # 52 bytes apart, as the real records are
        at = node_at + slot
        struct.pack_into(">i", blob, at, target - at)
    return bytes(blob), node_at, one, two


def test_a_node_names_the_meshes_it_draws():
    data, node_at, one, two = build_scene()
    (link,) = res.node_links(data)
    assert link.offset == node_at
    assert link.meshes == [one, two]


def test_a_mesh_takes_its_node_s_name_in_expand():
    """Grouping is what the links buy: the parts of one object land together in the output."""
    data, node_at, one, two = build_scene()
    names = [n for n, _ in res.expand(data)]
    assert sum("_rdms_node" in n for n in names) == 2


def test_a_file_with_no_node_sections_yields_no_links():
    assert res.node_links(build()) == []


def test_an_rdms_scene_carries_a_real_material():
    """`material=-1` with no materials at all is what the thumbnail pass indexes into, and
    `[][-1]` is an IndexError that failed 62,640 meshes across the three discs - every mesh
    that had triangles to draw."""
    import numpy as np

    from gcrip.formats import res_rdms
    from gcrip.plugins import res as plugin

    class FakeMesh:
        positions = np.zeros((4, 3), np.float32)
        indices = np.array([0, 1, 2, 1, 3, 2], np.uint32)
        normals = None
        uvs = None

    original = res_rdms.mesh
    res_rdms.mesh = lambda data: FakeMesh()
    try:
        (scene,) = plugin.extract(b"x" * 64, "000_rdms_12.bin", None)
    finally:
        res_rdms.mesh = original
    assert scene.materials, "an rdms scene must declare a material"
    assert scene.primitives[0].material == 0
