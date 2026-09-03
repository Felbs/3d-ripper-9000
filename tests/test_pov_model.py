"""Point of View's Smashing Drive files: PHM models (s_model from the shipped DWARF), TIM
texture records, and the TG_<phase> layouts that place them."""

from __future__ import annotations

import math
import struct

import numpy as np

from gcrip.formats import pov_level, pov_model, toc_wad
from gcrip.plugins import pov_level as level_plugin
from gcrip.plugins import pov_model as model_plugin


def phm(quad=None, material_texture: int = 0, bone_name: bytes = b"RootBone") -> bytes:
    """A model of one mesh: a quad as one strip, one material mapping one texture def."""
    quad = (
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], np.float32) if quad is None else quad
    )
    body = bytearray(256)

    def put(blob: bytes, align: int = 4) -> int:
        while len(body) % align:
            body.append(0)
        at = len(body)
        body.extend(blob)
        return at

    verts = b""
    for i, (x, y, z) in enumerate(quad):
        verts += struct.pack(">2f4f4f4B", x, y, x, y, z, 1.0, 0, 0, 1, 0, 255, 128, 64, 255 - i)
    pv = put(verts)
    mat = bytearray(pov_model.MATERIAL)
    struct.pack_into(">15i", mat, 72, material_texture, *([-1] * 14))
    pmat = put(bytes(mat))
    bone = bytearray(pov_model.BONE)
    bone[: len(bone_name)] = bone_name
    struct.pack_into(">4i", bone, 80, -1, -1, -1, 0)
    pbone = put(bytes(bone))
    ptex = put(b"QUADTEX".ljust(16, b"\0") + bytes(4))
    idx = put(struct.pack(">4I", 0, 1, 2, 3))
    cmds = put(
        struct.pack(">BBHI", pov_model.CMD_MATERIAL, 0, 0, 0)
        + struct.pack(">BBHI", pov_model.CMD_STRIP, 0, 0, 2)
        + bytes(8)
    )
    mesh = bytearray(pov_model.MESH)
    struct.pack_into(">IfIIIII", mesh, 48, 0, 1.0, 2, idx, 0, 0, cmds)
    pmesh = put(bytes(mesh))
    plist = put(struct.pack(">I", pmesh))
    struct.pack_into(">HHf", body, 8, 0, pov_model.VERTEX, 1.0)
    struct.pack_into(">3f", body, 0x20, 0, 0, 0)
    struct.pack_into(">3f", body, 0x30, 1, 1, 0)
    struct.pack_into(">II", body, 0x40, len(quad), pv)
    struct.pack_into(">II", body, 0x60, 1, pmat)
    struct.pack_into(">II", body, 0x6C, 1, pbone)
    struct.pack_into(">II", body, 0x74, 1, plist)
    struct.pack_into(">II", body, 0xAC, 1, ptex)
    return bytes(body)


def tim(width: int = 8, height: int = 8) -> bytes:
    """One I8 texture record: the count shares the first header's word 0."""
    head = bytearray(pov_model.TEXTURE_HEADER)
    struct.pack_into(">I", head, 0, 1)
    head[5] = 1  # GX I8
    struct.pack_into(">HHHIIIII", head, 6, width, height, 8, width * height, 0, 64, 0, 0)
    return bytes(head) + bytes([200]) * (width * height)


def test_a_model_is_recognised_inside_the_sixty_four_byte_sniff():
    data = phm()
    assert pov_model.is_model(data[:64], len(data))
    assert model_plugin.detect("files/common.wad/QUAD.PHM", data[:64], len(data))
    assert not pov_model.is_model(bytes(64), 4096)


def test_the_strip_command_reads_u32_indices_from_the_mesh_list():
    model = pov_model.parse(phm())
    assert len(model.positions) == 4
    (mesh,) = model.meshes
    assert mesh.name == "RootBone"
    assert mesh.triangles.tolist() == [[0, 1, 2], [1, 3, 2]]
    assert mesh.materials.tolist() == [0, 0]
    assert model.materials == [[0]]
    assert model.texture_defs == ["QUADTEX"]
    assert model.colors[:, 3].tolist() == [255, 254, 253, 252]


def test_a_tim_record_decodes_and_the_plugin_binds_it_by_texture_def_name():
    (tex,) = pov_model.parse_tim(tim())
    assert tex.rgba.shape == (8, 8, 4) and tex.error is None

    class Src:
        by_path = {"files/common.wad/QUAD.PHM": None, "files/common.wad/QUADTEX.TIM": None}

        def get(self, p):
            return tim()

    (scene,) = model_plugin.extract(phm(), "files/common.wad/QUAD.PHM", Src())
    assert scene.materials[0].texture == "QUADTEX"
    assert "QUADTEX" in scene.textures
    assert scene.primitives[0].indices.tolist() == [0, 1, 2, 1, 3, 2]


def wad(records: list[tuple[bytes, bytes, int, bytes]]) -> bytes:
    """The inline .wad: name[16] type[4] u32 size u32 user, then the bytes."""
    out = b""
    for name, kind, user, blob in records:
        out += name.ljust(16, b"\0") + kind.ljust(4, b"\0") + struct.pack(">2I", len(blob), user)
        out += blob
    return out


def layout(placements: list[tuple[int, tuple, float]], phase: bool = True) -> bytes:
    """One cell (phase header) or the inline-cells scene header, placing ``placements`` -
    (record id, position, yaw about +Y)."""
    recs = struct.pack(">I", len(placements))
    for rid, pos, yaw in placements:
        recs += struct.pack(">4HI3f3ff", 1, 0, rid, 0, 0, *pos, 0, 1, 0, yaw)
    if phase:
        # header, one (distance, ptr) section at +20 with an empty list, the cell table,
        # the cell's placements, the extras pointer at the end
        pcells = 32
        pplace = pcells + 4 + pov_level.CELL
        empty = pplace + len(recs)
        body = bytearray(struct.pack(">5I", 0x10, pcells, 0, 0, 1) + struct.pack(">2I", 0, empty))
        body += bytes(4) + struct.pack(">I", 1)
        body += struct.pack(">3ffII", 0, 0, 0, 100.0, 0, pplace) + recs + struct.pack(">I", 0)
        struct.pack_into(">I", body, 8, len(body))
        return bytes(body)
    pplace = 20 + pov_level.CELL
    body = struct.pack(">5I", 0, 0x10, pplace + len(recs), 0, 1)
    body += struct.pack(">3ffII", 0, 0, 0, 100.0, 0, pplace) + recs
    return body


def test_both_layout_headers_are_recognised_and_place_by_record_id():
    for phase in (True, False):
        data = layout([(7, (10.0, 0.0, 20.0), math.pi / 2)], phase=phase)
        assert pov_level.is_level(data[:64], len(data))
        level = pov_level.parse(data)
        (p,) = level.placements
        assert p.model == 7 and p.position == (10.0, 0.0, 20.0)
        assert len(level.sections) == (1 if phase else 0)
    assert not pov_level.is_level(bytes(64), 4096)


def test_the_rotation_turns_a_forward_vector_the_way_the_traffic_drives():
    p = pov_level.Placement(0, 0, 0, 0, (0, 0, 0), (0, 1, 0), math.pi / 2)
    forward = np.array([0, 0, 1.0]) @ p.matrix()
    assert np.allclose(forward, [1, 0, 0], atol=1e-6)


def test_the_phase_scene_places_props_and_keeps_the_unplaced_models_in_world_space():
    prop = phm(bone_name=b"Lamp")
    building = phm(quad=np.array([[100, 0, 0], [101, 0, 0], [100, 1, 0], [101, 1, 0]], np.float32))
    common = wad([(b"LAMP", b"PHM", 7 << 16, prop), (b"QUADTEX", b"TIM", 0, tim())])
    phase = wad(
        [
            (b"F11_000B", b"PHM", 9 << 16, building),
            (b"TG_FASE_11", b"BIN", 0, layout([(7, (10.0, 0.0, 20.0), 0.0)])),
            (b"TG_INTRO_11", b"BIN", 0, layout([(7, (0.0, 0.0, 0.0), 0.0)], phase=False)),
        ]
    )
    files = {"files/common.wad": common, "files/fase_11.wad": phase}
    for wp, blob in list(files.items()):
        for name, member in toc_wad.expand(blob):
            files[f"{wp}/{name}"] = member
    assert toc_wad.members(common)[0].user == 7 << 16

    class Src:
        by_path = dict.fromkeys(files)

        def get(self, p):
            return files[p]

    path = "files/fase_11.wad/TG_FASE_11.BIN"
    data = files[path]
    assert level_plugin.detect(path, data[:64], len(data))
    (scene,) = level_plugin.extract(data, path, Src())
    assert scene.extras["placed"] == 1 and scene.extras["world_models"] == 1
    pos = np.concatenate([p.positions for p in scene.primitives])
    assert [10.0, 0.0, 20.0] in pos.tolist()  # the lamp moved
    assert [100.0, 0.0, 0.0] in pos.tolist()  # the building did not
    assert scene.materials[0].texture == "QUADTEX"
    # the intro scene places its prop but does not repeat the phase's world models
    intro = "files/fase_11.wad/TG_INTRO_11.BIN"
    (scene,) = level_plugin.extract(files[intro], intro, Src())
    assert scene.extras["placed"] == 1 and scene.extras["world_models"] == 0
