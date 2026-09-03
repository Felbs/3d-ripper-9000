"""EA Tiburon TMdl models: section table, GX attribute arrays, display lists, materials and
the named MMAP texture pack."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import ea_terf, ea_tmdl, gx_texture
from gcrip.plugins import ea_tmdl as plugin


def _mmap_pack(names: list[str], w: int = 8, h: int = 4, stale: int = 0) -> bytes:
    """A C8 pack with one level per name (plus ``stale`` garbage slots), 16-byte name block."""
    tiles = gx_texture.encoded_size(9, w, h)
    n = len(names)
    slots = n + stale
    hdr_size = 0x28
    level_tbl = hdr_size
    data_off = level_tbl + 16 * slots
    pal_block = data_off + tiles * n
    pal_entries = pal_block + 12 * n
    name_block = pal_entries + 512 * n
    total = name_block + 16 * slots
    out = bytearray(b"MMAP" + struct.pack(">HH", 2, 0) + bytes([0, 1, 2, 3]))
    out += struct.pack(">HHHH", slots, n, slots, 0)
    out += struct.pack(">IIIII", total, hdr_size, pal_block, name_block, 0)
    for i in range(n):
        out += struct.pack(">HHHHII", w, h, 9, 0, tiles, data_off + tiles * i)
    for _ in range(stale):
        out += struct.pack(">HHHHII", 0, 0, 0, 0, 0xB0B0B0B0, 0xB0B0B0B0)
    for i in range(n):
        out += bytes(((p + i) % 2) for p in range(tiles))
    for i in range(n):
        out += struct.pack(">HHII", 1, 2, 512, pal_entries + 512 * i)
    for i in range(n):
        pal = bytearray(512)
        struct.pack_into(">H", pal, 0, 0x801F if i == 0 else 0xFC00)
        struct.pack_into(">H", pal, 2, 0xFC00 if i == 0 else 0x83E0)
        out += pal
    for name in names:
        out += name.encode("latin-1")[:15].ljust(16, b"\0")
    out += b"stale~00".ljust(16, b"\0") * stale
    assert len(out) == total
    return bytes(out)


def _tmdl(name: str = "cube.ea3", *, wide: bool = False, textures: list[str] | None = None) -> bytes:
    """One quad (two triangles) as a strip with POS s16 (frac 4), NRM s8 (frac 6), CLR0 RGBA8
    and TEX0 s16 (frac 12); ``wide`` switches the position indices to u16 and draws the quad
    as a GX quad instead of a strip."""
    body = bytearray(b"\0" * 0x100)  # header + section table live here; filled at the end
    info_off = len(body)
    body += name.encode() + b"\0"
    body += b"\0" * (-len(body) % 32)
    # arrays
    pos_off = len(body)
    body += struct.pack(">3h", -16, -16, 0) + struct.pack(">3h", 16, -16, 0)
    body += struct.pack(">3h", 16, 16, 0) + struct.pack(">3h", -16, 16, 0)
    nrm_off = len(body)
    body += struct.pack(">3b", 0, 0, 64)
    clr_off = len(body)
    body += bytes([255, 0, 0, 255]) + bytes([0, 255, 0, 128])
    tex_off = len(body)
    body += struct.pack(">2h", 0, 0) + struct.pack(">2h", 4096, 0) + struct.pack(">2h", 4096, 4096) + struct.pack(">2h", 0, 4096)
    body += b"\0" * (-len(body) % 32)
    # display list
    dl_off = len(body)
    dl = bytearray()
    if wide:
        dl += bytes([0x80]) + struct.pack(">H", 4)
        for v in (0, 1, 2, 3):
            dl += struct.pack(">H", v) + bytes([0, v % 2, v])
    else:
        dl += bytes([0x98]) + struct.pack(">H", 4)
        for v in (3, 0, 2, 1):
            dl += bytes([v, 0, v % 2, v])
    dl += b"\0" * (-len(dl) % 32)
    body += dl
    # attribute table and mesh table
    attr_off = len(body)
    body += struct.pack(">IHBBBBBB", pos_off, 4, 9, 6, 1, 3, 4, 3 if wide else 2)
    body += struct.pack(">IHBBBBBB", nrm_off, 1, 10, 3, 0, 1, 6, 2)
    body += struct.pack(">IHBBBBBB", clr_off, 2, 11, 4, 1, 5, 0, 2)
    body += struct.pack(">IHBBBBBB", tex_off, 4, 13, 4, 1, 3, 12, 2)
    mesh_off = len(body)
    body += struct.pack(">IHHHHHHB3x", dl_off, len(dl) // 32, 0, 0xFFFF, 2, 4, 0, 4)
    geom_end = len(body)
    # materials
    matl_off = len(body)
    names_off = matl_off + 8
    mat_name = b"lambert1_MATERIAL\0"
    shader = b"OnePass\0"
    tex_name = b"wall\0"
    rec_off = names_off + len(mat_name) + len(shader) + len(tex_name)
    rec_off += -rec_off % 16
    body += struct.pack(">II", 1, rec_off)
    body += mat_name + shader + tex_name
    body += b"\0" * (rec_off - len(body))
    body += struct.pack(">IIHHI", names_off, names_off + len(mat_name), 1, 0, names_off + len(mat_name) + len(shader))
    body += b"\0" * 28
    matl_end = len(body)
    sections = [(b"Info", info_off, len(name) + 1), (b"Geom", 0x60, geom_end - 0x60), (b"Matl", matl_off, matl_end - matl_off)]
    if textures is not None:
        text_off = len(body)
        pack = _mmap_pack(textures, stale=1)
        body += pack
        sections.append((b"Text", text_off, len(pack)))
    # Geom header at 0x60 (inside the reserved block, past the section table)
    struct.pack_into(">6I", body, 0x60, mesh_off, 1, attr_off, 4, 0xF, 0)
    struct.pack_into(">4sIHH4B", body, 0, b"TMdl", len(body), len(sections), 16, 0x10, 0x10, 6, 0)
    for i, (tag, off, size) in enumerate(sections):
        struct.pack_into(">4sIII", body, 16 + 16 * i, tag, off, size, 0)
    return bytes(body)


def test_parse_sections_meshes_attrs_and_materials():
    data = _tmdl()
    model = ea_tmdl.parse(data)
    assert model.name == "cube.ea3"
    assert set(model.sections) == {b"Info", b"Geom", b"Matl"}
    assert len(model.meshes) == 1 and model.meshes[0].triangles == 2 and model.meshes[0].attr_count == 4
    assert [a.va for a in model.attrs] == [9, 10, 11, 13]
    assert model.materials[0].name == "lambert1_MATERIAL"
    assert model.materials[0].shader == "OnePass"
    assert model.materials[0].texture == "wall"


def test_arrays_scale_by_fraction_bits():
    data = _tmdl()
    model = ea_tmdl.parse(data)
    pos = ea_tmdl.array(data, model.attrs[0])
    assert pos.shape == (4, 3) and pos[0].tolist() == [-1.0, -1.0, 0.0]
    nrm = ea_tmdl.array(data, model.attrs[1])
    assert nrm[0].tolist() == [0.0, 0.0, 1.0]
    clr = ea_tmdl.array(data, model.attrs[2])
    assert clr.dtype == np.uint8 and clr[1].tolist() == [0, 255, 0, 128]
    uv = ea_tmdl.array(data, model.attrs[3])
    assert uv[2].tolist() == [1.0, 1.0]


def test_strip_and_u16_quad_display_lists_give_two_triangles():
    for wide in (False, True):
        data = _tmdl(wide=wide)
        model = ea_tmdl.parse(data)
        md = ea_tmdl.mesh_data(data, model, model.meshes[0])
        assert md.indices.size == 6
        assert md.positions.shape == (4, 3)
        assert md.uvs is not None and md.normals is not None and md.colors is not None
        # both windings cover the same four corners once each
        assert sorted(set(md.indices.tolist())) == [0, 1, 2, 3]


def test_mmap_pack_names_every_texture_and_skips_stale_slots():
    pack = _mmap_pack(["wall", "floor"], stale=2)
    tex = ea_terf.mmap_pack(pack)
    assert [t[0] for t in tex] == ["wall", "floor"]
    assert tuple(tex[0][1][0, 0]) == (0, 0, 255, 255)
    assert tuple(tex[1][1][0, 0]) == (0, 255, 0, 255), "the second level uses the second palette"
    assert any("2 MMAP pack slots" in w for w in tex[0][2])
    unnamed = bytearray(pack)
    struct.pack_into(">I", unnamed, 0x20, 0)  # no name block: a plain MMAP, level 0 only
    single = ea_terf.mmap_pack(bytes(unnamed))
    assert len(single) == 1 and single[0][0] == ""


def test_plugin_binds_texture_by_material_name():
    data = _tmdl(textures=["wall", "floor"])
    assert plugin.detect("STADATA.DAT/0092.tmdl", data[:64], len(data))
    (scene,) = plugin.extract(data, "STADATA.DAT/0092.tmdl", None)
    assert scene.name == "cube"
    assert set(scene.textures) == {"wall", "floor"}
    assert scene.materials[0].texture == "wall"
    assert len(scene.primitives) == 1 and scene.primitives[0].indices.size == 6


def test_plugin_skips_geometry_less_files():
    data = bytearray(_tmdl())
    struct.pack_into(">6I", data, 0x60, 0, 0, 0, 0, 0, 0)
    assert plugin.extract(bytes(data), "x.tmdl", None) == []


def test_truncated_tables_raise():
    data = bytearray(_tmdl())
    struct.pack_into(">I", data, 0x60, len(data))  # mesh table past the end
    with pytest.raises(ea_tmdl.TmdlError):
        ea_tmdl.parse(bytes(data))
