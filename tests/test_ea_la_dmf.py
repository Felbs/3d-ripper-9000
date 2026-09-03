"""EA LA Frontline characters: .dmf cluster-skinned meshes posed over a .skl skeleton,
textured from a TPAC pack."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ea_la
from gcrip.plugins import ea_la as plugin
from tests.test_ea_la import shpg


def skl(joints: list[tuple[str, tuple[float, float, float], int]]) -> bytes:
    """Little-endian: u16 count at +6, name table pointer at +0xc, records at +0x20 of
    f32 xyz + i32 depth, then 20-byte name entries."""
    n = len(joints)
    names_at = 0x20 + 16 * n
    body = bytearray(names_at + 20 * n)
    body[:4] = ea_la.SKL_MAGIC
    struct.pack_into("<H", body, 6, n)
    struct.pack_into("<I", body, 0xC, names_at)
    for i, (name, (x, y, z), depth) in enumerate(joints):
        struct.pack_into("<3fi", body, 0x20 + 16 * i, x, y, z, depth)
        body[names_at + 20 * i + 4 : names_at + 20 * i + 20] = name.encode().ljust(16, b"\0")
    return bytes(body)


class Dmf:
    """One render object with one part: a quad strip on cluster 0, plus a second part on
    cluster 1 (the child bone, weight 1) to test the frame placement."""

    def __init__(self):
        self.body = bytearray(0x80)
        self.body[:4] = ea_la.DMF_MAGIC
        struct.pack_into(">I", self.body, 4, ea_la.DMF_VERSION)
        self.body[0xC:0x10] = b"Test"

    def put(self, blob: bytes, align: int = 32) -> int:
        while len(self.body) % align:
            self.body.append(0)
        at = len(self.body)
        self.body += blob
        return at

    def build(
        self, bones: list[str], rest: list[tuple[int, int, int]], clusters, textures, parts
    ) -> bytes:
        """parts: (texture index, cluster list, corners [(slot, pos, nrm, uv)])"""
        quad = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]) * 16384
        pos = self.put(quad.astype(">i2").tobytes())
        nrm = self.put(np.array([[0, 0, 32767]] * 4, ">i2").tobytes())
        uv = self.put((np.array([[0, 0], [1, 0], [0, 1], [1, 1]]) * 16384).astype(">i2").tobytes())
        cl = self.put(b"".join(struct.pack(">BBH", a, b, w) for a, b, w in clusters))
        names = self.put(b"".join(n.encode().ljust(16, b"\0") for n in bones))
        angles = self.put(b"".join(struct.pack(">3h", *r) for r in rest))
        tex = self.put(b"".join(t.encode().ljust(16, b"\0") for t in textures))
        recs = []
        for ti, part_clusters, corners in parts:
            dl = b"\x98" + struct.pack(">H", len(corners))
            dl += b"".join(struct.pack(">BHHH", *c) for c in corners)
            dl += bytes(-len(dl) % 32)
            at = self.put(dl)
            rec = struct.pack(">IHH", at, len(dl) // 32, len(part_clusters))
            rec += bytes(part_clusters).ljust(10, b"\xff")
            recs.append((ti, self.put(rec)))
        objs = bytearray()
        for ti, rec_at in recs:
            o = bytearray(ea_la.DMF_OBJECT)
            struct.pack_into(">4I", o, 0x28, ti, 1, rec_at, 0)
            objs += o
        obj = self.put(bytes(objs))
        struct.pack_into(">II", self.body, 0x20, len(clusters), cl)
        struct.pack_into(">II", self.body, 0x28, len(recs), obj)
        struct.pack_into(">II", self.body, 0x30, len(textures), tex)
        struct.pack_into(">III", self.body, 0x48, len(bones), names, angles)
        struct.pack_into(">6I", self.body, 0x5C, 4, pos, 4, nrm, 4, uv)
        return bytes(self.body)


def tpk(shapes: dict[str, bytes]) -> bytes:
    n = len(shapes)
    table = 16 + 16 * n
    body = bytearray(table + 4 * n)
    body[:4] = ea_la.TPK_MAGIC
    struct.pack_into(">3I", body, 4, n, 16, table)
    for i, (name, blob) in enumerate(shapes.items()):
        body[16 + 16 * i : 32 + 16 * i] = name.encode().ljust(16, b"\0")
        entry = len(body)
        body += struct.pack(">I", entry + 0x40) + bytes(0x3C) + blob
        struct.pack_into(">I", body, table + 4 * i, entry)
    return bytes(body)


def test_skeleton_walks_depth_first_with_rotations():
    sk = ea_la.parse_skl(
        skl([("Root", (0, 0, 1), -1), ("Arm", (0.5, 0, 0), 0), ("Hand", (0.5, 0, 0), 1)])
    )
    assert sk.names == ["Root", "Arm", "Hand"]
    # the arm turns a quarter about the up axis: the hand ends up along the front axis
    world = sk.world(np.array([[0, 0, 0], [0, 0, 16384], [0, 0, 0]]))
    np.testing.assert_allclose(world[1][1], [0.5, 0, 1], atol=1e-6)
    np.testing.assert_allclose(world[2][1], [0.5, 0.5, 1], atol=1e-6)


def test_dmf_parts_land_in_their_cluster_frames_and_bind_tpk_textures():
    skel = skl([("Root", (0, 0, 1), -1), ("Arm", (0.5, 0, 0), 0)])
    quad = [(0, i, 0, i) for i in range(4)]
    data = Dmf().build(
        bones=["Root", "Arm"],
        rest=[(0, 0, 0), (0, 0, 16384)],
        clusters=[(0, 0, 4096), (1, 0, 4096)],
        textures=["SKIN"],
        parts=[(0, [0], quad), (0, [1], quad), (0, [0, 1], [(3, i, 0, i) for i in range(4)])],
    )
    assert ea_la.is_dmf(data[:8]) and ea_la.is_skl(skel[:8])
    model = ea_la.parse_dmf(data, ea_la.parse_skl(skel))
    assert model.name == "Test" and model.warnings == [] and len(model.parts) == 3
    a, b, c = model.parts
    # cluster 0: root frame at (0, 0, 1); cluster 1: the arm's quarter turn about up, at the
    # root's origin (a cluster sits at its parent joint); the slot byte is 3 x the index into
    # the part's own cluster list
    np.testing.assert_allclose(a.positions[1], [1, 0, 1], atol=1e-6)
    np.testing.assert_allclose(b.positions[1], [0, 1, 1], atol=1e-6)
    np.testing.assert_allclose(c.positions[1], [0, 1, 1], atol=1e-6)
    np.testing.assert_allclose(b.normals[0], [0, 0, 1], atol=1e-6)
    assert len(a.triangles) == 2 and a.texture == "SKIN"
    np.testing.assert_allclose(a.uvs[3], [1, 1])
    pack = tpk({"skin": shpg()})
    assert ea_la.is_tpk(pack[:16]) and list(ea_la.tpk_shapes(pack)) == ["SKIN"]

    class Src:
        def __init__(self, files):
            self.files = files
            self.by_path = dict.fromkeys(files)

        def get(self, p):
            return self.files[p]

    files = {
        "files/DATA/1/1_1/level.viv/Test.dmf": data,
        "files/DATA/1/1_1/level.viv/Soldier.skl": skel,
        "files/DATA/1/1_1/level.viv/tpk1_1.tpk": pack,
    }
    path = "files/DATA/1/1_1/level.viv/Test.dmf"
    assert plugin.detect(path, data[:64], len(data))
    (scene,) = plugin.extract(data, path, Src(files))
    assert scene.warnings == [] and len(scene.primitives) == 3
    assert scene.materials[0].texture == "SKIN" and tuple(scene.textures["SKIN"][0, 0]) == (
        0,
        0,
        255,
        255,
    )
    # the PS2 layout beside it is not claimed
    ps2 = bytearray(data)
    struct.pack_into(">I", ps2, 4, ea_la.DMF_VERSION_PS2)
    assert not plugin.detect(path, bytes(ps2[:64]), len(ps2))
