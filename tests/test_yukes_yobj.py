"""Yuke's YOBJ meshes - the .ymg files of the WWE discs."""

import struct

import numpy as np

from gcrip.formats import yukes_yobj
from gcrip.plugins import yukes_yobj as plugin

QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
# distinct unit vectors: identical ones stay unit under a shifted read, so they cannot
# show that the +8 convention matters
VARIED = [(0.6, 0.8, 0.0), (0.8, 0.0, 0.6), (0.0, 0.6, 0.8), (0.28, 0.96, 0.0)]
MARKER_AT = 32
POS_BLOCK = 64


def build(
    positions=QUAD,
    normal=(0.0, 0.0, 1.0),
    strip=(0, 1, 2, 3),
    count=None,
    skip=yukes_yobj.BLOCK_SKIP,
    gap=0,
    normals=None,
):
    """A YOBJ with one record.  `skip` is where the arrays sit relative to their offset -
    the format's own answer is 8, and the tests use it to show what other values do."""
    n = len(positions)
    pos_at = POS_BLOCK
    nrm_at = pos_at + (count if count is not None else n) * yukes_yobj.STRIDE + gap
    idx_at = nrm_at + n * yukes_yobj.STRIDE
    strips_at = idx_at + yukes_yobj.INDEX_SKIP
    end = strips_at + 4 + len(strip) * 2
    data = bytearray(end + 16)
    data[0:4] = yukes_yobj.MAGIC
    struct.pack_into(">I", data, 12, MARKER_AT - 8)
    struct.pack_into(">H", data, MARKER_AT + yukes_yobj.COUNT_AT, count if count is not None else n)
    struct.pack_into(">I", data, MARKER_AT, yukes_yobj.MARKER)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.POS_AT, pos_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.NRM_AT, nrm_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.IDX_AT, idx_at)
    for i, p in enumerate(positions):
        struct.pack_into(">3f", data, pos_at + skip + i * yukes_yobj.STRIDE, *p)
    for i in range(n):
        one = normals[i] if normals else normal
        struct.pack_into(">3f", data, nrm_at + skip + i * yukes_yobj.STRIDE, *one)
    struct.pack_into(">I", data, strips_at, len(strip))
    for i, v in enumerate(strip):
        struct.pack_into(">H", data, strips_at + 4 + i * 2, v)
    return bytes(data)


def test_detection_is_the_magic():
    data = build()
    assert yukes_yobj.is_yobj(data[:64])
    assert plugin.detect("0_2.ymg", data[:64], len(data))
    assert not plugin.detect("0_2.ymg", b"DUMY" + bytes(60), 64)


def test_a_mesh_round_trips():
    (mesh,) = yukes_yobj.meshes(build())
    assert len(mesh.positions) == 4 and len(mesh.indices) == 6
    assert np.allclose(mesh.positions[3], (1.0, 1.0, 0.0))
    assert mesh.unsigned_agreement > 0.99


def test_every_offset_points_eight_bytes_before_its_data():
    """Read the arrays at the offset itself and the normals come out non-unit - which reads
    like an off-by-one in the count rather than a block header, and is how the layout was
    first misread."""
    assert yukes_yobj.meshes(build(skip=0, normals=VARIED)) == []
    assert yukes_yobj.meshes(build(skip=yukes_yobj.BLOCK_SKIP, normals=VARIED)) != []


def test_the_normal_array_must_start_exactly_one_position_array_later():
    """`normals - positions == count * 12` is what ties the record's count to its data."""
    assert yukes_yobj.meshes(build(gap=4)) == []


def test_normals_that_are_not_unit_length_are_refused():
    assert yukes_yobj.meshes(build(normal=(0.0, 0.0, 0.5))) == []


def test_an_index_outside_the_vertex_count_ends_the_strip():
    assert yukes_yobj.meshes(build(strip=(0, 1, 2, 9))) == []


def test_triangles_are_flipped_to_agree_with_their_own_normals():
    """Winding is inconsistent here as it is in Terminal Reality's _smf and A2M's .gc."""
    (mesh,) = yukes_yobj.meshes(build(normal=(0.0, 0.0, -1.0)))
    tri = mesh.indices.reshape(-1, 3).astype(np.int64)
    a, b, c = mesh.positions[tri[:, 0]], mesh.positions[tri[:, 1]], mesh.positions[tri[:, 2]]
    face = np.cross(b - a, c - a)
    face /= np.linalg.norm(face, axis=1)[:, None]
    assert (face @ np.array([0.0, 0.0, -1.0]) > 0.99).all()


def test_the_plugin_builds_one_primitive_a_mesh():
    (scene,) = plugin.extract(build(), "files/bg/0_2.ymg", None)
    assert len(scene.primitives) == 1 and scene.triangles == 2
    assert scene.primitives[0].normals is not None


def test_a_file_that_is_not_yobj_yields_nothing():
    assert yukes_yobj.meshes(b"DUMY" + bytes(256)) == []
    assert plugin.extract(b"DUMY" + bytes(256), "x/point.ymg", None) == []


def build_xix(groups=((0, 1, 2, 3),), single=True):
    """WrestleMania XIX's block: an 8-byte entry a group (u8, u8, u16 strips, u32 ptr), the
    strips 8 bytes past the pointer as `u32 corners` + 10-byte corners.  A one-group table is
    the entry pointing at itself; more groups point past the table."""
    n = 4
    pos_at = POS_BLOCK
    nrm_at = pos_at + n * yukes_yobj.STRIDE
    idx_at = nrm_at + n * yukes_yobj.STRIDE
    t = idx_at + yukes_yobj.BLOCK_SKIP
    table = bytearray()
    bodies = bytearray()
    body_at = t + 8 * len(groups)
    for g, strip in enumerate(groups):
        ptr = t if single and len(groups) == 1 else body_at + len(bodies)
        table += struct.pack(">BBHI", g, 0, 1, ptr)
        if not (single and len(groups) == 1):
            bodies += bytes(8)  # the 8 bytes the pointer sits before
        bodies += struct.pack(">I", len(strip))
        for v in strip:
            bodies += struct.pack(">H4Bhh", v, 10 * v, 20, 30, 255, v * 8192, 16384)
    data = bytearray(t + len(table) + len(bodies) + 16)
    data[0:4] = yukes_yobj.MAGIC
    struct.pack_into(">H", data, MARKER_AT + yukes_yobj.COUNT_AT, n)
    struct.pack_into(">I", data, MARKER_AT, yukes_yobj.MARKER)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.POS_AT, pos_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.NRM_AT, nrm_at)
    struct.pack_into(">I", data, MARKER_AT + yukes_yobj.IDX_AT, idx_at)
    for i, p in enumerate(QUAD):
        struct.pack_into(">3f", data, pos_at + 8 + i * 12, *p)
        struct.pack_into(">3f", data, nrm_at + 8 + i * 12, 0.0, 0.0, 1.0)
    data[t : t + len(table)] = table
    data[body_at : body_at + len(bodies)] = bodies
    return bytes(data)


def test_wrestlemania_xix_groups_carry_uvs_and_colours():
    (m,) = yukes_yobj.meshes(build_xix())
    assert len(m.indices) == 6 and m.uvs is not None and m.colors is not None
    assert np.allclose(m.uvs[2], [0.5, 0.5]) and m.colors[3].tolist() == [30, 20, 30, 255]
    assert m.groups == [0, 0]
    (m,) = yukes_yobj.meshes(build_xix(((0, 1, 2), (1, 3, 2)), single=False))
    assert len(m.indices) == 6 and sorted(set(m.groups)) == [0, 1]
    (scene,) = plugin.extract(build_xix(), "0_2.ymg", None)
    assert scene.extras["variant"] == "xix" and scene.primitives[0].uvs is not None
    # X8's block still reads as before, without uvs
    (scene,) = plugin.extract(build(), "dummy_x8.ymg", None)
    assert scene.extras["variant"] == "x8" and scene.primitives[0].uvs is None


# -- Day of Reckoning (version 4) -------------------------------------------------------------

DOR_NAMES = ("g_skin", "face", "hair_00")


def _tpl_rgba8_4x4(rgba=(10, 20, 30, 255)) -> bytes:
    """A one-image TPL: 4x4 RGBA8, every texel `rgba` (AR pairs then GB pairs per tile)."""
    r, g, b, a = rgba
    tile = bytes([a, r] * 16) + bytes([g, b] * 16)
    head = struct.pack(">3I", 0x0020AF30, 1, 12)
    table = struct.pack(">2I", 20, 0)
    image = struct.pack(">HHIIIIIIfBBBB", 4, 4, 6, 64, 0, 0, 1, 1, 0.0, 0, 0, 0, 0)
    return (head + table + image).ljust(64, b"\0") + tile


def build_dor(strips=((0, 1, 2, 3),), materials=(1, 0), dumy=True, normal=(-1, 0, 0)):
    """A version-4 YOBJ: one mesh of QUAD, one group a strip, each group on `materials[i]`.
    Material 0 stacks g_skin under face, material 1 is hair_00 alone.  `normal` is stored,
    i.e. (nz, nx, ny) - the default is a geometric -z, which the file winding produces."""
    out = bytearray(0x48)
    struct.pack_into(">HHI", out, 8, yukes_yobj.VERSION_DOR, 1, 0x40)
    mesh = bytearray(yukes_yobj.MESH_RECORD)
    out += mesh  # patched below
    skip = yukes_yobj.BLOCK_SKIP

    def block(payload: bytes) -> int:
        """Append `payload` behind an 8-byte header; returns the pointer that names it."""
        at = len(out)
        out.extend(bytes(skip) + payload)
        return at

    verts = b"".join(
        struct.pack(">6h", int(x * 64), int(y * 64), int(z * 64), *(int(c * 4096) for c in normal))
        for x, y, z in QUAD
    )
    data_ptr = block(verts)
    strip_ptrs = []
    for strip in strips:
        body = struct.pack(">I", len(strip)) + b"".join(
            struct.pack(">Hhh", v, v * 256, 1024 - v * 256) for v in strip
        )
        strip_ptrs.append(block(body))
    rows = b"".join(
        struct.pack(">BBHI", materials[i], 1, 1, ptr) for i, ptr in enumerate(strip_ptrs)
    )
    groups_ptr = block(rows)
    struct.pack_into(">HHBBBB", mesh, 0, len(QUAD), 0, 3, 0, len(strips), 0)
    struct.pack_into(">IIIII", mesh, 8, yukes_yobj.MARKER, data_ptr, 0, 0, groups_ptr)
    struct.pack_into(">4f", mesh, 28, 0.5, 0.5, 0.0, 0.8)
    out[0x48 : 0x48 + len(mesh)] = mesh
    # bones
    bones = b"".join(
        struct.pack(">16si3f3ff", name, parent, *t, 0.0, 0.0, 0.0, 1.0).ljust(64, b"\0")
        for name, parent, t in ((b"null", -1, (0, 0, 0)), (b"Bip", 0, (0.0, -100.0, 0.0)))
    )
    bones_ptr = block(bones)
    # names
    names_ptr = block(b"".join(n.encode().ljust(16, b"\0") for n in DOR_NAMES))

    # materials: stage lists first, then the 20-byte records that point at them
    def stages(*tex):
        body = struct.pack(">HH", len(tex), 0) + bytes([0xE4] * 4) + bytes([0xFF] * 16)
        body += struct.pack(">II", 0, 0)
        for t in tex:
            body += bytes(19) + bytes([t])
        return block(body)

    s0 = stages(0, 1)
    s1 = stages(2)
    records = b"".join(
        bytes([0xB2, 0xB2, 0xB2, 0xFF]) * 3 + struct.pack(">HHI", 0, 0, ptr) for ptr in (s0, s1)
    )
    materials_ptr = block(records)
    struct.pack_into(">2I", out, 0x10, 2, bones_ptr)
    struct.pack_into(">2I", out, 0x18, 2, materials_ptr)
    struct.pack_into(">2I", out, 0x20, len(DOR_NAMES), names_ptr)
    out[0:4] = yukes_yobj.MAGIC
    struct.pack_into(">I", out, 4, len(out))
    if dumy:
        out = bytearray(b"DUMY" + struct.pack(">I", 16) + bytes(16)) + out
    return bytes(out)


def test_day_of_reckoning_is_version_4_behind_a_dumy_stamp():
    data = build_dor()
    assert data[:4] == b"DUMY" and yukes_yobj.yobj_at(data) == 24
    assert yukes_yobj.version(data) == 4 and yukes_yobj.is_dor(data)
    assert yukes_yobj.is_yobj(data[:64]) and plugin.detect("000_0.ymg", data[:64], len(data))
    assert yukes_yobj.version(build_dor(dumy=False)) == 4
    assert not yukes_yobj.is_dor(build_xix()) and yukes_yobj.dor_model(build_xix()) is None
    assert yukes_yobj.version(build_xix()) == 0  # X8 / XIX builders leave +8 zero


def test_day_of_reckoning_groups_read_by_material():
    m = yukes_yobj.dor_model(build_dor(strips=((0, 1, 2, 3), (1, 3, 2))))
    assert m is not None and m.warnings == [] and m.meshes == 1
    assert [b.name for b in m.bones] == ["null", "Bip"] and m.bones[1].parent == 0
    assert m.bones[1].translation == (0.0, -100.0, 0.0)
    assert m.names == list(DOR_NAMES)
    assert [mat.textures for mat in m.materials] == [["g_skin", "face"], ["hair_00"]]
    assert m.materials[0].diffuse == (0xB2, 0xB2, 0xB2, 0xFF)
    assert [g.material for g in m.groups] == [1, 0]
    quad, tri = m.groups
    assert len(quad.indices) == 6 and len(tri.indices) == 3
    assert np.allclose(quad.positions[quad.indices[:3]].sum(0), [1.0, 1.0, 0.0], atol=1e-6)
    # the stored (nz, nx, ny) comes back as a geometric normal, and agrees with the winding
    assert np.allclose(quad.normals, [[0.0, 0.0, -1.0]] * 4)
    assert quad.agreement > 0.99 and tri.agreement > 0.99
    # corner uvs / 1024, unique per (index, u, v)
    v = quad.positions[:, 0] + 2 * quad.positions[:, 1]  # 0, 1, 2, 3 by QUAD order
    order = np.argsort(v)
    assert np.allclose(quad.uvs[order], [[0.0, 1.0], [0.25, 0.75], [0.5, 0.5], [0.75, 0.25]])


def test_day_of_reckoning_declines_bad_groups():
    data = bytearray(build_dor())
    # a strip index past the vertex count: that group is dropped with a warning
    at = data.find(struct.pack(">IHhh", 4, 0, 0, 1024)) + 4
    struct.pack_into(">H", data, at, 9)
    m = yukes_yobj.dor_model(bytes(data))
    assert m is not None and m.groups == [] and m.warnings == ["mesh 0: group 0 does not read"]
    assert plugin.extract(bytes(data), "x.ymg", None) == []


class _Src:
    def __init__(self, files):
        self.by_path = files

    def get(self, path):
        return self.by_path[path]


def test_day_of_reckoning_plugin_textures_from_the_sibling_tex_pack():
    data = build_dor(strips=((0, 1, 2, 3), (1, 3, 2)))
    src = _Src(
        {
            "files/model/wrestler/000_0.tex/face.tpl": _tpl_rgba8_4x4((10, 20, 30, 255)),
            "files/model/wrestler/000_0.tex/g_skin.tpl": _tpl_rgba8_4x4((1, 1, 1, 255)),
            "files/model/wrestler/017_1.tex/hair_00.tpl": _tpl_rgba8_4x4((90, 80, 70, 255)),
        }
    )
    (scene,) = plugin.extract(data, "files/model/wrestler/000_0.ymg", src)
    assert scene.extras["variant"] == "dor" and scene.triangles == 3
    assert len(scene.primitives) == 2 and len(scene.materials) == 2
    # the picture is the stage without a g_/m_/n_ prefix; hair_00 comes from another pack
    assert [m.name for m in scene.materials] == ["hair_00", "face"]
    assert [m.texture for m in scene.materials] == ["hair_00", "face"]
    assert scene.textures["face"][0, 0].tolist() == [10, 20, 30, 255]
    assert scene.textures["hair_00"].shape == (4, 4, 4)
    assert scene.materials[1].base_color == (1.0, 1.0, 1.0, 1.0)
    # stood upright: the quad's -z normal becomes +z, y is negated
    assert np.allclose(scene.primitives[0].normals[0], [0.0, 0.0, 1.0])
    assert scene.extras["stages"]["material_00"] == ["g_skin", "face"]
    assert scene.extras["bones"] == ["null", "Bip"]
    # without a pack the material keeps the file's diffuse and no texture
    (bare,) = plugin.extract(data, "000_0.ymg", None)
    assert bare.materials[0].texture is None
    assert np.allclose(bare.materials[0].base_color, (0xB2 / 255,) * 3 + (1.0,))


def test_wrestlemania_xix_meshes_split_by_material_and_bind_the_tex_pack(monkeypatch):
    data = build_xix(((0, 1, 2), (1, 3, 2)), single=False)
    (mesh,) = yukes_yobj.meshes(data)
    assert mesh.groups == [0, 1]
    # the sample builder has no material tables; stand in for them
    monkeypatch.setattr(
        yukes_yobj,
        "materials",
        lambda _d: (
            [
                yukes_yobj.DorMaterial((0x96, 0x96, 0x96, 0xFF), ["tekin_01"]),
                yukes_yobj.DorMaterial((0x95, 0x95, 0x95, 0xFF), ["g_skin", "yuka_01"]),
            ],
            ["tekin_01", "g_skin", "yuka_01"],
        ),
    )
    src = _Src({"files/bg/0_2.tex/yuka_01.tpl": _tpl_rgba8_4x4((5, 6, 7, 255))})
    (scene,) = plugin.extract(data, "files/bg/0_2.ymg", src)
    assert scene.extras["variant"] == "xix" and scene.extras["textures"] == 1
    assert len(scene.primitives) == 2 and scene.triangles == 2
    assert [m.name for m in scene.materials] == ["tekin_01", "yuka_01"]
    assert [m.texture for m in scene.materials] == [None, "yuka_01"]
    assert np.allclose(scene.materials[0].base_color, (0x96 / 255,) * 3 + (1.0,))
    # each primitive re-indexes only the vertices it touches, keeping their uvs and colours
    second = scene.primitives[1]
    assert len(second.positions) == 3 and second.indices.tolist() == [0, 2, 1]
    assert second.uvs is not None and second.colors is not None
