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


def test_object_table_found_by_validating_against_the_dma_table():
    """The object table is an array of {vromStart, vromEnd} pairs in `code`, one per object
    id.  It is findable without any outside data because every pair must name a real DMA
    entry - a long run that all match cannot be coincidence.  Object 1 is gameplay_keep,
    which is the segment-4 bank actors borrow textures from."""
    from n64rip import objects

    table_at = 0x2000
    n_objects = 30
    # above 0x10000: find_object_table ignores low addresses so a field of small
    # integers cannot masquerade as a table
    files = [(0x20000 + i * 0x1000, 0x20800 + i * 0x1000) for i in range(n_objects)]
    entries = [
        (0, 0x1060, 0, 0),
        (0x1060, table_at, 0x1060, 0),
        (table_at, table_at + 16 * (3 + n_objects + 1), table_at, 0),
    ]
    entries += [(vs, ve, vs, 0) for vs, ve in files]
    # the file holding the table ("code") must itself be a ROM file we can read
    code_vs = 0x100000
    code = bytearray(0x40000)  # find_object_table only scans code-sized files
    # real `code` holds instructions either side of the table; without something non-zero
    # there the walk would absorb the zero padding as empty object slots
    code[:0x100] = bytes(range(1, 256)) + b""
    struct.pack_into(">2I", code, 0x100, 0, 0)  # object 0 is the empty slot
    for i, (vs, ve) in enumerate(files):
        struct.pack_into(">2I", code, 0x108 + i * 8, vs, ve)
    entries.append((code_vs, code_vs + len(code), code_vs, 0))

    size = 0x400000
    buf = bytearray(size)
    buf[0:4] = b"\x80\x37\x12\x40"
    for i, e in enumerate(entries):
        buf[table_at + i * 16 : table_at + (i + 1) * 16] = _entry(*e)
    buf[code_vs : code_vs + len(code)] = code

    rom = Rom(bytes(buf))
    table = objects.find_object_table(rom)
    assert table is not None
    assert len(table.entries) == n_objects + 1
    assert table.entries[0] is None  # object 0 is an empty slot and must keep its place:
    # dropping it shifts every id by one, which silently renames gameplay_keep
    # object 1 is the first real object, and keep_segments binds it to segment 4
    assert table.file_for(objects.GAMEPLAY_KEEP) is not None
    seg = objects.keep_segments(rom, table)
    assert set(seg) == {4}


def test_clamp_and_mirror_bits_are_not_swapped():
    """gbi packs the wrap mode as G_TX_MIRROR = 1 (low bit) and G_TX_CLAMP = 2 (high bit).

    Reading bit 8 as clamp and bit 9 as mirror swaps them, so a clamped face tile exports as
    MIRRORED_REPEAT - which paints a second, mirrored pair of eyes along the jaw.
    """
    t = f3dex2.TileState(width=32, height=32, mask_s=5, mask_t=5)
    t.cm_s = 2  # G_TX_CLAMP
    t.cm_t = 1  # G_TX_MIRROR
    assert t.clamp_s and not t.mirror_s
    assert t.mirror_t and not t.clamp_t
    # a tile with no mask has nothing to wrap around, so it clamps whatever the bits say
    bare = f3dex2.TileState(width=16, height=16, mask_s=0, mask_t=0)
    assert bare.clamp_s and bare.clamp_t and not bare.mirror_s


def test_texture_disabled_runs_are_not_textured():
    """G_TEXTURE's enable bit is honoured - an 'off' run must not inherit the live tile -
    but its S/T scale is deliberately NOT applied: every scale-zero command in this ROM is
    gsSPTexture(..., G_OFF), and applying the scale collapses geometry onto one texel."""
    on = f3dex2.TileState(addr=0x06001000, width=8, height=8)
    off = f3dex2.TileState(addr=0x06001000, width=8, height=8, tex_on=False)
    assert on.key() != off.key()

# --------------------------------------------------------------------------- face tables


def test_tile_for_picks_the_squarest_shape():
    """A stride gives a texel count, not a shape; the squarest split is the right one."""
    from n64rip.actor_code import tile_for

    assert tile_for(0x400, 8) == (32, 32)  # 1024 texels, not 64x16
    assert tile_for(0x800, 8) == (64, 32)
    assert tile_for(0x800, 16) == (32, 32)  # RGBA16 is two bytes a texel
    assert tile_for(0x200, 8) == (32, 16)
    assert tile_for(0, 8) is None


def test_delta_groups_splits_eyes_from_mouths():
    """A change of spacing is where one packed table ends and the next begins."""
    from n64rip.actor_code import delta_groups

    # three 0x800 eyes, a jump, then three 0x400 mouths
    run = [0x1000, 0x1800, 0x2000, 0x9000, 0x9400, 0x9800]
    assert delta_groups(run) == [[0x1000, 0x1800, 0x2000], [0x9000, 0x9400, 0x9800]]


def test_texture_tables_offers_the_whole_run_too():
    """Not every table is packed - some actors list scattered offsets, so the run is it."""
    from n64rip.actor_code import texture_tables

    run = [0x100, 0x980, 0x1200, 0x1600]
    assert run in texture_tables(run)


def test_texture_tables_ignores_a_lone_pointer():
    from n64rip.actor_code import texture_tables

    assert texture_tables([0x100], 8) == []


def test_frame_agreement_ranks_variants_over_noise():
    """The discriminator that replaced maximising pixel variance.

    Variance maximisation chose noise, because noise has more of it than any real image.
    Frames of one eye are the same drawing with the lid moved, so they share most of their
    bytes; unrelated data shares about one byte in 256.
    """
    import numpy as np

    from n64rip.extract import MIN_EXPRESSION_CORR, _frame_agreement

    rng = np.random.default_rng(0)
    eye = rng.integers(0, 255, 1024, dtype=np.uint8)
    lid = eye.copy()
    lid[:300] = 7  # same eye, lid lowered over the top third
    data = eye.tobytes() + lid.tobytes()
    assert _frame_agreement(data, [0, 1024], 1024) > MIN_EXPRESSION_CORR

    noise = rng.integers(0, 255, 3072, dtype=np.uint8).tobytes()
    assert _frame_agreement(noise, [0, 1024, 2048], 1024) < MIN_EXPRESSION_CORR


def test_frame_agreement_rejects_flat_and_identical_frames():
    """Padding is one byte repeated; a repeated pointer gives identical frames."""
    import numpy as np

    from n64rip.extract import _frame_agreement

    assert _frame_agreement(bytes(2048), [0, 1024], 1024) == 0.0
    rng = np.random.default_rng(1)
    same = rng.integers(0, 255, 1024, dtype=np.uint8).tobytes()
    assert _frame_agreement(same * 2, [0, 1024], 1024) == 0.0


def test_pixel_correlation_carries_true_colour_faces():
    """RGBA16 eyes are re-shaded rather than copied, so few bytes match but the picture does."""
    import numpy as np

    from n64rip.extract import _pixel_correlation

    rng = np.random.default_rng(2)
    a = rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)
    b = a.copy()
    b[:4] = rng.integers(0, 255, (4, 16, 4), dtype=np.uint8)  # same picture, lid redrawn
    assert _pixel_correlation([a, b]) > 0.45
    assert _pixel_correlation([a, rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)]) < 0.45


def test_actor_overlays_keep_every_actor_sharing_an_object():
    """Several actors can use one object, and only one of them may draw the face."""
    import inspect

    from n64rip.objects import find_actor_overlays

    src = inspect.getsource(find_actor_overlays)
    assert "bucket.append" in src, "must collect every overlay, not just the first"

def test_structure_ratio_sees_through_a_low_contrast_palette():
    """Noise in a narrow palette measures smooth in absolute terms; the ratio does not care.

    This is the gate that stopped an actor shipping twenty-one frames of grey confetti as
    its mouth table.
    """
    import numpy as np

    from n64rip.extract import MAX_STRUCTURE_RATIO, _roughness, _structure_ratio

    rng = np.random.default_rng(3)
    # noise confined to a narrow band of values - absolutely smooth, structurally not
    quiet = rng.integers(120, 140, (32, 32, 4), dtype=np.uint8)
    assert _roughness([quiet]) < 0.20  # the absolute gate is fooled
    assert _structure_ratio([quiet]) > MAX_STRUCTURE_RATIO  # this one is not

    # a drawing: regions, so neighbours agree far more than distant texels do
    art = np.zeros((32, 32, 4), dtype=np.uint8)
    art[:16] = 200
    art[16:] = 40
    assert _structure_ratio([art]) < MAX_STRUCTURE_RATIO

def test_expression_drivers_are_reparsed_after_their_variable_exists():
    """An invalid driver is never evaluated again, so the expression control does nothing.

    `driver_add` evaluates once before the variable is created and flags the driver invalid.
    Clearing the flag by hand does not rebuild the parsed expression - only assigning
    `expression` does - and without that rebuild every faced character imported with a dead
    control: the default face stayed visible at every setting.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "blender" / "gcrip_blender.py"
    src = src.read_text(encoding="utf-8")
    body = src[src.index("def add_expression_controls"):src.index("def set_expression")]
    assert "drv.expression = drv.expression" in body, "the parse must be forced after is_valid"
    # and it has to come after the flag is cleared, or the rebuild is thrown away again
    assert body.index("drv.is_valid = True") < body.index("drv.expression = drv.expression")

def test_face_tlut_prefers_a_palette_from_a_face_tile():
    """The PNGs written beside a model must use the face's palette, not the model's first one.

    `zobj` decodes every tile with that tile's own palette, so the model itself was always
    right; only the exported expression images came out in somebody else's colours - which
    made real eyes look like noise and had several of them rejected as junk.
    """
    import inspect

    from n64rip.extract import _face_tlut

    src = inspect.getsource(_face_tlut)
    assert "EYE_SEGMENT" in src and "MOUTH_SEGMENT" in src, "must prefer a face-segment tile"
    assert "fallback" in src, "and still return something when no face tile resolves"
    assert "prefer_face" in inspect.signature(_face_tlut).parameters

def test_coherent_span_drops_garbage_at_both_ends():
    """A pointer run does not start and end where the eye table does."""
    from n64rip.extract import _coherent_span

    assert _coherent_span([0.01, 0.6, 0.7, 0.6, 0.02, 0.01]) == (1, 4)
    assert _coherent_span([0.7, 0.6, 0.05, 0.01]) == (0, 2)
    assert _coherent_span([0.6, 0.7, 0.6]) == (0, 3)


def test_coherent_span_ends_at_a_frame_unlike_the_others():
    """Junk frames can agree with each other byte for byte, so steps alone do not cut them."""
    from n64rip.extract import _coherent_span

    steps = [0.6, 0.6, 0.6, 0.6, 0.6]          # every neighbour "matches"
    ok = [True, True, True, False, False, False]  # but the last three are not faces
    assert _coherent_span(steps, ok) == (0, 2)


def test_frame_is_face_needs_both_halves_of_the_rule():
    """Relative alone cuts Link's dark open mouth; absolute alone cuts detailed eyes."""
    import numpy as np

    from n64rip.extract import _frame_is_face

    rng = np.random.default_rng(7)
    smooth = np.zeros((32, 32, 4), dtype=np.uint8)
    smooth[:16] = 210
    detailed = smooth.copy()
    detailed[::3] = 120           # busier, but still a drawing
    noise = rng.integers(0, 255, (32, 32, 4), dtype=np.uint8)
    ok = _frame_is_face([smooth, detailed, noise])
    assert ok[0] and ok[2] is False, ok
    assert ok[1], "a more detailed real frame must survive"


def test_trim_table_hands_back_the_tail_it_shed():
    """What the eye table sheds is usually the mouth table, so the caller needs it."""
    import numpy as np

    from n64rip.extract import _trim_table

    rng = np.random.default_rng(5)
    eye = rng.integers(0, 255, 64, dtype=np.uint8)
    frames = [eye, eye.copy(), eye.copy()]
    frames[1][:10] = 3
    frames[2][:20] = 3
    mouth = rng.integers(0, 255, 64, dtype=np.uint8)
    data = b"".join(f.tobytes() for f in frames) + mouth.tobytes() + mouth.tobytes()
    offs = [0, 64, 128, 192, 256]
    head, tail = _trim_table(data, offs, 64, [])
    assert head == [0, 64, 128], head
    assert tail == [192, 256], tail

def test_is_blank_accepts_a_zero_length_object_slot():
    """A zero-length DMA range is an unused slot, not the end of the table.

    Ocarina's slot 227 is {0x015e2000, 0x015e2000}.  The DMA table never yields a zero-length
    file, so that pair can never match a real one - and treating it as the end of the table
    stopped the walk at object 227 and hid the remaining 175 objects, King Zora among them.
    """
    from n64rip.objects import _is_blank

    assert _is_blank(0, 0)
    assert _is_blank(0x015E2000, 0x015E2000)
    assert not _is_blank(0x015E2000, 0x015E4170)
    assert not _is_blank(0, 0x100)

def test_the_head_share_gate_is_retired():
    """It rejected Deku Scrubs, whose eyes really are glowing dots on their own billboards.

    Kept as constants rather than deleted so the reasoning stays with the code: the gate was
    built by looking at 8x8 textures out of context, and the characters it silenced were the
    evidence against it.
    """
    from n64rip.extract import MAX_FACE_SHARE, MIN_HEAD_TRIANGLES

    # a two-triangle limb whose tile is all of it must now pass
    assert not (1.0 > MAX_FACE_SHARE and 2 < MIN_HEAD_TRIANGLES)


def test_expression_variants_are_not_in_the_default_scene():
    """A plain glTF viewer draws every node in the scene, so alternates must stay out of it.

    Listed in the scene, all nine of a character's expressions render coincident and z-fight -
    which is what made a whole cast look like their eyes were shut in the library preview and
    in the thumbnails.  Blender still imports a scene-less node (into an "Orphan Nodes"
    collection in the same scene), so the add-on still finds them.
    """
    import json
    import pathlib
    import tempfile

    import numpy as np

    from ripcore import gltf
    from ripcore.scene import MaterialDef, Primitive, Scene

    tri = dict(
        positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        indices=np.array([0, 1, 2], np.uint32),
    )
    sc = Scene(name="who")
    sc.materials = [MaterialDef("body", None), MaterialDef("face", None),
                    MaterialDef("face_expr1", None)]
    sc.primitives = [
        Primitive(material=0, **tri),
        Primitive(material=1, **tri),
        Primitive(material=2, variant_of="face", variant_texture="expr_01", **tri),
    ]
    out = pathlib.Path(tempfile.mkdtemp()) / "who"
    gltf.export(sc, out, thumbnail=False)
    g = json.loads(out.with_suffix(".gltf").read_text(encoding="utf-8"))

    names = {i: n.get("name") for i, n in enumerate(g["nodes"])}
    in_scene = {names[i] for i in g["scenes"][0]["nodes"]}
    assert "face@expr_01" not in in_scene, "the alternate must not be drawn by default"
    assert "face" in in_scene, "but the default face must be"
    # it still has to exist as a node, or Blender has nothing to import
    assert "face@expr_01" in set(names.values())
    variant = next(n for n in g["nodes"] if n.get("name") == "face@expr_01")
    assert variant["extras"]["gcrip_variant_of"] == "face"

def test_mirrored_batches_are_one_feature_not_two():
    """Two segments drawing the same tile at mirrored centroids are the left and right eye.

    Measured on this ROM: (255.2, 611.8, -162.0) against (255.2, 611.2, +162.0), same tile,
    same x-span.  Binding only one of them leaves the character blank on one side; treating
    the second as a mouth paints a mouth where the right eye belongs.
    """
    import numpy as np

    from n64rip.extract import _mirrored

    spec = (2, 1, 32, 32)
    left = (8, spec, np.array([255.2, 611.8, -162.0]), 518.0, 4, 120)
    right = (9, spec, np.array([255.2, 611.2, 162.0]), 518.0, 4, 120)
    assert _mirrored(left, right)

    # an eye and a mouth: same side of the head, different height and span
    mouth = (9, (2, 1, 32, 16), np.array([-120.1, 670.3, -4.3]), 307.0, 5, 120)
    eye = (8, spec, np.array([213.4, 702.4, -4.7]), 433.0, 6, 120)
    assert not _mirrored(eye, mouth)

    # same tile but both centred - Link's two features share a spec on some actors
    a = (8, spec, np.array([333.3, 666.6, 0.0]), 497.0, 6, 84)
    b = (9, spec, np.array([48.3, 600.5, 0.0]), 309.0, 5, 84)
    assert not _mirrored(a, b)


def test_face_segments_include_0x0a():
    """Some heads put the mouth on segment 0x0A and never sample 9 at all."""
    from n64rip.face import FACE_SEGMENTS

    assert set(FACE_SEGMENTS) == {8, 9, 10}


def test_segments_for_binds_every_segment_playing_a_part():
    """A head drawing two eyes through two segments needs the frame on both."""
    from n64rip.face import FaceSet, segments_for

    obj = bytes(range(256)) * 4
    faces = FaceSet(eyes=[0x10], mouths=[0x40], eye_segments=(8, 9), mouth_segments=(10,))
    bound = segments_for(faces, obj)
    assert set(bound) == {8, 9, 10}
    assert bound[8] is not None and bound[8] == bound[9], "both eyes share one frame"
    assert bound[10] != bound[8]

def test_named_characters_reach_the_library_path():
    """The object id always leads; the English name follows it when we have one."""
    from n64rip.publish import _display_path

    rep = {"code": "N64_CZLE"}
    assert _display_path(rep, {"object_id": 255, "name": "file_0731"}) ==         "N64_CZLE/obj_255_king_zora_file_0731"
    # an unidentified object keeps the id alone - which is always correct
    assert _display_path(rep, {"object_id": 99, "name": "file_0600"}) ==         "N64_CZLE/obj_099_file_0600"
    # and a model outside the object table keeps its file name
    assert _display_path(rep, {"object_id": None, "name": "file_0900"}) == "N64_CZLE/file_0900"


def test_names_are_path_safe():
    """They end up in a path, so they must not carry spaces or separators."""
    import re

    from n64rip.names import OOT

    for oid, nm in OOT.items():
        assert re.fullmatch(r"[a-z0-9_]+", nm), (oid, nm)

def test_attested_tables_short_circuit_the_search():
    """The few actors no rule reaches take their offsets from data, not from a heuristic.

    The frames that were beating the right ones on these files are real artwork, not noise -
    object 357's wrong frames measure smoother than several correct ones - so no threshold
    separates them and the search has to be bypassed rather than tuned.
    """
    from n64rip import attested
    from n64rip.extract import _attested_faces

    att = attested.for_object(357)
    assert att and "eyes" in att
    faces = _attested_faces(att, (8,), ())
    assert faces.eyes == [0x3928, 0x3D28, 0x4128]
    assert faces.eye_size == (32, 32)
    assert faces.eye_segments == (8,)
    assert attested.for_object(None) == {}
    assert attested.for_object(20) == {}, "Link is found by rule and must not be attested"


def test_every_attested_row_records_what_was_seen():
    """These are claims about pictures, so each has to say what the picture was."""
    from n64rip.attested import NOTES, OOT

    for oid, tables in OOT.items():
        assert oid in NOTES, f"object {oid} must say why a rule could not reach it"
        for role, tb in tables.items():
            assert len(tb.seen) > 20, f"object {oid} {role} must describe what was seen"
            assert len(tb.offsets) >= 2
            assert tb.width > 0 and tb.height > 0

def _mips(*words):
    import struct

    return b"".join(struct.pack(">I", w) for w in words)


def _lui(rt, imm):
    return 0x3C000000 | (rt << 16) | (imm & 0xFFFF)


def _ori(rt, rs, imm):
    return 0x34000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _addiu(rt, rs, imm):
    return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _sw(rt, off, base):
    return 0xAC000000 | (base << 21) | (rt << 16) | (off & 0xFFFF)


def _lw(rt, off, base):
    return 0x8C000000 | (base << 21) | (rt << 16) | (off & 0xFFFF)


def _and(rd, rs, rt):
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x24


def _addu(rd, rs, rt):
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x21


V0, A0, A3, T0, T4, T5, T6, T7, T9 = 2, 4, 7, 8, 12, 13, 14, 15, 25


def test_gsp_segments_reads_a_direct_binding_through_segmented_to_virtual():
    """gSPSegment(gfx, 8, SEGMENTED_TO_VIRTUAL(0x06001300)) as the compiler emits it.

    The stored address is derived from the segmented constant through `and` and two `addu`;
    the first attempt dropped the constant at the `and` and found nothing in any actor.
    """
    import pytest

    pytest.importorskip("capstone")
    from n64rip.actor_code import gsp_segments

    code = _mips(
        _lui(A3, 0x00FF), _ori(A3, A3, 0xFFFF),      # 0x00FFFFFF mask
        _lui(T0, 0x8000),                            # + 0x80000000
        _lui(A0, 0x0600), _addiu(A0, A0, 0x1300),    # the segmented address
        _lui(T9, 0xDB06), _ori(T9, T9, 0x20),        # gSPSegment command for segment 8
        _sw(T9, 0, V0),                              # gfx->words.w0
        _lw(T5, 0, T4),                              # gSegments[seg] (unknown base)
        _and(T6, A0, A3),                            # offset
        _addu(T7, T5, T6), _addu(T7, T7, T0),        # virtual address
        _sw(T7, 4, V0),                              # gfx->words.w1
    )
    got = gsp_segments(code, 0x80A00000, 0x4000)
    assert got.get(8) == [0x1300], got


def test_gsp_segments_reads_a_table_binding():
    """The common shape: the address is loaded from an array the code names by VRAM address."""
    import pytest

    pytest.importorskip("capstone")
    from n64rip.actor_code import gsp_segments

    base = 0x80A00000
    table_off = 0x40
    code_words = [
        _lui(T9, 0xDB06), _ori(T9, T9, 0x24),        # segment 9
        _sw(T9, 0, V0),
        _lui(T4, (base + table_off) >> 16),
        _addiu(T4, T4, (base + table_off) & 0xFFFF),
        _lw(A0, 0, T4),                              # sEyeTextures[0]
        _sw(A0, 4, V0),
    ]
    code = _mips(*code_words)
    code += b"\0" * (table_off - len(code))
    code += _mips(0x06001000, 0x06001400, 0x06001800, 0x00000000)
    got = gsp_segments(code, base, 0x4000)
    assert got.get(9) == [0x1000, 0x1400, 0x1800], got


def test_gsp_segments_pairs_the_two_stores_not_the_nearest_address():
    """With two calls interleaved, the +4 store nearest by distance can belong to the previous
    call - which assigned every pointer one segment late on the first actor tried."""
    import pytest

    pytest.importorskip("capstone")
    from n64rip.actor_code import gsp_segments

    code = _mips(
        _lui(A0, 0x0600), _addiu(A0, A0, 0x1300),
        _lui(T9, 0xDB06), _ori(T9, T9, 0x20), _sw(T9, 0, V0),     # cmd 8
        _sw(A0, 4, V0),                                           # addr 8
        _addiu(V0, V0, 8),
        _lui(A0, 0x0600), _addiu(A0, A0, 0x1700),
        _lui(T9, 0xDB06), _ori(T9, T9, 0x24), _sw(T9, 0, V0),     # cmd 9
        _sw(A0, 4, V0),                                           # addr 9
    )
    got = gsp_segments(code, 0x80A00000, 0x4000)
    assert got.get(8) == [0x1300] and got.get(9) == [0x1700], got


def test_unclaimed_objects_consult_the_runtime_pool_by_code_only():
    """An object no actor claims is attributed by asking the pool's code, never by shape."""
    import inspect

    from n64rip import extract

    src = inspect.getsource(extract._attribute_from_pool)
    assert "gsp_segments" in src
    assert "texture_runs" not in src, "the pool must never be searched by pointer shape"
    body = inspect.getsource(extract._overlay_faces)
    assert "if not own and pool:" in body


def _bne(rs, rt, off_words):
    return 0x14000000 | (rs << 21) | (rt << 16) | (off_words & 0xFFFF)


def test_attachments_reads_a_post_limb_draw():
    """PostLimbDraw: if (limbIndex == 15) gSPDisplayList(hairTable[this->hairType]).

    The Gerudo's ponytail.  The list is not in the limb table; the actor draws it under the
    head's matrix, and the compiler folds the table's low half into the load's displacement,
    so the base register points outside the overlay while the load lands inside it.
    """
    import pytest

    pytest.importorskip("capstone")
    from n64rip.actor_code import attachments

    AT, A1, T0, T7, T8, T9 = 1, 5, 8, 15, 24, 25
    # the table sits just below the next 64 K page, as it does in the Gerudo's overlay, so
    # the compiler reaches it with lui of that page and a negative displacement
    base = 0x80A1C000
    table_off = 0x80
    words = [
        _addiu(AT, 0, 15),            # limbIndex == 15
        _bne(A1, AT, 20),             # skip if not
        _lui(T7, 0xDE00),             # gSPDisplayList command
        _lui(T0, (base + 0x10000) >> 16),   # lui of a HIGHER page than the table
        _sw(T7, 0, V0),
        _lw(T8, 0x29E, A3),           # this->hairType (unknown base -> index)
        (T8 << 16) | (T9 << 11) | (2 << 6) | 0x00,   # sll $t9, $t8, 2
        _addu(T0, T0, T9),
        _lw(T0, (base + table_off) - ((base + 0x10000) & 0xFFFF0000), T0),   # negative displacement folds it back
        _sw(T0, 4, V0),
    ]
    code = _mips(*words)
    code += b"\0" * (table_off - len(code))
    code += _mips(0x06009198, 0x06009430, 0x06009690, 0)
    got = attachments(code, base, 0x10000)
    assert got == [(14, [0x9198, 0x9430, 0x9690])], got


def test_attachments_ignores_a_list_with_no_limb_guard():
    """A list emitted with no limbIndex compare is drawn under the actor's own matrix, whose
    pose is not known here - so it is left alone rather than placed at the wrong joint."""
    import pytest

    pytest.importorskip("capstone")
    from n64rip.actor_code import attachments

    code = _mips(
        _lui(T9, 0xDE00), _sw(T9, 0, V0),
        _lui(A0, 0x0600), _addiu(A0, A0, 0x1300), _sw(A0, 4, V0),
    )
    assert attachments(code, 0x80A00000, 0x4000) == []

def test_pose_quality_keeps_the_standing_gate_in_charge():
    """Where the original gate fires it decides, unchanged - it has posed a hundred models."""
    from n64rip.extract import _pose_quality

    # Link: 45.9 x 23.3 x 21.8 un-posed becomes 33.4 x 62.2 x 21.2
    stands, _better = _pose_quality([45.9, 23.3, 21.8], [33.4, 62.2, 21.2])
    assert stands


def test_pose_quality_fallback_wants_three_dimensions_without_inflation():
    """For creatures the standing gate cannot speak for: less degenerate, and no bigger."""
    from n64rip.extract import _pose_quality

    # a Tektite: flat and splayed un-posed, three-dimensional posed, and no longer
    stands, better = _pose_quality([67, 17, 30], [66, 30, 59])
    assert not stands and better

    # a pose that merely inflates the model is not a rest pose
    _s, better = _pose_quality([67, 17, 30], [140, 60, 90])
    assert not better

    # and neither is one that changes nothing
    _s, better = _pose_quality([148, 60, 86], [148, 60, 86])
    assert not better


def test_every_animation_is_tried():
    """The rest pose is often not among the first few - object 359's is its eighth."""
    from n64rip.extract import MAX_POSE_ANIMS

    assert MAX_POSE_ANIMS >= 32
