"""Call of Duty: Finest Hour's sectioned `.rws` (gcrip.formats.cod_rws).

Two different files share the extension on that disc: 299 MB streamed audio, and level geometry
that is ordinary RenderWare behind an 8-byte header.  The walk is what tells them apart, so the
tests check it accounts for the file and refuses the audio.
"""

from __future__ import annotations

import struct

from gcrip.formats import cod_rws

STAMP = 0x1803FFFF


def rw_chunk(ident: int, body: bytes) -> bytes:
    return struct.pack("<3I", ident, len(body), STAMP) + body


def section(kind: int, ident: int, body: bytes) -> bytes:
    chunk = rw_chunk(ident, body)
    return struct.pack("<2I", kind, len(chunk)) + chunk


def sample(pad: int = 4) -> bytes:
    return (
        section(4, cod_rws.TEXDICT, b"\x11" * 64)
        + section(0, cod_rws.WORLD, b"\x22" * 128)
        + section(1, cod_rws.WORLD, b"\x33" * 96)
        + bytes(pad)
    )


def test_the_walk_accounts_for_the_file():
    data = sample()
    got = cod_rws.sections(data)
    assert [s.kind for s in got] == [4, 0, 1]
    assert [s.ident for s in got] == [cod_rws.TEXDICT, cod_rws.WORLD, cod_rws.WORLD]
    assert len(data) - got[-1].end == 4


def test_a_walk_that_leaves_more_than_a_padding_word_returns_nothing():
    """The size identity is what separates these from the streamed audio, so it has to be
    strict about what is left over."""
    assert cod_rws.sections(sample(pad=cod_rws.MAX_PAD + 1)) == []


def test_the_streamed_audio_is_not_claimed():
    """`NGC_2s1.rws` is 299 MB and opens 0x080D, whose size is larger than the file."""
    audio = struct.pack("<3I", 0x080D, 0x11D19FF4, STAMP) + b"\x00" * 256
    assert not cod_rws.is_cod_rws(audio[: cod_rws.HEADER + cod_rws.CHUNK])
    assert cod_rws.sections(audio) == []


def test_a_section_without_a_renderware_stamp_is_refused():
    data = bytearray(sample())
    struct.pack_into("<I", data, cod_rws.HEADER + 8, 0)  # clear the version word
    assert cod_rws.sections(bytes(data)) == []


def test_a_chunk_bigger_than_its_section_is_refused():
    data = bytearray(sample())
    struct.pack_into("<I", data, cod_rws.HEADER + 4, 1 << 20)
    assert cod_rws.sections(bytes(data)) == []


def test_both_identities_hold_and_can_fail():
    from gcrip import identities

    results = {r.identity.name: r for r in identities.check(cod_rws, sample())}
    assert results["the section walk accounts for the file"].held is True
    assert results["every section is a RenderWare chunk"].held is True

    hurt = bytearray(sample())
    struct.pack_into("<I", hurt, 4, len(hurt))  # a section that swallows the file
    broken = {r.identity.name: r for r in identities.check(cod_rws, bytes(hurt))}
    assert broken["the section walk accounts for the file"].held is False


def test_the_container_names_sections_by_their_chunk():
    from gcrip.plugins import cod_rws as plugin

    data = sample()
    assert plugin.is_container("s_1.rws", data[:64])
    names = [n for n, _ in plugin.expand(data)]
    assert names == ["000_4.txd", "001_0.bsp", "002_1.bsp"]
    for name, blob in plugin.expand(data):
        ident = struct.unpack_from("<I", blob, 0)[0]
        assert ident in cod_rws.EXT


def test_the_container_declines_the_audio():
    from gcrip.plugins import cod_rws as plugin

    audio = struct.pack("<3I", 0x080D, 0x11D19FF4, STAMP) + b"\x00" * 256
    assert not plugin.is_container("NGC_2s1.rws", audio[:64])
