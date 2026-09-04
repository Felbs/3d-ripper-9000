"""Climax .bog textures and .rom models (gcrip.formats.climax_bog / climax_rom), the members
of the .bad archives once the .bah names them."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import climax_bog, climax_rom
from gcrip.plugins import climax_bog as bog_plugin
from gcrip.plugins import climax_rom as rom_plugin


def bog(version=b"BOG 1.02   \0", fmt=0x40, w=8, h=8) -> bytes:
    head = bytearray(climax_bog.HEADERS[version[:8]])
    head[:12] = version
    struct.pack_into(">6I", head, 12, fmt, w, h, 1, 1, w * h)
    body = b""
    if fmt == 0x40:
        body += bytes(sum(([255, i, 0, 0] for i in range(256)), []))  # ARGB: opaque, red ramp
        body += bytes(range(w * h))  # C8 indices, 8x4 tiles: two tiles of 32
    else:
        body += bytes(w * h // 2)  # CMPR, 8x8 = two 8-byte blocks... four
        body += bytes(32 - len(body))
    return bytes(head) + body


def test_bog_headers_differ_by_version_and_palettes_are_argb():
    data = bog()
    assert climax_bog.is_bog(data[:64])
    assert climax_bog.header(data[:64]).data_at == 56
    rgba = climax_bog.decode(data)
    assert rgba.shape == (8, 8, 4)
    assert rgba[0, 0].tolist() == [0, 0, 0, 255]  # index 0 -> palette entry 0: A=255, R=0
    old = bog(version=b"BOG 1.01   \0")
    assert climax_bog.header(old[:64]).data_at == 40 and climax_bog.decode(old).shape == (8, 8, 4)
    assert not climax_bog.is_bog(b"BOG 1.03   " + bytes(60))
    (scene,) = bog_plugin.extract(data, "cars/24_7/cache/tex_high/pal/24_7.bog", None)
    assert scene.extras["textures_only"] and "24_7" in scene.textures


def rom(version=b"ROM 1.26", patch=False) -> bytes:
    mesh_header = climax_rom.MAGICS[version]
    head = bytearray(climax_rom.HEADER)
    head[:8] = version
    struct.pack_into(">6I", head, 12, 1, 0, 1, 0, 0, 1)
    mat = bytearray(climax_rom.MATERIAL)
    mat[:9] = b"Tpage2ATC"
    point = b"frwheelcentre".ljust(32, b"\0") + struct.pack(">3f", 0.5, 0.25, 1.0)
    mesh = bytearray(mesh_header)
    if patch:
        struct.pack_into(">Ii", mesh, 0, 1, -1)
        struct.pack_into(">4I", mesh, 0x14, 0, 1, 0, 0)
        body = bytearray(climax_rom.PATCH)
        grid = [(i / 3, j / 3) for i in range(4) for j in range(4)]
        struct.pack_into(">16f", body, 12, *(x for x, _ in grid))
        struct.pack_into(">16f", body, 12 + 64, *(0.0 for _ in grid))
        struct.pack_into(">16f", body, 12 + 128, *(z for _, z in grid))
    else:
        struct.pack_into(">Ii", mesh, 0, 0, 0)
        struct.pack_into(">4I", mesh, 0x14, 2, 0, 0, 4)
        body = struct.pack(">6I", 0, 1, 2, 0, 2, 3)
        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)):
            body += struct.pack(">14f", x, y, 0, 0, 0, 1, x, y, 0, 0, 0, 0, 0, 0)
    return bytes(head) + bytes(mat) + point + bytes(mesh) + bytes(body)


def test_a_triangle_mesh_reads_with_its_material_and_points():
    data = rom()
    assert climax_rom.is_rom(data[:64], len(data))
    m = climax_rom.parse(data)
    assert m.materials == ["Tpage2ATC"] and m.points == [("frwheelcentre", (0.5, 0.25, 1.0))]
    (mesh,) = m.meshes
    assert mesh.material == 0 and mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]
    assert mesh.positions[2].tolist() == [1.0, 1.0, 0.0] and mesh.uvs[2].tolist() == [1.0, 1.0]
    assert np.allclose(mesh.normals[0], [0, 0, 1])


def test_version_one_twenty_seven_has_a_longer_mesh_header():
    m = climax_rom.parse(rom(b"ROM 1.27"))
    assert len(m.meshes) == 1 and m.meshes[0].positions[1].tolist() == [1.0, 0.0, 0.0]


def test_a_patch_tessellates_to_a_grid():
    m = climax_rom.parse(rom(patch=True))
    (mesh,) = m.meshes
    n = climax_rom.PATCH_STEPS + 1
    assert mesh.patches == 1 and len(mesh.positions) == n * n
    assert len(mesh.indices) == climax_rom.PATCH_STEPS**2 * 2 * 3
    # a flat patch spanning the unit square stays inside it, corners included
    assert np.allclose(mesh.positions[0], [0, 0, 0], atol=1e-6)
    assert np.allclose(mesh.positions[-1], [1, 0, 1], atol=1e-6)
    assert mesh.positions[:, 1].max() == 0


def test_the_rom_plugin_binds_bog_textures_by_material_name():
    files = {"Cars/ATC/Body.rom": rom(), "Cars/ATC/Tpage2ATC.bog": bog()}

    class Src:
        by_path = dict.fromkeys(files)

        def get(self, p):
            return files[p]

    assert rom_plugin.detect("Cars/ATC/Body.rom", files["Cars/ATC/Body.rom"][:64], 999)
    (scene,) = rom_plugin.extract(files["Cars/ATC/Body.rom"], "Cars/ATC/Body.rom", Src())
    assert scene.materials[0].texture == "Tpage2ATC" and "Tpage2ATC" in scene.textures
    assert scene.extras["points"] == ["frwheelcentre"]
