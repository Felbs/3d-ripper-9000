"""A2M 2004-05 (Scooby-Doo! Unmasked, Scaler): the .ghr level archive, EF3dObjRes objects and
EFStatic3dObj worlds serialised as DTBinaryPersistStream, and the .htd texture dictionaries."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import a2m_hg
from gcrip.plugins import a2m_hg as plugin

QUAD = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], np.float32)


def material(flags: int, textures: list[str], static: bool = False) -> bytes:
    out = (
        bytes([255, 128, 64, 255])
        + struct.pack(">3f", 1, 1, 1)
        + struct.pack(">II", flags, 0x40420002)
    )
    out += struct.pack(">I", len(textures))
    for t in textures:
        out += struct.pack(">I", 0) + t.encode().ljust(32, b"\0")
    return out


def vertices(flags: int, skin: bool = False) -> bytes:
    out = b""
    for i, p in enumerate(QUAD):
        if flags & 1:
            out += struct.pack(">3f", *p)
        if flags & 2:
            out += struct.pack(">3f", 0, 0, 1)
        if flags & 4:
            out += bytes([i, 0, 0, 255])
        if flags & 8:
            out += struct.pack(">2f", p[0], p[1])
        if flags & 32:
            out += struct.pack(">4f", 0.75, 0.25, 0, 0) + bytes([0, 1, 0, 0])
    return out


def rigid_sub(material_index: int, flags: int) -> bytes:
    """u32, u32 material, vertices, strips + spheres, corner order, GX list."""
    corners = [0, 1, 2, 3]
    dl = b"\x98\x00\x04" + b"".join(struct.pack(">4H", i, i, i, i) for i in corners)
    out = struct.pack(">II", 0, material_index) + struct.pack(">I", 4) + vertices(flags)
    out += struct.pack(">I", 1) + struct.pack(">H", 4) + struct.pack(">4f", 0, 0, 0, 1)
    out += struct.pack(">H", 4) + struct.pack(">4H", *corners)
    out += struct.pack(">I", len(dl)) + dl
    return out


def skinned_sub(material_index: int, flags: int, records: bool) -> bytes:
    out = struct.pack(">II", 0, material_index) + struct.pack(">I", 4) + vertices(flags, True)
    if records:
        out += struct.pack(">H", 2)
        out += struct.pack(">3H", 0, 1, 2).ljust(20, b"\0") + struct.pack(">3H", 2, 1, 3).ljust(
            20, b"\0"
        )
        out += struct.pack(">H", 0)
    else:
        out += (
            struct.pack(">I", 1)
            + struct.pack(">H", 4)
            + struct.pack(">H", 4)
            + struct.pack(">4H", 0, 1, 2, 3)
        )
    return out


def dynamic_surface(mats: list[bytes], subs: list[bytes]) -> bytes:
    return (
        struct.pack(">II", 0, len(mats))
        + b"".join(mats)
        + struct.pack(">I", len(subs))
        + b"".join(subs)
        + struct.pack(">I", 0)
    )


def hg_object(name: str, records: bool = False) -> bytes:
    path = f"z:\\game\\objects\\{name}".encode()
    out = bytes([len(path)]) + path + bytes(12)
    out += struct.pack(">4H", 0, 2, 1, 1) + bytes(16)
    # two bones: a root and a child translated up one
    for k, ty in enumerate((0.0, 1.0)):
        m = np.eye(4, dtype=">f4")
        m[3, 1] = ty
        out += m.tobytes() + struct.pack(">4HI", 0xFFFF if k == 0 else 0, 0xFFFF, 0xFFFF, 0, 0)
    out += np.eye(4, dtype=">f4").tobytes() * 2  # inverse bind matrices
    out += struct.pack(">H", 0)
    # one LOD: a skin surface over bones [0, 1] and a rigid group over bone [1]
    skin = dynamic_surface([material(0x2F, ["skin"])], [skinned_sub(0, 0x2F, records)])
    rigid = dynamic_surface([material(0x0F, ["crate"])], [rigid_sub(0, 0x0F)])
    out += struct.pack(">H", 1) + struct.pack(">H", 2) + struct.pack(">2H", 0, 1) + skin
    out += struct.pack(">H", 1) + struct.pack(">H", 1) + rigid
    return out


def hg_world() -> bytes:
    out = bytes(12) + struct.pack(">HHI", 2, 1, 0)
    out += struct.pack(">I", 0) + bytes(0x38) + bytes(1 * 1) + struct.pack(">I", 0)
    clone = dynamic_surface([material(0x0F, ["crate"])], [rigid_sub(0, 0x0F)])
    out += struct.pack(">HH", 1, 0) + struct.pack(">Iff", 0, 1.0, 2.0) + clone
    out += struct.pack(">HH", 1, 1) + bytes(0x50) + bytes(12)
    out += bytes(0x1E) * 2
    mats = [material(0x0F, ["crate"], True), material(0x03, [], True)]
    out += struct.pack(">II", len(mats), 1) + b"".join(mats)
    out += struct.pack(">II", 2, 3)
    out += (
        struct.pack(">II", 0, 2)
        + struct.pack(">I", 1)
        + struct.pack(">I", 0)
        + rigid_sub(0, 0x0F)[8:]
    )
    out += struct.pack(">II", 1, 1) + struct.pack(">I", 0) + rigid_sub(1, 0x03)[8:]
    return out


def htd(textures: list[tuple[str, int, int, int, bytes]], palettes: int = 1) -> bytes:
    out = struct.pack(">II", palettes, len(textures))
    for k in range(palettes):
        entries = b"".join(struct.pack("4B", 255, i, 0, 0) for i in range(256))
        out += struct.pack(">II", 256, 1 + k) + entries * (1 + k)
    for name, w, h, fmt, tiles in textures:
        out += name.encode().ljust(32, b"\0") + struct.pack(">4I", w, h, fmt, 0) + tiles
    return out


def ghr(records: list[tuple[int, int, bytes]]) -> bytes:
    table = bytearray(struct.pack(">4I", 0x6543, len(records), 0, 0))
    body = bytearray()
    for cls, res, payload in records:
        table += struct.pack(">4I", len(body), cls, res, len(payload))
        body += payload + bytes(-len(payload) % 32)
    return bytes(table) + bytes(body)


def test_object_bones_lods_and_both_skin_forms():
    for records in (False, True):
        model = a2m_hg.parse_object(hg_object("shaggy_ref", records))
        assert model.name == "shaggy_ref" and model.warnings == [] and model.lods == 1
        assert [b.parent for b in model.bones] == [-1, 0]
        np.testing.assert_allclose(model.bones[1].matrix[3, :3], [0, 1, 0])
        assert [m.textures for m in model.materials] == [["skin"], ["crate"]]
        skin, rigid = model.meshes
        assert skin.material == 0 and rigid.material == 1
        np.testing.assert_allclose(skin.positions, QUAD)
        assert len(skin.triangles) == 2 and len(rigid.triangles) == 2
        # skin slots map through the surface's bone list [0, 1]: slot 1 -> bone 1
        assert skin.joints[0].tolist() == [0, 1, 0, 0]
        np.testing.assert_allclose(skin.weights[0], [0.75, 0.25, 0, 0])
        assert rigid.joints is None and rigid.colors[1].tolist() == [1, 0, 0, 255]
        np.testing.assert_allclose(rigid.uvs[3], [1, 1])


def test_world_container_behind_pvs_and_env_clones():
    model = a2m_hg.parse_world(hg_world())
    assert model.warnings == [] and len(model.meshes) == 2
    assert [m.material for m in model.meshes] == [0, 1]
    assert model.meshes[1].uvs is None and model.meshes[1].normals is not None
    assert model.materials[0].textures == ["crate"]


def test_htd_dictionary_and_the_ghr_container_through_the_plugin():
    tiles = bytes([0xFF, 0xFF, 0, 0, 0, 0, 0, 0]) * 4  # 8x8 CMPR: one block a quadrant, white
    pack = htd([("crate", 8, 8, 14, tiles), ("skin", 8, 8, 14, tiles)], palettes=2)
    assert a2m_hg.is_htd(pack[:64], len(pack))
    assert a2m_hg.htd_names(pack) == ["crate", "skin"]
    texs = a2m_hg.parse_htd(pack)
    assert [t.name for t in texs] == ["crate", "skin"] and texs[0].rgba.shape == (8, 8, 4)
    assert tuple(texs[0].rgba[0, 0]) == (255, 255, 255, 255)
    level = ghr(
        [
            (24, 0xFFFFFFFF, hg_world()),
            (69, 5, b"code"),
            (91, 7, hg_object("crate_ref")),
            (91, 8, hg_object("crate_ref")),
        ]
    )
    assert a2m_hg.is_ghr(level[:64], len(level))
    assert plugin.is_container("files/level/W1L3/gen/W1L3.ghr", level[:64])
    members = plugin.expand(level)
    assert [n for n, _ in members] == [
        "world_ffffffff.hgworld",
        "crate_ref.hgobj",
        "crate_ref_1.hgobj",
    ]

    class Src:
        def __init__(self, files):
            self.files = files
            self.by_path = dict.fromkeys(files)

        def get(self, p):
            return self.files[p]

    files = {f"files/level/W1L3/gen/W1L3.ghr/{n}": b for n, b in members}
    files["files/level/W1L3/gen/TEXDIC.htd"] = pack
    src = Src(files)
    path = "files/level/W1L3/gen/W1L3.ghr/crate_ref.hgobj"
    assert plugin.detect(path, files[path][:64], len(files[path]))
    (scene,) = plugin.extract(files[path], path, src)
    assert len(scene.primitives) == 2 and len(scene.joints) == 2
    assert scene.materials[0].texture == "skin" and scene.materials[1].texture == "crate"
    assert scene.primitives[0].joints is not None and scene.primitives[1].joints is None
    path = "files/level/W1L3/gen/W1L3.ghr/world_ffffffff.hgworld"
    (world,) = plugin.extract(files[path], path, src)
    assert len(world.primitives) == 2 and not world.joints and world.materials[0].texture == "crate"
