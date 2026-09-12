"""n64rip.static: the vertex-load gate that finds props in object files with no skeleton."""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from n64rip import f3dex2, static

ROM = Path(os.environ.get("N64RIP_OOT_ROM", "")) if os.environ.get("N64RIP_OOT_ROM") else None
_FALLBACK = Path(r"C:/Users/emane/AppData/Local/Temp/claude/Z--3d-ripper/"
                 r"edbdc273-f8f2-4975-b5df-bb6e79cb36f0/scratchpad/n64/collectors_zle_f.n64")
if ROM is None and _FALLBACK.exists():
    ROM = _FALLBACK
rom_only = pytest.mark.skipif(ROM is None or not ROM.exists(), reason="needs the Ocarina ROM")


def _vertex(x, y, z):
    return struct.pack(">hhhHhhBBBB", x, y, z, 0, 0, 0, 255, 255, 255, 255)


def _file_with_lists() -> bytes:
    """A segment-6 object: vertices at 0x100, a real list at 0x200, a list at 0x300 that loads
    its vertices from segment 8, and a stored pointer to 0x200 at 0x10."""
    data = bytearray(0x400)
    struct.pack_into(">I", data, 0x10, 0x06000200)
    for i, v in enumerate([(0, 0, 0), (100, 0, 0), (0, 100, 0)]):
        data[0x100 + i * 16:0x110 + i * 16] = _vertex(*v)
    real = struct.pack(">II", 0x01003006, 0x06000100) + struct.pack(">II", 0x05000204, 0) \
        + struct.pack(">II", 0xDF000000, 0)
    data[0x200:0x200 + len(real)] = real
    foreign = struct.pack(">II", 0x01003006, 0x08000100) + struct.pack(">II", 0x05000204, 0) \
        + struct.pack(">II", 0xDF000000, 0)
    data[0x300:0x300 + len(foreign)] = foreign
    return bytes(data)


def test_the_gate_keeps_own_segment_loads_and_rejects_foreign_ones():
    data = _file_with_lists()
    segs = f3dex2.Segments({6: data})
    rs = static.roots(data, segs, 6)
    assert [r.offset for r in rs] == [0x200]
    assert rs[0].from_pointer is True and rs[0].triangles == 1
    # the segment-8 list is executable but its vertices are not on the cartridge
    res = f3dex2.run(0x06000300, segs)
    assert res.vtx_segments == {8: 3} and not static._passes(res, 6)


def test_candidates_come_from_pointers_and_the_scan():
    data = _file_with_lists()
    c = static.candidates(data, 6)
    assert c[0x200] is True              # the stored pointer
    assert 0 not in c, "a run of zero words is G_NOOPs, not a list"
    assert 0x100 not in c, "a G_VTX operand names vertex data, and vertex bytes start 0x00"


def test_a_list_called_by_another_kept_list_is_interior_unless_pointed_at():
    """A G_DL operand is a call, not the game naming a list.

    A root made only of G_DL calls draws nothing of its own, so the scan never proposes it -
    the game's tables do, which is why stored pointers are a candidate source at all.
    """
    data = bytearray(_file_with_lists())
    caller = struct.pack(">II", 0xDE000000, 0x06000200) + struct.pack(">II", 0xDF000000, 0)
    data[0x380:0x380 + len(caller)] = caller
    struct.pack_into(">I", data, 0x14, 0x06000380)       # a table names the caller
    # the callee is still named by its own table entry at 0x10: both stay
    rs = static.roots(bytes(data), f3dex2.Segments({6: bytes(data)}), 6)
    assert sorted(r.offset for r in rs) == [0x200] or sorted(r.offset for r in rs) == [0x200, 0x380]
    # remove the callee's own entry: the G_DL operand at 0x384 still names it, but that is a
    # call, so the callee is interior and only the caller remains
    struct.pack_into(">I", data, 0x10, 0)
    rs = static.roots(bytes(data), f3dex2.Segments({6: bytes(data)}), 6)
    assert [r.offset for r in rs] == [0x380]


def test_identical_geometry_is_emitted_once():
    data = bytearray(_file_with_lists())
    dup = bytes(data[0x200:0x218])
    data[0x380:0x398] = dup
    struct.pack_into(">I", data, 0x14, 0x06000380)
    rs = static.roots(bytes(data), f3dex2.Segments({6: bytes(data)}), 6)
    assert len(rs) == 1


def test_the_keep_banks_live_on_segments_4_and_5():
    assert static.home_segment(1) == 4
    assert static.home_segment(2) == 5 and static.home_segment(3) == 5
    assert static.home_segment(233) == 6 and static.home_segment(None) == 6


@pytest.fixture(scope="module")
def oot():
    from n64rip import objects as O
    from n64rip.rom import Rom

    rom = Rom.open(str(ROM))
    tbl = O.find_object_table(rom)
    return rom, tbl


def _roots(rom, tbl, fidx, seg):
    from n64rip import objects as O

    keep = O.keep_segments(rom, tbl, field=True)
    data = rom.read(rom.files[fidx])
    segs = f3dex2.Segments({seg: data, **{k: v for k, v in keep.items() if k != seg}})
    return static.roots(data, segs, seg)


@rom_only
def test_gameplay_keep_yields_nothing_at_segment_6_and_a_bank_at_4(oot):
    rom, tbl = oot
    assert _roots(rom, tbl, 497, 6) == []
    # measured with this gate: 68 roots / 1,093 triangles and 12 / 122.  The investigation's
    # own two pipelines put them at 72 / 1,106 and 14 / 125 - the counts move with candidate
    # and dedup policy, so the floor is set below what any of the three produced.
    rs = _roots(rom, tbl, 497, 4)
    assert len(rs) >= 60 and sum(r.triangles for r in rs) >= 1_000
    rs5 = _roots(rom, tbl, 499, 5)
    assert len(rs5) >= 12 and sum(r.triangles for r in rs5) >= 120


@rom_only
def test_file_570_is_rejected_because_its_vertices_are_not_in_the_file(oot):
    """Offset 0 decodes as a VERTEX (652, 0, 358), not a command, and the lists that do run
    load vertices from 14 different segments."""
    rom, tbl = oot
    data = rom.read(rom.files[570])
    assert data[:16] == bytes.fromhex("028c0000016600 00ffafffb901e675ff".replace(" ", ""))
    assert _roots(rom, tbl, 570, 6) == []


@rom_only
def test_the_false_positive_skeletons_hold_real_geometry(oot):
    from n64rip import skeleton as S

    rom, tbl = oot
    for fidx in (503, 517, 531, 537, 561, 581, 639, 689):
        data = rom.read(rom.files[fidx])
        skels = S.find_skeletons(data)
        assert skels, f"file {fidx} is the false-positive case"
        highs = {(limb.dlist >> 24) for sk in skels for limb in sk.limbs if limb.dlist}
        assert highs <= {0}, f"file {fidx}: limb pointers are raw small integers, not segment 6"
        assert sum(r.triangles for r in _roots(rom, tbl, fidx, 6)) > 0


@rom_only
def test_the_aggregate_lands_in_the_band(oot):
    """Two independent pipelines put the skeleton-free geometry at 18,000-28,500 triangles;
    the numbers move with dedup policy, so the test is on the band and the controls."""
    from n64rip import skeleton as S

    rom, tbl = oot
    total = 0
    for fidx in sorted(tbl.object_files):
        f = rom.files[fidx]
        if f.size < 128:
            continue
        data = rom.read(f)
        if any(sk.count > 1 and all((l.dlist >> 24) == 6 for l in sk.limbs if l.dlist)
               and any(l.dlist for l in sk.limbs) for sk in S.find_skeletons(data)):
            continue  # the skeleton route's files
        oid = next((o for o, fi in enumerate(tbl.entries) if fi == fidx), None)
        total += sum(r.triangles for r in _roots(rom, tbl, fidx, static.home_segment(oid)))
    assert 18_000 <= total <= 28_500, total
