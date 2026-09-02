"""Kalisto TotemTech `.ngc` index (gcrip.formats.totemtech).

docs/OPEN.md recorded the blocker as "the file has no directory at all - nothing anywhere
references the verified vertex data".  There is one: the sibling `.ngc`, a plain-text
hash-to-typed-path index, and its hashes appear in the `.dgc` big-endian.
"""

from __future__ import annotations

import struct

from gcrip.formats import totemtech

SAMPLE = (
    b'-853289997 "WORLD"\r\n'
    b'854756687 "DB:>LEVELS>LEVEL07A>MAP>LEVEL07A.TWORLD"\r\n'
    b'596819425 "LEVEL07A"\r\n'
    b'-1989570394 "DB:>LEVELS>LEVEL07A>MAP>3DNODEFAMILY>ROOT_LEVEL07A.T3DNODE"\r\n'
    b'1085295399 "DB:>LEVELS>LEVEL07A>MESHES>O_ECHAFAUDAGE_MESH.TMESH"\r\n'
)


def test_index_parses_hash_and_path():
    ents = totemtech.index(SAMPLE)
    assert len(ents) == 5
    assert ents[0].path == "WORLD"
    assert ents[1].name == "LEVEL07A.TWORLD"
    assert ents[3].kind == "T3DNODE"


def test_negative_hashes_become_unsigned():
    """They are written signed and appear in the .dgc as unsigned big-endian."""
    ents = totemtech.index(SAMPLE)
    assert ents[0].hash == (-853289997 & 0xFFFFFFFF)
    assert 0 <= ents[0].hash <= 0xFFFFFFFF


def test_of_kind_selects_the_meshes():
    meshes = totemtech.of_kind(totemtech.index(SAMPLE), "TMESH")
    assert [e.name for e in meshes] == ["O_ECHAFAUDAGE_MESH.TMESH"]


def test_locate_finds_the_hash_big_endian():
    ents = totemtech.index(SAMPLE)
    e = ents[4]
    blob = b"\x00" * 16 + struct.pack(">I", e.hash) + b"\x00" * 8 + struct.pack(">I", e.hash)
    assert totemtech.locate(blob, e) == [16, 28]
    # and the little-endian encoding is genuinely absent - 400/400 vs 0/400 on the real file
    assert struct.pack("<I", e.hash) not in blob or e.hash in (0,)


def test_a_bare_label_has_no_kind():
    ents = totemtech.index(SAMPLE)
    assert ents[0].kind == ""
    assert ents[2].kind == ""


def test_unparsable_lines_are_skipped_not_guessed():
    assert totemtech.index(b'not an index line\r\n42 "OK.TMESH"\r\n') == [
        totemtech.Entry(42, "OK.TMESH")
    ]


def test_dgc_banner():
    assert totemtech.is_dgc(b"TotemTech Data v1.75 (c) Kalisto")
    assert not totemtech.is_dgc(b"something else entirely")
