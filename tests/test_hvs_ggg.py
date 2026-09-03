"""High Voltage GGG models: header, node tree, packed arrays, 32-aligned strips, the AGM
material database and the plugin's texture binding."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import hvs_agm, hvs_ggg
from gcrip.plugins import hvs_ggg as plugin
from tests.test_tpl_hvs import build as build_tpl


def _ggg(*, normals: bool = False, block: int = 0, skinned: bool = False, two_nodes: bool = False) -> bytes:
    """Two quads (meshes) over a shared vertex pool, positions s16 with 13 fraction bits."""
    materials = [b"MatA".ljust(16, b"\0"), b"MatB".ljust(16, b"\0")]
    mblock = b"".join(materials)
    mask = hvs_ggg.BIT_POS | hvs_ggg.BIT_TEX | hvs_ggg.BIT_CLR | (hvs_ggg.BIT_NRM if normals else 0)
    attrs = 3 + (1 if normals else 0)
    nverts = 8
    quad = lambda z: [(-8192, -8192, z), (8192, -8192, z), (8192, 8192, z), (-8192, 8192, z)]  # noqa: E731
    pos = quad(0) + quad(4096)
    pos_bytes = b"".join(struct.pack(">3h", *p) for p in pos)
    arrays = pos_bytes
    starts = [-1] * 7
    if normals:
        starts[hvs_ggg.SLOT_NRM] = len(arrays)
        arrays += bytes([0, 0, 64] * nverts)
        arrays += b"\0" * (-len(arrays) % 2)
    starts[hvs_ggg.SLOT_TEX] = len(arrays)
    arrays += b"".join(struct.pack(">2h", (i % 2) * 16384, (i // 2 % 2) * 16384) for i in range(nverts))
    starts[hvs_ggg.SLOT_CLR] = len(arrays)
    arrays += bytes([255, 0, 0, 255] * 4 + [0, 0, 255, 255] * 4)
    starts[hvs_ggg.SLOT_DL] = len(arrays)
    # the header block's size is fixed before the strips exist, so the strips can be
    # placed at absolute 32-byte boundaries the way the game's exporter does
    hdr_len = len(mblock) + (2 * 24 if two_nodes else 24) + 2 * struct.calcsize(hvs_ggg.MESH_FMT)
    geom_len = struct.calcsize(hvs_ggg.GEOM_FMT) + (0x44 - 0x24) + 7 * 4
    geom_len += -geom_len % 16
    hdr_len += geom_len
    dl_abs = 0x60 + hdr_len + block + len(arrays)
    lists = b""
    mesh_records = []
    strips = []
    for k in range(2):
        lists += b"\0" * (-(dl_abs + len(lists)) % 32)
        strip = bytes([0x9C]) + struct.pack(">H", 4)
        for v in (0, 1, 3, 2):
            strip += (bytes([k]) if skinned else b"") + struct.pack(f">{attrs}H", *([v] * attrs))
        lists += strip
        strips.append(strip)
        mesh_records.append(
            struct.pack(
                hvs_ggg.MESH_FMT,
                0, -1, 4 * k, 4 * k, 4, 1, 4, 0x21, k, 2, 1, 0, 4 * k,
                0xB301, attrs | (0x200 if skinned else 0), 4, len(strip) + 32,
            )
        )
    lists += b"\0" * (-len(lists) % 32)
    node_a = struct.pack(">III", 2 if not two_nodes else 1, 0, 1) + b"Root".ljust(12, b"\0")
    tree = node_a + mesh_records[0]
    if two_nodes:
        tree += struct.pack(">III", 1, 0, 1) + b"Child".ljust(12, b"\0")
    tree += mesh_records[1]
    geom = struct.pack(hvs_ggg.GEOM_FMT, 0x40, nverts, 0.0, 0.0, 0.0, 0x1200, attrs, 4, mask)
    geom += struct.pack(">IIIIIIII", 0, 1, 0x14000000, 0x1E00B301, 13 << 16, 0, 1, 0)
    geom += struct.pack(">7i", *starts)
    geom += b"\0" * (-len(geom) % 16)
    header_block = mblock + tree + geom
    assert len(header_block) == hdr_len
    hdr = 0x60 + len(header_block)
    payload = bytes(block) + arrays + lists
    head = bytearray(0x60)
    head[:8] = hvs_ggg.MAGIC
    struct.pack_into(">II", head, 8, 0x00020008, hdr + len(payload))
    struct.pack_into(">I", head, 0x18, len(header_block))
    struct.pack_into(">II", head, 0x20, 2 if two_nodes else 1, len(mblock))
    struct.pack_into(">I", head, 0x2C, len(mblock) + len(tree))
    struct.pack_into(">I", head, 0x44, block)
    struct.pack_into(">I", head, 0x4C, block + starts[hvs_ggg.SLOT_DL])
    return bytes(head) + header_block + payload


def test_header_nodes_and_meshes():
    data = _ggg()
    m = hvs_ggg.parse(data)
    assert m.materials == ["MatA", "MatB"]
    assert m.nodes == ["Root"]
    assert [x.vertex_base for x in m.meshes] == [0, 4]
    assert m.total_vertices == 8 and m.frac == 13
    assert hvs_ggg.is_ggg(data[:64])


def test_arrays_scale_and_strips_decode():
    data = _ggg()
    m = hvs_ggg.parse(data)
    md = hvs_ggg.meshes(data, m)
    assert len(md) == 2
    assert md[0].positions[:, 0].min() == pytest.approx(-1.0)
    assert md[1].positions[:, 2].max() == pytest.approx(0.5)
    assert md[0].indices.size == 6 and md[1].indices.size == 6
    assert md[0].uvs is not None and md[0].uvs.max() == pytest.approx(1.0)
    assert tuple(md[1].colors[0]) == (0, 0, 255, 255)
    assert md[0].normals is None


def test_normals_skin_bytes_and_leading_block():
    data = _ggg(normals=True, skinned=True, block=64)
    m = hvs_ggg.parse(data)
    md = hvs_ggg.meshes(data, m)
    assert len(md) == 2 and md[0].normals is not None
    assert md[0].normals[0].tolist() == [0.0, 0.0, 1.0]
    assert m.meshes[0].skinned


def test_two_nodes_interleave_with_their_meshes():
    data = _ggg(two_nodes=True)
    m = hvs_ggg.parse(data)
    assert m.nodes == ["Root", "Child"]
    assert [x.node for x in m.meshes] == [0, 1]
    assert len(hvs_ggg.meshes(data, m)) == 2


AGM = """StagedShaderTexture[3]
{
\t"TstBrck"
\tDefault
\t"HSout2LT"
}
Material[2]
{
\tMaterial "MatA"
\t{
\t\tSimpleTextureShader 2
\t}
\tMaterial "MatB"
\t{
\t\tSimpleTextureShader 1
\t}
}
"""


def test_agm_binds_materials_to_named_textures():
    assert hvs_agm.textures(AGM) == {"MatA": "HSout2LT"}


class _Src:
    def __init__(self, members: dict[str, bytes]) -> None:
        self.by_path = {k: None for k in members}
        self.members = members

    def get(self, path: str) -> bytes:
        return self.members[path]


def test_plugin_textures_through_the_archive():
    ggg = _ggg()
    tpl = build_tpl(((8, 8, 0x0E),))
    src = _Src({"Levels/House4.JAM/CAR.GGG": ggg, "Levels/House4.JAM/CAR.AGM": AGM.encode(), "Levels/House4.JAM/HSOUT2LT.TPL": tpl})
    assert plugin.detect("Levels/House4.JAM/CAR.GGG", ggg[:64], len(ggg))
    (scene,) = plugin.extract(ggg, "Levels/House4.JAM/CAR.GGG", src)
    assert scene.name == "Root"
    assert scene.materials[0].texture == "HSout2LT" and scene.materials[1].texture is None
    assert scene.textures["HSout2LT"].shape == (8, 8, 4)
    assert len(scene.primitives) == 2
