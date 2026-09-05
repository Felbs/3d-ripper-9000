"""Runecraft ``.gcg`` (Mat Hoffman's Pro BMX 2): the reader, the plugin routing, and the
regression the plugin guards.

The GMHE52 finding: 4,730 ``gcg\\0`` files were claimed by nothing, so the ``gx`` fallback
scanned them - it found the f32 position arrays but paired them with the wrong index
words, and 472 of 533 exported models scored garbage/suspect (76-81% zero-length edges).
The reader here parses every one of the 401 cached park/rider/bike files byte-exact to EOF
(see docs/formats/runecraft-gcg.md); these tests pin the layout with synthetic files.
"""

import struct

import numpy as np

from gcrip.formats import gcg
from gcrip.plugins import gcg as plugin
from gcrip.plugins import plugins_for

FLT_MAX = 3.4028234663852886e38


def node(name, parent=-1, translation=(0.0, 0.0, 0.0), maxabs=(1.0, 1.0, 1.0)):
    rec = bytearray(gcg.NODE_SIZE)
    rec[: len(name)] = name.encode()
    m = np.eye(4, dtype=">f4")
    m[3, :3] = translation
    rec[0x80:0xC0] = m.tobytes()
    struct.pack_into(">7f", rec, 0xC0, 0.0, 0.0, 0.0, *maxabs, 1.0)
    struct.pack_into(">i", rec, 0xDC, parent)
    return bytes(rec)


def display_list(op, rows, skinned=False):
    """One primitive: *rows* is a list of index tuples (one u16 per attribute), with an
    optional (node slot) prefix byte when skinned."""
    body = bytearray([op, 0, len(rows)])
    struct.pack_into(">H", body, 1, len(rows))
    for r in rows:
        if skinned:
            body.append(r[0] * 3)
            r = r[1:]
        body += struct.pack(f">{len(r)}H", *r)
    while len(body) % 32:
        body.append(0)
    return bytes(body)


def submesh(
    material,
    positions,
    *,
    s16_frac=None,
    normals=None,
    colors=None,
    uvs=None,
    uv_u8=False,
    dl=b"",
    skinned=False,
    explicit=True,
):
    mask = 1 | (2 if normals is not None else 0) | (4 if colors is not None else 0)
    mask |= 8 if uvs is not None else 0
    mask |= 0x40 if skinned else 0
    nv = len(positions)
    out = bytearray(struct.pack(">I", material))
    out += bytes([0x80 if explicit else 0x00, mask, 1, 0xFF, 0])
    out += struct.pack(">fH", 1.0, nv)
    if explicit:
        comp = 3 if s16_frac is not None else 4
        out += struct.pack(">IB", comp, s16_frac or 0)
        out += struct.pack(">IB", 1, 0)
        out += bytes([0, 0, 0 if uv_u8 else 3, 7 if uv_u8 else 9])
    if s16_frac is not None:
        out.append(6)
        out += np.asarray(positions, ">i2").tobytes()
    else:
        out.append(12)
        out += np.asarray(positions, ">f4").tobytes()
    if normals is not None:
        out.append(3)
        out += np.asarray(normals, np.int8).tobytes()
    if colors is not None:
        out.append(4)
        out += np.asarray(colors, np.uint8).tobytes()
    if uvs is not None:
        if uv_u8:
            out.append(2)
            out += np.asarray(uvs, np.uint8).tobytes()
        else:
            out.append(4)
            out += np.asarray(uvs, ">i2").tobytes()
    out += struct.pack(">III", 1, 1, len(dl)) + dl
    return bytes(out)


def build(nodes, materials, submeshes, order=None):
    out = bytearray(gcg.MAGIC + struct.pack(">II", 3, len(nodes)))
    out += b"".join(nodes)
    out += struct.pack(">I", len(materials))
    for m in materials:
        out += m.encode().ljust(64, b"\0")
    out += struct.pack(">IfI", 1, FLT_MAX, len(submeshes))
    out += b"".join(submeshes)
    if order is not None:
        padded = (len(order) + 3) & ~3
        out += struct.pack(">II", 1, len(order)) + bytes(order).ljust(padded, b"\0")
        out += struct.pack(">I", len(nodes))
    return bytes(out)


def quad_f32():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)]
    nrm = [(0, 64, 0)] * 4
    col = [(255, 0, 0, 255)] * 4
    uv = [(0, 0), (0x200, 0), (0, 0x200), (0x200, 0x200)]
    dl = display_list(0x98, [(0, 0, 0, 0), (1, 1, 1, 1), (2, 2, 2, 2), (3, 3, 3, 3)])
    return submesh(0, pos, normals=nrm, colors=col, uvs=uv, dl=dl)


# --- the reader --------------------------------------------------------------------------


def test_single_node_file_parses_byte_exact():
    data = build([node("PO_thing")], ["po_wood01"], [quad_f32()])
    m = gcg.parse(data)
    assert m.end == len(data)
    assert [n.name for n in m.nodes] == ["PO_thing"]
    assert m.materials == ["po_wood01"]
    (sub,) = m.submeshes
    assert sub.material == 0
    assert sub.positions.shape == (4, 3)
    assert np.allclose(sub.normals, [[0, 1, 0]] * 4)
    assert sub.colors.tolist() == [[255, 0, 0, 255]] * 4
    assert np.allclose(sub.uvs, [[0, 0], [1, 0], [0, 1], [1, 1]])  # s16 with 9 frac bits
    assert not sub.skinned
    tris = gcg.triangulate(sub.prims)
    assert len(tris) == 2  # a 4-vertex strip


def test_s16_positions_scale_by_two_to_the_frac():
    # po_vdeck12: frac 11, 27368 -> 13.363 == the node's maxabs.z
    pos = [(2493, 0, 27368), (-10196, 0, -25499), (-2496, 0, -27367), (10196, 0, 25500)]
    dl = display_list(0x98, [(0,), (1,), (2,), (3,)])
    data = build([node("PO_vdeck12")], ["po_pwood01"], [submesh(0, pos, s16_frac=11, dl=dl)])
    m = gcg.parse(data)
    assert m.end == len(data)
    assert np.isclose(m.submeshes[0].positions[0, 2], 27368 / 2048)


def test_attr_mask_without_uv_reads_three_index_columns():
    pos = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    dl = display_list(0x90, [(0, 0, 0), (1, 1, 1), (2, 2, 2)])
    sub = submesh(gcg.NO_MATERIAL, pos, normals=[(0, 0, 64)] * 3, colors=[(1, 2, 3, 4)] * 3, dl=dl)
    m = gcg.parse(build([node("PO_col57")], [""], [sub]))
    s = m.submeshes[0]
    assert s.uvs is None and s.material == gcg.NO_MATERIAL
    assert s.prims[0][1].shape == (3, 3)
    assert gcg.triangulate(s.prims).tolist() == [[0, 1, 2]]


def test_u8_uvs_use_seven_fraction_bits():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1)]
    dl = display_list(0x90, [(0, 0), (1, 1), (2, 2)])
    sub = submesh(0, pos, uvs=[(0, 12), (128, 48), (128, 35)], uv_u8=True, dl=dl)
    m = gcg.parse(build([node("n")], ["m"], [sub]))
    assert np.allclose(m.submeshes[0].uvs, [[0, 12 / 128], [1, 48 / 128], [1, 35 / 128]])


def test_implicit_vertex_format_is_all_f32():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1)]
    dl = display_list(0x90, [(0,), (1,), (2,)])
    data = build([node("po_vert02h")], ["m"], [submesh(0, pos, dl=dl, explicit=False)])
    m = gcg.parse(data)
    assert m.end == len(data)
    assert np.array_equal(m.submeshes[0].positions, np.array(pos, np.float32))


def test_display_list_is_padded_with_nops_and_stops_at_its_size():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)]
    dl = display_list(0x80, [(0,), (1,), (3,), (2,)])  # one quad, then 0x00 padding
    m = gcg.parse(build([node("n")], ["m"], [submesh(0, pos, dl=dl)]))
    assert gcg.triangulate(m.submeshes[0].prims).tolist() == [[0, 1, 3], [0, 3, 2]]


def test_index_past_the_vertex_count_is_refused():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1)]
    dl = display_list(0x90, [(0,), (1,), (7,)])
    data = build([node("n")], ["m"], [submesh(0, pos, dl=dl)])
    try:
        gcg.parse(data)
    except gcg.GcgError:
        return
    raise AssertionError("bad index accepted")


def test_multi_node_file_binds_vertices_to_nodes_and_reads_the_trailer():
    nodes = [node("Root"), node("Arm", parent=0, translation=(0.0, 2.0, 0.0))]
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1)]
    # LOAD_INDX_A node 1 into slot 0 (addr 0, size 0xB), then draw with PNMTXIDX 0
    loads = (
        bytes([0x20])
        + struct.pack(">HH", 1, 0xB000)
        + bytes([0x28])
        + struct.pack(">HH", 1, 0x8400)
    )
    dl = loads + display_list(0x90, [(0, 0), (0, 1), (0, 2)], skinned=True)
    data = build(nodes, ["m"], [submesh(0, pos, dl=dl, skinned=True)], order=[0, 1])
    m = gcg.parse(data)
    assert m.end == len(data)
    assert m.order == [0, 1]
    sub = m.submeshes[0]
    assert sub.skinned
    assert sub.binds[0].tolist() == [1, 1, 1]
    scene = plugin.build_scene(m, "files/GLOBAL/riders/x.gcg", None)
    prim = scene.primitives[0]
    assert np.allclose(prim.positions[:, 1], 2.0)  # baked through the Arm node's translation
    assert scene.extras["skinned"] is True


def test_world_matrices_compose_parent_chains():
    nodes = [node("a", translation=(1, 0, 0)), node("b", parent=0, translation=(0, 1, 0))]
    data = build(nodes, [], [], order=[0, 1])
    m = gcg.parse(data)
    w = gcg.world_matrices(m.nodes)
    assert np.allclose(w[1][3, :3], [1, 1, 0])


# --- textures and materials ---------------------------------------------------------------


def gct(paletted, w, h, levels, ncolors=256):
    out = struct.pack(">6I", 1, int(paletted), len(levels), ncolors if paletted else 0, w, h)
    if paletted:
        out += struct.pack(f">{ncolors}H", *([0xFFFF] * ncolors))  # opaque white (RGB5A3)
    for lw, lh, body in levels:
        out += struct.pack(">3I", lw, lh, len(body)) + body
    return out


def test_gct_base_level_is_the_last_and_largest_mip():
    small = bytes(gcg.gx_texture.encoded_size(9, 4, 4))
    base = bytes([0] * gcg.gx_texture.encoded_size(9, 8, 8))
    t = gcg.decode_gct(gct(True, 8, 8, [(4, 4, small), (8, 8, base)]))
    assert t.rgba.shape == (8, 8, 4)
    assert t.paletted and tuple(t.rgba[0, 0]) == (255, 255, 255, 255)


def test_gct_cmpr_without_palette():
    body = bytes(gcg.gx_texture.encoded_size(14, 8, 8))
    t = gcg.decode_gct(gct(False, 8, 8, [(8, 8, body)]))
    assert t.rgba.shape == (8, 8, 4) and not t.paletted


def test_gcm_material_names_its_texture():
    text = "[ShaderPass_1]\r\nShaderName = GCNVSDiffuse\r\nTextureMap_1        = bigfoot2\r\n"
    assert gcg.material_texture(text) == "bigfoot2"
    assert gcg.material_texture("[General]\r\n") is None


class FakeSrc:
    def __init__(self, files):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path):
        return self.files[path]


def test_plugin_binds_gcm_and_gct_from_the_textures_folder():
    data = build([node("poground21")], ["po_ground01"], [quad_f32()])
    body = bytes(gcg.gx_texture.encoded_size(14, 8, 8))
    gcm = b"[ShaderPass_1]\r\nTextureMap_1 = PO_dirt\r\n"
    src = FakeSrc(
        {
            "files/TRACKS/portland/geometry/poground21.gcg": data,
            "files/TRACKS/portland/textures/po_ground01.gcm": gcm,
            "files/TRACKS/portland/textures/po_dirt.gct": gct(False, 8, 8, [(8, 8, body)]),
        }
    )
    (scene,) = plugin.extract(data, "files/TRACKS/portland/geometry/poground21.gcg", src)
    assert scene.materials[0].texture == "po_dirt"
    assert scene.textures["po_dirt"].shape == (8, 8, 4)
    assert scene.primitives[0].material == 0
    assert scene.primitives[0].uvs.shape == (4, 2)


def test_plugin_drops_strip_stitch_triangles():
    pos = [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)]
    # strip 0 1 2 2 3 1 : the (1,2,2) and (2,2,3) triangles are stitches, two are real
    dl = display_list(0x98, [(0,), (1,), (2,), (2,), (3,), (1,)])
    m = gcg.parse(build([node("n")], ["m"], [submesh(0, pos, dl=dl)]))
    scene = plugin.build_scene(m, "x.gcg", None)
    assert len(scene.primitives[0].indices) == 3 * 2


# --- routing -------------------------------------------------------------------------------


def test_gcg_files_route_to_the_plugin_not_the_gx_fallback():
    data = build([node("poground21")], ["po_ground01"], [quad_f32()])
    names = [
        m.NAME
        for m in plugins_for("files/TRACKS/portland/geometry/poground21.gcg", data[:64], len(data))
    ]
    assert names == ["gcg"]


def test_detect_wants_the_magic_not_the_extension():
    assert not plugin.detect("files/x.gcg", b"\0" * 64, 4096)
    assert plugin.detect("files/x.bin", gcg.MAGIC + struct.pack(">II", 3, 1) + b"\0" * 52, 4096)
