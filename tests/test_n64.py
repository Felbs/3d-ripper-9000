"""n64rip: the ROM container, texture formats, skeletons and the F3DEX2 interpreter.

Synthetic fixtures throughout - these must pass without a ROM present.  The facts they
encode were measured against the three Zelda ROMs on the GameCube discs and are cited in
each test, because the expensive mistakes here are the ones that look plausible.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from n64rip import f3dex2, scan, skeleton, texture
from n64rip.rom import DELETED, Rom, RomError, find_dma_table, read_dma_table

# -- the ROM container --------------------------------------------------------


def _entry(vs: int, ve: int, ps: int, pe: int) -> bytes:
    return struct.pack(">4I", vs, ve, ps, pe)


def _rom_with_table(entries: list[tuple[int, int, int, int]], table_at: int = 0x2000) -> bytes:
    size = 0x8000
    buf = bytearray(size)
    buf[0:4] = b"\x80\x37\x12\x40"
    for i, e in enumerate(entries):
        buf[table_at + i * 16 : table_at + (i + 1) * 16] = _entry(*e)
    return bytes(buf)


def test_dma_table_size_comes_from_its_own_entry():
    """Entry #2 describes dmadata itself, so the table states how many slots it has.

    Walking until the entries stop looking plausible undercounts: on the real Ocarina of
    Time such a walk stops at 1,030 of 1,509 files, and on Majora's Mask at 1,158 of 1,549.
    """
    table_at = 0x2000
    slots = 40
    span = slots * 16
    entries = [
        (0, 0x1060, 0, 0),
        (0x1060, table_at, 0x1060, 0),
        (table_at, table_at + span, table_at, 0),  # dmadata describing itself
    ]
    entries += [(0x3000 + i * 0x100, 0x3100 + i * 0x100, 0x3000 + i * 0x100, 0)
                for i in range(slots - 3)]
    data = _rom_with_table(entries, table_at)
    assert find_dma_table(data) == table_at
    files = read_dma_table(data, table_at)
    assert len(files) == slots


def test_deleted_entries_stay_in_the_table():
    """Majora's Mask keeps 17 slots for assets cut from the GameCube release, marked
    promStart == promEnd == 0xFFFFFFFF.  A validity test that demands a real physical
    address rejects those and splits the table in half."""
    table_at = 0x2000
    entries = [
        (0, 0x1060, 0, 0),
        (0x1060, table_at, 0x1060, 0),
        (table_at, table_at + 16 * 14, table_at, 0),  # 14 slots, declared by the table itself
        (0x3000, 0x3100, 0x3000, 0),
        (0x3100, 0x3200, DELETED, DELETED),  # deleted, but the slot is real
        (0x3200, 0x3300, 0x3200, 0),
    ]
    # find_dma_table wants a real run before it believes a candidate; real tables are large
    entries += [(0x3300 + i * 0x100, 0x3400 + i * 0x100, 0x3300 + i * 0x100, 0)
                for i in range(8)]
    data = _rom_with_table(entries, table_at)
    files = read_dma_table(data, find_dma_table(data))
    assert len(files) == len(entries)
    assert files[4].deleted
    assert not files[4].compressed
    assert [f.deleted for f in files].count(True) == 1


def test_rom_rejects_a_non_n64_image():
    with pytest.raises(RomError):
        Rom(b"\x00" * 0x2000)


def test_byteswapped_images_are_normalised():
    """.v64 stores 16-bit words the other way round; the loader should still read it."""
    table_at = 0x2000
    entries = [(0, 0x1060, 0, 0), (0x1060, table_at, 0x1060, 0),
               (table_at, table_at + 16 * 12, table_at, 0)]
    entries += [(0x3000 + i * 0x100, 0x3100 + i * 0x100, 0x3000 + i * 0x100, 0)
                for i in range(9)]
    good = _rom_with_table(entries, table_at)
    swapped = bytearray(good)
    swapped[0::2], swapped[1::2] = good[1::2], good[0::2]
    assert swapped[:4] == b"\x37\x80\x40\x12"
    rom = Rom(bytes(swapped))
    assert rom.dma_offset == table_at


# -- textures -----------------------------------------------------------------


def test_rgba16_decodes_with_one_bit_alpha():
    # 0xF801 = r 31, g 0, b 0, a 1 -> opaque red
    data = struct.pack(">2H", 0xF801, 0x0000)
    out = texture.decode(texture.FMT_RGBA, texture.SIZE_16, 2, 1, data)
    assert out.shape == (1, 2, 4)
    assert tuple(out[0, 0]) == (255, 0, 0, 255)
    assert out[0, 1][3] == 0  # alpha bit clear


def test_ci4_uses_the_tiles_sub_palette():
    """One 256-entry TLUT serves 16 different CI4 textures; the tile's palette field picks
    the 16-entry window.  Ignoring it silently gives every CI4 texture palette 0."""
    tlut_words = [0x0000] * 256
    tlut_words[16] = 0xF801  # first entry of window 1: red
    tlut_words[17] = 0x07C1  # green
    tlut = texture.decode_tlut(struct.pack(">256H", *tlut_words), 256)
    pixels = bytes([0x01])  # two texels: index 0 then index 1
    out = texture.decode(texture.FMT_CI, texture.SIZE_4, 2, 1, pixels, tlut, palette=1)
    assert tuple(out[0, 0]) == (255, 0, 0, 255)
    assert tuple(out[0, 1])[1] > 200  # green


def test_i4_and_ia8_span_the_full_range():
    out = texture.decode(texture.FMT_I, texture.SIZE_4, 2, 1, bytes([0x0F]))
    assert out[0, 0][0] == 0 and out[0, 1][0] == 255
    out = texture.decode(texture.FMT_IA, texture.SIZE_8, 1, 1, bytes([0xF0]))
    assert out[0, 0][0] == 255 and out[0, 0][3] == 0


def test_ci_without_a_palette_is_an_error_not_a_guess():
    with pytest.raises(texture.TextureError):
        texture.decode(texture.FMT_CI, texture.SIZE_8, 2, 1, b"\0\0")


# -- skeletons ----------------------------------------------------------------


def _build_skeleton(limbs: list[tuple[int, int, int, int, int, int]], seg: int = 6) -> bytes:
    """A file holding a skeleton header, its limb pointer table and the limbs."""
    header_at, table_at, limbs_at = 0x00, 0x20, 0x80
    buf = bytearray(0x400)
    struct.pack_into(">IB3x", buf, header_at, (seg << 24) | table_at, len(limbs))
    for i, limb in enumerate(limbs):
        addr = limbs_at + i * 12
        struct.pack_into(">I", buf, table_at + i * 4, (seg << 24) | addr)
        struct.pack_into(">3hBBI", buf, addr, *limb)
    return bytes(buf)


def test_skeleton_hierarchy_and_draw_order():
    # root -> child 1; 1 -> child 2, sibling 3
    data = _build_skeleton([
        (0, 0, 0, 1, skeleton.NO_LIMB, 0),
        (10, 0, 0, 2, 3, 0x06001000),
        (20, 0, 0, skeleton.NO_LIMB, skeleton.NO_LIMB, 0x06002000),
        (-10, 0, 0, skeleton.NO_LIMB, skeleton.NO_LIMB, 0x06003000),
    ])
    sk = skeleton.read_skeleton(data, 0)
    assert sk is not None and sk.count == 4
    # limb 3 is limb 1's sibling, so it shares limb 1's parent rather than descending from it
    assert [limb.parent for limb in sk.limbs] == [None, 0, 1, 0]
    assert sk.order() == [0, 1, 2, 3]  # depth-first: child before sibling


def test_skeleton_detection_rejects_a_bad_limb_index():
    """The header is only 8 bytes, so validity comes from what it points at."""
    data = _build_skeleton([
        (0, 0, 0, 9, skeleton.NO_LIMB, 0),  # child 9 with only 2 limbs
        (10, 0, 0, skeleton.NO_LIMB, skeleton.NO_LIMB, 0),
    ])
    assert skeleton.read_skeleton(data, 0) is None


def test_find_skeletons_ignores_random_bytes():
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 256, 0x4000, dtype=np.uint8).tobytes()
    assert skeleton.find_skeletons(noise) == []


# -- the display-list interpreter ---------------------------------------------


def _cmd(op: int, w0_rest: int, w1: int) -> bytes:
    return struct.pack(">2I", (op << 24) | w0_rest, w1)


def _vertex(x: int, y: int, z: int, u: int = 0, v: int = 0, rgba=(255, 255, 255, 255)) -> bytes:
    return struct.pack(">3hHhh4B", x, y, z, 0, u, v, *rgba)


def test_interpreter_reads_a_triangle():
    verts = _vertex(0, 0, 0) + _vertex(100, 0, 0) + _vertex(0, 100, 0)
    dl = (
        _cmd(f3dex2.G_VTX, (3 << 12) | (3 << 1), 0x06000100)
        + _cmd(f3dex2.G_TRI1, 0, 0)  # slots 0,1,2 (stored doubled)
        + _cmd(f3dex2.G_ENDDL, 0, 0)
    )
    buf = bytearray(0x400)
    buf[0x000 : len(dl)] = dl
    buf[0x100 : 0x100 + len(verts)] = verts
    # G_TRI1 packs each index doubled
    struct.pack_into(">2I", buf, 8, (f3dex2.G_TRI1 << 24) | (0 << 16) | (2 << 8) | 4, 0)
    res = f3dex2.run(0x06000000, f3dex2.Segments({6: bytes(buf)}))
    assert res.triangles == 1
    assert len(res.batches) == 1
    np.testing.assert_allclose(res.batches[0].positions[1], [100, 0, 0], atol=1e-4)


def test_unbound_segment_is_recorded_not_guessed():
    """Segments 8-0F are written by actor code at draw time.  A static rip cannot resolve
    them, and must say so rather than reading whatever happens to be there."""
    dl = _cmd(f3dex2.G_VTX, (3 << 12) | (3 << 1), 0x08000100) + _cmd(f3dex2.G_ENDDL, 0, 0)
    buf = bytearray(0x400)
    buf[0 : len(dl)] = dl
    res = f3dex2.run(0x06000000, f3dex2.Segments({6: bytes(buf)}))
    assert res.unresolved == {8}
    assert res.triangles == 0


def test_lighting_bit_decides_normal_versus_colour():
    """The last four bytes of a vertex are a normal when G_LIGHTING is set and a colour when
    it is not - the same bytes read two ways, decided by state."""
    verts = _vertex(0, 0, 0, rgba=(10, 20, 30, 255)) * 3
    body = (
        _cmd(f3dex2.G_VTX, (3 << 12) | (3 << 1), 0x06000100)
        + _cmd(f3dex2.G_TRI1, (0 << 16) | (2 << 8) | 4, 0)
        + _cmd(f3dex2.G_ENDDL, 0, 0)
    )
    for lighting, expect_normals in ((0, False), (f3dex2.G_LIGHTING, True)):
        buf = bytearray(0x400)
        head = _cmd(f3dex2.G_GEOMETRYMODE, 0xFFFFFF, lighting)
        buf[0 : len(head) + len(body)] = head + body
        buf[0x100 : 0x100 + len(verts)] = verts
        res = f3dex2.run(0x06000000, f3dex2.Segments({6: bytes(buf)}))
        assert res.triangles == 1
        assert (res.batches[0].normals is not None) is expect_normals
        if not expect_normals:
            assert tuple(res.batches[0].colors[0])[:3] == (10, 20, 30)


# -- the display-list scanner -------------------------------------------------


def test_scanner_needs_vertices_and_triangles():
    """A stream that parses but draws nothing is not a display list worth reporting."""
    empty = _cmd(f3dex2.G_ENDDL, 0, 0)
    assert scan.display_lists(empty.ljust(64, b"\0")) == []


def test_scanner_finds_a_real_list_and_not_noise():
    dl = (
        _cmd(f3dex2.G_VTX, (3 << 12) | (3 << 1), 0x06000100)
        + _cmd(f3dex2.G_TRI1, (0 << 16) | (2 << 8) | 4, 0)
        + _cmd(f3dex2.G_ENDDL, 0, 0)
    )
    found = scan.display_lists(dl.ljust(128, b"\0"))
    assert len(found) == 1 and found[0].triangles == 1

    rng = np.random.default_rng(11)
    noise = rng.integers(0, 256, 0x2000, dtype=np.uint8).tobytes()
    assert len(scan.display_lists(noise)) == 0


def test_sibling_cycles_do_not_hang_the_parent_walk():
    """Limb indices come from the ROM, so a candidate that is not really a skeleton can have
    two limbs list each other as siblings.  Following that chain without a guard spins
    forever - it hung a whole-ROM scan before the guard existed."""
    data = _build_skeleton([
        (0, 0, 0, 1, skeleton.NO_LIMB, 0),
        (10, 0, 0, skeleton.NO_LIMB, 2, 0),
        (20, 0, 0, skeleton.NO_LIMB, 1, 0),  # sibling points back at limb 1
    ])
    sk = skeleton.read_skeleton(data, 0)
    assert sk is not None
    assert sk.order()[0] == 0


def test_vertex_colours_export_normalised():
    """glTF multiplies COLOR_0 into the base colour, so it must arrive in 0..1.

    Parsers hand back 0..255 bytes.  Casting those straight to float made every textured
    surface 255x too bright - invisible in the thumbnailer, which ignores vertex colour, and
    blown out in the browser's 3D viewer.
    """
    import json
    import tempfile
    from pathlib import Path

    from ripcore import gltf
    from ripcore.scene import MaterialDef, Primitive, Scene

    scene = Scene(name="c")
    scene.materials = [MaterialDef(name="m", texture=None)]
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    scene.primitives = [
        Primitive(
            material=0,
            positions=pos,
            indices=np.array([0, 1, 2], dtype=np.uint32),
            colors=np.full((3, 4), 255, dtype=np.uint8),
        )
    ]
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "c"
        gltf.export(scene, base, thumbnail=False)
        doc = json.loads(base.with_suffix(".gltf").read_text(encoding="utf-8"))
        acc = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"]]
        # bytes go out as normalized UNSIGNED_BYTE, never as raw floats of 255
        assert acc["componentType"] == 5121
        assert acc.get("normalized") is True
