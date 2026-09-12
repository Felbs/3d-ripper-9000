"""n64rip levels: scene and room headers, mesh headers, collision, the tables in code.

Synthetic fixtures encode the layouts; the tests marked ``rom`` run the decoder over the real
cartridge when it is present and assert the whole-game census that a 34-agent investigation
established and this decoder reproduced to the triangle.  Every figure below was measured,
not quoted.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

from n64rip import collision, level

ROM = Path(os.environ.get("N64RIP_OOT_ROM", "")) if os.environ.get("N64RIP_OOT_ROM") else None
_FALLBACK = Path(r"C:/Users/emane/AppData/Local/Temp/claude/Z--3d-ripper/"
                 r"edbdc273-f8f2-4975-b5df-bb6e79cb36f0/scratchpad/n64/collectors_zle_f.n64")
if ROM is None and _FALLBACK.exists():
    ROM = _FALLBACK
rom_only = pytest.mark.skipif(ROM is None or not ROM.exists(), reason="needs the Ocarina ROM")


def _cmd(op: int, arg: int = 0, w1: int = 0) -> bytes:
    return struct.pack(">II", (op << 24) | (arg << 16), w1)


# -- the header language ------------------------------------------------------------------


def test_header_stops_at_0x14_and_skips_unknown_opcodes():
    """The game's executor tests 0x14 before dispatch and skips any opcode at or above 0x1A."""
    data = _cmd(0x16, 0, 3) + _cmd(0x1B, 0, 0xDEAD) + _cmd(0x0A, 0, 0x03000040) + _cmd(0x14)
    cmds = level.commands(data)
    assert [c.op for c in cmds] == [0x16, 0x0A]
    assert cmds[1].segment == 3 and cmds[1].offset == 0x40


def test_a_header_without_a_terminator_is_not_a_header():
    with pytest.raises(ValueError):
        level.commands(bytes(64 * 8))


def test_alternate_header_walk_skips_null_slots():
    """27 of 32 scenes put their first real alternate in slot 3 behind three NULLs.

    A walk that stops at the first non-pointer sees zero alternates for those scenes - and
    then reports "no differences" from an empty loop.
    """
    hdr = _cmd(0x18, 0, 0x02000020) + _cmd(0x04, 1, 0x02000100) + _cmd(0x14)
    data = bytearray(0x200)
    data[0:len(hdr)] = hdr
    # the array at 0x20: NULL NULL NULL ptr sentinel
    struct.pack_into(">5I", data, 0x20, 0, 0, 0, 0x02000080, 0x0000FFEE)
    alt = _cmd(0x04, 1, 0x02000100) + _cmd(0x14)
    data[0x80:0x80 + len(alt)] = alt
    got = level.alternate_headers(bytes(data), level.commands(bytes(data)), 2)
    assert got == [0x80]


# -- mesh headers -------------------------------------------------------------------------


def test_mesh_header_pointers_are_at_plus_4_and_plus_8():
    """``{u8 type; u8 count; u16 PAD; u32 start; u32 end}`` - a spec that forgets the pad
    reads 10 bytes and produces hundreds of bogus stride failures."""
    room = bytearray(0x100)
    struct.pack_into(">BBHII", room, 0xC0, 0, 1, 0, 0x030000CC, 0x030000D4)
    struct.pack_into(">II", room, 0xCC, 0x03002CD8, 0x03004060)   # file 1038's own entry
    m = level.mesh_header(bytes(room), 0xC0)
    assert m.kind == 0 and m.entries == [(0x03002CD8, 0x03004060)]


def test_type_2_entries_carry_a_cull_sphere_before_the_lists():
    room = bytearray(0x300)
    struct.pack_into(">BBHII", room, 0x210, 2, 1, 0, 0x0300021C, 0x0300022C)
    # file 1007 entry 0: centre (-59,-790,80) radius 415, opa 0x03006D28, xlu 0
    room[0x21C:0x22C] = bytes.fromhex("ffc5fcea0050019f03006d2800000000")
    m = level.mesh_header(bytes(room), 0x210)
    assert m.kind == 2
    assert m.spheres == [(-59, -790, 80, 415)]
    assert m.entries == [(0x03006D28, 0)]


def test_type_2_span_must_match_count_times_16():
    room = bytearray(0x300)
    struct.pack_into(">BBHII", room, 0x210, 2, 2, 0, 0x0300021C, 0x0300022C)  # 1 entry's span
    with pytest.raises(ValueError):
        level.mesh_header(bytes(room), 0x210)


def test_type_1_has_one_extra_indirection_and_a_format_byte():
    """The word at +4 points at an {opa, xlu} RECORD, not at a display list; byte +1 is the
    background format, not a count.  Getting the first wrong executes JPEG bytes as commands."""
    room = bytearray(0x3000)
    # file 1304's head, verbatim
    room[0xA0:0xBC] = bytes.fromhex("01010000030000c00300248000000000000000000140" "00f0" "00020000")
    struct.pack_into(">II", room, 0xC0, 0x030023A8, 0)
    room[0x2480:0x248A] = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    room[0x2500:0x2502] = b"\xff\xd9"
    m = level.mesh_header(bytes(room), 0xA0)
    assert m.kind == 1
    assert m.entries == [(0x030023A8, 0)]
    assert len(m.backgrounds) == 1
    bg = m.backgrounds[0]
    assert (bg.width, bg.height, bg.fmt, bg.siz) == (320, 240, 0, 2)
    assert bg.jpeg is not None and bg.jpeg[:4] == b"\xff\xd8\xff\xe0" and bg.jpeg[-2:] == b"\xff\xd9"


# -- collision ----------------------------------------------------------------------------


def _scene_with_collision() -> bytes:
    """Scene 1006's real header bytes, over a synthetic body that satisfies them in miniature."""
    data = bytearray(0x400)
    # camData at 0x100 (1 entry), surface types 0x108 (2), polys 0x118 (2), verts 0x138 (4)
    struct.pack_into(">HhI", data, 0x100, 0x12, 0, 0)
    struct.pack_into(">II", data, 0x108, 0x00000002, 0)     # type 0: bgCam 2
    struct.pack_into(">II", data, 0x110, 0x00000103, 0)     # type 1: bgCam 3, exit 1
    verts = [(0, 0, 0), (100, 0, 0), (0, 0, 100), (100, 0, 100)]
    for i, v in enumerate(verts):
        struct.pack_into(">3h", data, 0x138 + i * 6, *v)
    # two floor polys, normal +Y, plane y = 0
    struct.pack_into(">4H3hh", data, 0x118, 0, 0 | 0xE000, 2 | 0x2000, 1, 0, 0x7FFF, 0, 0)
    struct.pack_into(">4H3hh", data, 0x128, 1, 1, 2, 3, 0, 0x7FFF, 0, 0)
    hdr = struct.pack(">6hHHIHHIIIhHI", 0, 0, 0, 100, 0, 100, 4, 0, 0x02000138, 2, 0,
                      0x02000118, 0x02000108, 0x02000100, 0, 0, 0)
    data[0x200:0x200 + len(hdr)] = hdr
    return bytes(data)


def test_collision_header_layout_and_index_masks():
    c = collision.parse(_scene_with_collision(), 0x200, 2)
    assert len(c.vertices) == 4 and len(c.polygons) == 2
    # the vertex index is the low 13 bits; the flags above it are kept separately
    assert c.polygons[0].tolist() == [0, 2, 1]
    assert c.poly_flags[0].tolist() == [7, 1, 0]
    assert len(c.surface_types) == 2, "count comes from the gap, which is stored nowhere"
    assert c.bg_cam_index(1) == 3 and c.exit_index(1) == 1
    assert c.water_boxes == [] and len(c.cam_data) == 1
    assert collision.winding_agrees(c) == 2
    assert collision.plane_residual(c) == 0.0


def test_water_box_pointer_may_be_null():
    """74 of 101 scenes have no water and a NULL pointer; an assert that all five pointers are
    segmented fires on 73% of the game."""
    c = collision.parse(_scene_with_collision(), 0x200, 2)
    assert c.offsets["water_boxes"] == -1


def test_collision_rejects_a_polygon_list_that_does_not_end_at_the_vertices():
    data = bytearray(_scene_with_collision())
    struct.pack_into(">H", data, 0x200 + 0x14, 3)  # claim three polygons
    with pytest.raises(ValueError):
        collision.parse(bytes(data), 0x200, 2)


# -- tables in code -----------------------------------------------------------------------


def test_entrance_table_trims_the_zero_padding_before_it():
    """Eight zero bytes sit between gObjectTable's end and the first record, and a zero
    record passes the shape test (scene 0, spawn 0).  The real entrance 0 is 00 00 41 02."""
    code = bytearray(0x100)
    # a fake last object-table entry that fails the test, then 8 zero bytes, then 3 records
    struct.pack_into(">II", code, 0x40, 0x01F01000, 0x01F0EA10)
    struct.pack_into(">bbH", code, 0x50, 0, 0, 0x4102)
    struct.pack_into(">bbH", code, 0x54, 85, 1, 0x4183)
    struct.pack_into(">bbH", code, 0x58, 17, 0, 0x8102)
    off, count = level.find_entrance_table(bytes(code), 0x5C, floor=0x48)
    assert (off, count) == (0x50, 3)
    assert level.entrance(bytes(code), off, count, 1) == (85, 1)


# -- the real cartridge -------------------------------------------------------------------


@pytest.fixture(scope="module")
def oot():
    from n64rip import objects as O
    from n64rip.rom import Rom

    rom = Rom.open(str(ROM))
    tbl = O.find_object_table(rom)
    code = rom.read(rom.files[tbl.file_index])
    return rom, tbl, code


@rom_only
def test_the_scene_table_is_found_structurally(oot):
    rom, tbl, code = oot
    off, entries = level.find_scene_table(rom, code)
    assert off == 0xE9B00 and len(entries) == 101
    e0 = entries[0]
    assert (e0.scene_file, e0.title_file, e0.draw_config) == (1006, 884, 0x13)
    assert code[off:off + 0x14] == bytes.fromhex("01f0100001f0ea100198300001984b0001130200")
    assert sum(1 for e in entries if e.title_file is not None) == 65
    assert len({e.title_file for e in entries if e.title_file is not None}) == 57
    assert entries[81].title_file == 905 and entries[91].title_file == 914  # Lost Woods; 921 is Ganon's Castle


@rom_only
def test_the_entrance_table_is_flat_and_bounded_by_its_neighbours(oot):
    rom, tbl, code = oot
    off, entries = level.find_scene_table(rom, code)
    eoff, count = level.find_entrance_table(code, off, floor=tbl.offset + 8 * len(tbl.entries))
    assert (eoff, count) == (0xE82B0, 1556)
    # scene 1006's two exits, 521 and 1039, are the two places the Deku Tree leads to
    assert level.entrance(code, eoff, count, 521) == (85, 1)
    assert level.entrance(code, eoff, count, 1039) == (17, 0)
    assert code[eoff:eoff + 4] == bytes.fromhex("00004102")
    # ids the game stores as immediates, mod 4 = 3, 3, 2 - it is not groups of four
    assert level.entrance(code, eoff, count, 0x53)[0] == 67
    assert level.entrance(code, eoff, count, 0x517)[0] == 79
    assert level.entrance(code, eoff, count, 0x11E)[0] == 91


@rom_only
def test_scene_1006_decodes_to_its_documented_bytes(oot):
    rom, tbl, code = oot
    _off, entries = level.find_scene_table(rom, code)
    scene = rom.read(rom.files[1006])
    ops = level.by_op(level.commands(scene))
    assert scene[0x20:0x28] == bytes.fromhex("0300000002 00b610".replace(" ", ""))
    c = collision.parse(scene, ops[0x03].offset, 2)
    assert (len(c.vertices), len(c.polygons), len(c.water_boxes)) == (1399, 2321, 3)
    assert c.offsets["vertices"] == 0x9514 and c.offsets["polygons"] == 0x404
    assert c.bounds_declared == ((-2788, -1960, -2928), (494, 1160, 1714))
    assert scene[0x404:0x414] == bytes.fromhex("00000166016701685a820000a57e027a")
    assert c.polygons[0].tolist() == [358, 359, 360]
    assert c.normals[0].tolist() == pytest.approx([23170 / 0x7FFF, 0, -23170 / 0x7FFF])
    assert int(c.dist[0]) == 634
    assert scene[0xB5E0:0xB5F0] == bytes.fromhex("fdfdfc81fdbb027b047500000000 7f09".replace(" ", ""))
    lvl, sc = level.decode(rom, tbl, code, entries[0])
    assert len(lvl.rooms) == 12 and sum(r.triangles for r in lvl.rooms) == 4516
    assert lvl.entrances == [(0, 0), (1, 9)] and lvl.exits == [521, 1039]
    assert len(lvl.doors) == 12 and len(lvl.lights) == 7 and lvl.keep == 3
    assert lvl.doors[0].actor_id == 0x2E and lvl.doors[0].pos == (-455, 400, 455)
    assert lvl.lights[0].ambient == (0x43, 0x2D, 0x28) and lvl.lights[0].fog_near == 980
    assert lvl.lights[0].z_far == 4000 and lvl.lights[0].light1_dir == (0, 73, 103)
    # the export shape: a node per room plus the collision, no empty main mesh
    assert {p.group for p in sc.primitives} == {f"room_{k:02d}" for k in range(12)} | {"collision"}
    assert len(sc.empties) == sum(len(r.actors) for r in lvl.rooms) + 2 + 12


@rom_only
def test_room_1007s_actor_and_object_lists(oot):
    rom, tbl, code = oot
    room = rom.read(rom.files[1007])
    assert room[0x30:0x38] == bytes.fromhex("011b000003000058")
    ops = level.by_op(level.commands(room))
    acts = level.actor_entries(room, ops[0x01].offset, ops[0x01].count)
    assert len(acts) == 27
    assert (acts[0].id, acts[0].pos, acts[0].rot[1]) == (0x95, (283, 478, 357), -23666)
    assert acts[3].id == 0x37 and acts[3].pos == (-67, 1069, 255) and acts[3].params == 1
    assert room[0x28:0x30] == bytes.fromhex("0b0b000003000040")
    objs = struct.unpack_from(">11H", room, ops[0x0B].offset)
    assert objs == (0x36, 0x1E, 0x24, 0x39, 0x164, 0x0E, 0xA4, 0x12B, 0xB7, 0xBB, 0x15C)


@rom_only
def test_the_whole_game_census(oot):
    """The figures a 34-agent investigation established, reproduced by this decoder."""
    rom, tbl, code = oot
    _off, entries = level.find_scene_table(rom, code)
    rooms = tris = a_main = a_alt = doors = spawns = lights = bgs = 0
    cv = cp = cs = cw = 0
    kinds: dict[int, int] = {}
    outside = []
    for e in entries:
        lvl, sc = level.decode(rom, tbl, code, e)
        rooms += len(lvl.rooms)
        tris += sum(r.triangles for r in lvl.rooms)
        a_main += sum(len(r.actors) for r in lvl.rooms)
        a_alt += sum(len(a) for r in lvl.rooms for a in r.alt_actors)
        doors += len(lvl.doors)
        spawns += len(lvl.spawns)
        lights += len(lvl.lights)
        bgs += len(lvl.backgrounds)
        for r in lvl.rooms:
            kinds[r.mesh_kind] = kinds.get(r.mesh_kind, 0) + 1
        c = lvl.collision
        assert c is not None, e.index
        cv += len(c.vertices); cp += len(c.polygons); cs += len(c.surface_types)
        cw += len(c.water_boxes)
        assert collision.winding_agrees(c) == len(c.polygons)
        assert collision.plane_residual(c) < 1.5
        pos = [p.positions for p in sc.primitives if p.group and p.group.startswith("room_")]
        if pos:
            allp = np.concatenate(pos) / 0.01
            lo, hi = allp.min(0), allp.max(0)
            dlo, dhi = c.bounds_declared
            if not all(lo[k] >= dlo[k] - 100 and hi[k] <= dhi[k] + 100 for k in range(3)):
                outside.append(e.index)
    assert rooms == 388 and tris == 164228
    assert kinds == {0: 157, 1: 28, 2: 203}
    assert (a_main, a_alt) == (4295, 2734)
    assert (doors, spawns, lights, bgs) == (389, 376, 573, 35)
    assert (cv, cp, cs, cw) == (63262, 87215, 2046, 120)
    # Before the unresolved-G_MTX fix scene 2 (file 1037) reached Y 2257 against a ceiling of
    # 607 and X 2588 against 1971; after it, every scene's rooms sit inside the declared
    # collision box to within 100 units.
    assert outside == []


# -- dyna-poly collision in object files -------------------------------------------------


def test_object_607s_collision_header_parses_from_its_documented_bytes():
    """The same 0x2C struct as a scene's, at segment 6, water boxes NULL."""
    from n64rip import collision

    hdr = bytes.fromhex("fe700000fe7001904e200190000800000600009000080000060000100600000806000000"
                        "0000000000000000")
    data = bytearray(0x100)
    data[0xC0:0xC0 + len(hdr)] = hdr
    # one surface type at 0x08, eight polygons at 0x10, eight vertices at 0x90 (as in the file)
    struct.pack_into(">II", data, 0x08, 0, 0)
    # the first three sit on the x = +400 face, so a +X normal with dist -400 is their plane
    verts = [(400, 0, -400), (400, 0, 400), (400, 20000, 400), (400, 20000, -400),
             (-400, 0, -400), (-400, 0, 400), (-400, 20000, 400), (-400, 20000, -400)]
    for i, v in enumerate(verts):
        struct.pack_into(">3h", data, 0x90 + i * 6, *v)
    # poly 0 as documented: type 0, verts (0,1,2) with flag bit 13 on vA, normal +X, dist -400
    data[0x10:0x20] = bytes.fromhex("000020000001000 27fff00000000fe70".replace(" ", ""))
    for k in range(1, 8):
        struct.pack_into(">4H3hh", data, 0x10 + 16 * k, 0, 0, 1, 2, 0x7FFF, 0, 0, -400)
    c = collision.parse(bytes(data), 0xC0, 6)
    assert (len(c.vertices), len(c.polygons), len(c.surface_types)) == (8, 8, 1)
    assert c.bounds_declared == ((-400, 0, -400), (400, 20000, 400))
    assert c.polygons[0].tolist() == [0, 1, 2] and c.poly_flags[0].tolist() == [1, 0, 0]
    assert int(c.dist[0]) == -400 and c.offsets["water_boxes"] == -1
    assert collision.find_headers(bytes(data), 6) == [0xC0]


@rom_only
def test_the_dyna_poly_census(oot):
    from n64rip import collision, static

    rom, tbl, code = oot
    d = rom.read(rom.files[607])
    assert d[0xC0:0xEC] == bytes.fromhex(
        "fe700000fe7001904e200190000800000600009000080000060000100600000806000000"
        "0000000000000000")
    c = collision.parse(d, 0xC0, 6)
    assert (len(c.vertices), len(c.polygons)) == (8, 8) and collision.plane_residual(c) < 0.1
    c = collision.parse(rom.read(rom.files[583]), 0x54B8, 6)
    assert (len(c.vertices), len(c.polygons)) == (185, 201)
    obj_of = {}
    for oid, fi in enumerate(tbl.entries):
        if fi is not None:
            obj_of.setdefault(fi, oid)
    headers = files = polys = 0
    top = {}
    for fi in sorted(tbl.object_files):
        f = rom.files[fi]
        if f.size < 0x40:
            continue
        data = rom.read(f)
        hs = collision.find_headers(data, static.home_segment(obj_of.get(fi)))
        if hs:
            files += 1
            headers += len(hs)
            polys += sum(len(collision.parse(data, h, static.home_segment(obj_of.get(fi))).polygons) for h in hs)
            top[fi] = len(hs)
    assert headers >= 200 and files >= 74 and polys >= 6_100
    assert top[596] >= 20 and top[536] >= 20 and top[580] >= 11
    # a scene's own header is on segment 2 - scanned as an object it yields nothing
    assert collision.find_headers(rom.read(rom.files[1006]), 6) == []
