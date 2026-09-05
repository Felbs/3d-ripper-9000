"""EA GCsk characters - the scbm mesh members behind the Cact actors of the LotR .scg."""

import struct

import numpy as np

from gcrip.formats import ea_cact
from gcrip.plugins import ea_cact as plugin

GCSK_BASE = 0x2A0  # where the GCsk tag lands in a real scbm, kept for offset realism


def build(declared=2, strip=(0, 1, 2, 3), bone_b=0xFF):
    """A minimal scbm: OBG 01 05, the HEAD that overflows its declared size by 16 bytes,
    an ELHE, and one ELDA holding a GCsk with one mesh, one material, one strip."""
    verts = b""
    for x, y, z in [(0, 0, 0), (1024, 0, 0), (0, 1024, 0), (1024, 1024, 0)]:
        verts += struct.pack(">3h4B", x, y, z, 128, 3, bone_b, 0xBB)
    normals = struct.pack(">12b", *([0, 0, 64] * 4))
    uvs = struct.pack(">8h", 0, 0, 1024, 0, 0, 1024, 1024, 1024)
    skin = struct.pack(">f2B2HH", 1.0, 3, bone_b, 0, 4, 0)
    dl = bytes([0x9D]) + struct.pack(">H", len(strip))
    for i in strip:
        dl += struct.pack(">3H", i, i, i)
    dl += bytes((-len(dl)) % 32)

    mesh = bytearray(0x84 + 0x40)
    mesh[:2] = b"01"
    arrays = b""
    at = GCSK_BASE + len(mesh)  # data follows the mesh header, GCsk-relative
    for slot, count, elem, blob in [
        (0, 4, 10, verts),
        (1, 4, 3, normals),
        (2, 4, 4, uvs),
        (4, 1, 12, skin),
    ]:
        struct.pack_into(">3I", mesh, 0x10 + 12 * slot, count, at, elem)
        arrays += blob
        at += len(blob)
    struct.pack_into(">2I", mesh, 0x70, 0xFFFFFFFF, 1)  # material count
    struct.pack_into(">3I", mesh, 0x84, declared, at, len(dl))
    mesh[0x84 + 0x14 : 0x84 + 0x1B] = b"froface"

    gcsk = bytearray(GCSK_BASE)
    body = bytes(mesh) + arrays + dl
    gcsk[:4] = b"GCsk"
    struct.pack_into(">2I", gcsk, 4, 9, GCSK_BASE + len(body))
    gcsk[12:21] = b"TEST.g3d\0"
    struct.pack_into(">2I", gcsk, 24, 1, GCSK_BASE)
    gcsk = bytes(gcsk) + body

    def chunk(tag, payload):
        return tag + struct.pack(">I", len(payload)) + payload

    head = chunk(b"HEAD", bytes(0x70)) + bytes(16)  # the 16-byte overflow, as on disc
    elhe = chunk(b"ELHE", bytes(0xF8))
    elda = chunk(b"ELDA", struct.pack(">2I", 4, 0) + gcsk)
    return b"OBG \x01\x05\x00\x00" + head + elhe + elda


def test_the_head_overflow_does_not_hide_the_model():
    """HEAD declares 0x70 bytes but occupies 0x80, so a sized-chunk walk desynchronises;
    the reader must still find the GCsk."""
    got = ea_cact.model(build())
    assert got is not None and got.name == "TEST.g3d" and len(got.meshes) == 1


def test_positions_scale_by_1024_and_carry_bone_bytes():
    mesh = ea_cact.model(build()).meshes[0]
    assert mesh.positions.tolist()[1] == [1.0, 0.0, 0.0]
    assert mesh.weights.tolist() == [1.0] * 4
    assert mesh.bones.tolist() == [[3, 0xFF]] * 4


def test_normals_come_out_unit():
    mesh = ea_cact.model(build()).meshes[0]
    assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0)


def test_skin_groups_run_length_encode_the_assignment():
    mesh = ea_cact.model(build(bone_b=5)).meshes[0]
    (g,) = mesh.groups
    assert (g.weight, g.bone_a, g.bone_b, g.start, g.count) == (1.0, 3, 5, 0, 4)


def test_strips_alternate_winding_and_drop_degenerates():
    corners = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2], [2, 2, 2], [3, 3, 3]], np.uint16)
    assert ea_cact.strip_indices(corners).tolist() == [[0, 1, 2]]
    square = np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]], np.uint16)
    assert ea_cact.strip_indices(square).tolist() == [[0, 1, 2], [2, 1, 3]]


def test_the_triangle_count_identity_holds_and_catches_a_lie():
    held, detail = ea_cact.IDENTITIES[0].check(build(declared=2))
    assert held, detail
    held, _ = ea_cact.IDENTITIES[0].check(build(declared=3))
    assert held is False


def test_the_actor_lists_its_members():
    data = (
        b"tACT"
        + struct.pack(">2I", 0x20, 5)
        + bytes(0x14)
        + b"aRSL"
        + struct.pack(">2I", 8 + 4 + 16, 5)
        + b"scbm"
        + struct.pack(">I", 35001)
        + b"txfs"
        + struct.pack(">I", 35001)
    )
    got = ea_cact.actor(data)
    assert got.index == 5
    assert got.resources == [("scbm", 35001), ("txfs", 35001)]


class _Src:
    by_path: dict = {}

    def get(self, p):
        raise KeyError(p)


def test_the_plugin_builds_a_scene_with_per_corner_attributes():
    data = build()
    assert plugin.detect("scbm_35001", data[:64], len(data))
    (scene,) = plugin.extract(data, "x.scg/scbm_35001", _Src())
    (prim,) = scene.primitives
    assert scene.materials[prim.material].name == "froface"
    assert prim.indices.tolist() == [0, 1, 2, 2, 1, 3]
    assert prim.normals is not None and prim.uvs is not None
    assert prim.uvs.tolist()[3] == [1.0, 1.0]
    assert scene.extras["skinned"] and scene.extras["bones"] == 1


def test_terrain_obg_is_not_claimed():
    assert not plugin.detect("ter_1", b"OBG \x01\x04\x00\x00" + bytes(56), 64)


STEPS = ((0, 0, 0), (0, 0.4, 0), (0, 0.3, 0), (0.2, 0, 0))


def build_rig(parents=(-1, 0, 1, 2), steps=STEPS, kind=None):
    """A minimal rcb: the pointer-serialized header, the render-skeleton block at 0x64 -
    joint count, then (parent, flag) pairs and the 4x4 inverse-bind matrices (row-vector
    convention).  Joints are pure translation chains, so the inverse's last row is the
    negated bind position."""
    world = []
    for p, t in zip(parents, steps, strict=True):
        base = world[p] if 0 <= p < len(world) else np.zeros(3)
        world.append(base + np.asarray(t))
    p_pair = 0x80
    p_mat = p_pair + 8 * len(parents)
    out = bytearray(p_mat + 64 * len(parents))
    struct.pack_into(">2I", out, 0, len(out), ea_cact.RCB_KIND if kind is None else kind)
    struct.pack_into(">I", out, ea_cact.SKELETON_AT, len(parents))
    struct.pack_into(">5I", out, ea_cact.SKELETON_AT + 4, p_pair, p_mat, 0, 0, 0)
    for i, p in enumerate(parents):
        struct.pack_into(">iI", out, p_pair + 8 * i, p, 1)
        m = np.eye(4)
        m[3, :3] = -world[i]  # inverse of a pure translation, translation in the last row
        struct.pack_into(">16f", out, p_mat + 64 * i, *m.ravel())
    return bytes(out), world


def test_the_rig_reads_parents_and_rest_pose():
    data, world = build_rig()
    rig = ea_cact.rig(data)
    assert [j.parent for j in rig.joints] == [-1, 0, 1, 2]
    for j, t in zip(rig.joints, STEPS, strict=True):
        assert np.allclose(j.translation, t) and np.allclose(j.rotation, (0, 0, 0, 1))
        assert np.allclose(j.scale, 1)
    assert np.allclose([j.world for j in rig.joints], world)


def test_a_rig_with_a_forward_parent_is_refused():
    data, _ = build_rig(parents=(-1, 2, 1, 0))  # joint 1's parent comes after it
    assert ea_cact.rig(data) is None
    data, _ = build_rig(kind=0x15)
    assert ea_cact.rig(data) is None


class _RigSrc:
    def __init__(self, rig_blob):
        self.by_path = {"x.scg/scbm_35001": b"", "x.scg/rcb_35001": rig_blob}

    def get(self, p):
        return self.by_path[p]


def test_the_plugin_attaches_a_rig_that_lands_inside_the_mesh():
    rig_blob, _ = build_rig()
    (scene,) = plugin.extract(build(), "x.scg/scbm_35001", _RigSrc(rig_blob))
    assert scene.extras["rigged"] and len(scene.joints) == 4
    (prim,) = scene.primitives
    assert prim.joints is not None and prim.joints[:, 0].tolist() == [3, 3, 3, 3]
    assert np.allclose(prim.weights.sum(axis=1), 1.0)
    assert np.allclose(prim.weights[:, 0], 1.0)  # bone B is 0xff - bone A alone


def test_a_rig_outside_the_mesh_is_dropped_not_the_render():
    """The baked mesh renders correctly with no rig, so a wrong skeleton must never
    regress it: joints outside the padded bounding box leave the scene unrigged."""
    rig_blob, _ = build_rig(steps=((0, 0, 0), (0, 40, 0), (0, 3, 0), (2, 0, 0)))
    (scene,) = plugin.extract(build(), "x.scg/scbm_35001", _RigSrc(rig_blob))
    assert scene.extras["rigged"] is False and scene.joints == []
    assert scene.primitives and scene.primitives[0].joints is None


def test_a_rig_short_of_the_bone_bytes_is_dropped():
    rig_blob, _ = build_rig(parents=(-1, 0), steps=((0, 0, 0), (0, 0.4, 0)))
    (scene,) = plugin.extract(build(), "x.scg/scbm_35001", _RigSrc(rig_blob))
    assert scene.extras["rigged"] is False  # the mesh binds bone 3; the rig has 2 joints
