"""TMNT: Mutant Melee archive.arc directory + archive.dat blob."""

import struct

from gcrip.formats import melee_arc
from gcrip.plugins import melee as plugin


def make_arc() -> bytes:
    names = b"models\0hero\0logo\0"
    folders = struct.pack("<5I", 0, 0xFFFFFFFF, 0, 0, 0)  # "models"
    files = struct.pack("<5I", 7, 0, 0, 24, (1 << 16) | 0x10)  # hero -> clump
    files += struct.pack("<5I", 12, 0, 24, 128, (2 << 16) | 7)  # logo -> DDS
    head = melee_arc.MAGIC + bytes(melee_arc.HEADER - 8)
    body = folders + names
    names_off = melee_arc.HEADER + 24 + len(folders)
    files_off = names_off + len(names)
    head = bytearray(head + struct.pack("<6I", 0, 1, 2, 0, names_off, files_off) + body + files)
    return bytes(head)


def make_dat() -> bytes:
    clump = struct.pack("<3I", 0x10, 12, 0x1003FFFF) + struct.pack("<3I", 1, 0, 0x1003FFFF)
    return clump + b"DDS " + bytes(124)


def test_entries_and_members():
    arc, dat = make_arc(), make_dat()
    assert melee_arc.is_arc("files/archive.arc", arc[:16])
    es = melee_arc.entries(arc)
    assert [(e.name, e.folder, e.offset, e.size, e.rtype) for e in es] == [
        ("hero", "models", 0, 24, 0x10),
        ("logo", "models", 24, 128, 7),
    ]
    members = melee_arc.members(arc, dat)
    assert [n for n, _ in members] == ["models/hero.dff", "models/logo.dds"]
    assert members[0][1][:4] == b"\x10\x00\x00\x00"


def test_plugin_expands_with_sibling():
    arc, dat = make_arc(), make_dat()
    assert plugin.is_container("files/archive.dat", dat[:16])
    out = plugin.expand_with(dat, "archive.dat", lambda n: arc if n == "archive.arc" else None)
    assert [n for n, _ in out] == ["models/hero.dff", "models/logo.dds"]
    assert plugin.expand_with(dat, "archive.dat", lambda n: None) == []
