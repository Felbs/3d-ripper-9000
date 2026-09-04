"""EA SHOC chunk archives - the .hog on the four Tiger Woods PGA Tour discs."""

import struct
import zlib

from gcrip.formats import shoc
from gcrip.plugins import shoc as plugin


def chunk(tag, payload):
    return tag + struct.pack(">I", 8 + len(payload)) + payload


def wrap(inner):
    return chunk(shoc.SHOC, bytes(8) + inner)


def shdr(kind, index, unpacked, version=1):
    return wrap(shoc.SHDR + struct.pack(">I4s2I", version, kind, index, unpacked))


def build(kind=b"ter ", index=7, body=b"terrain bytes" * 4, compress=True, pad=b""):
    payload = zlib.compress(body) if compress else pad + body
    tag = shoc.ZDAT if compress else b"SDAT"
    return (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(kind, index, len(body))
        + wrap(chunk(tag, payload))
    )


def test_a_member_is_an_shdr_plus_the_data_that_follows():
    (m,) = shoc.members(build())
    assert (m.kind, m.index) == ("ter", 7)
    assert m.data == b"terrain bytes" * 4


def test_the_declared_unpacked_size_is_what_confirms_the_pairing():
    """A member that decompresses to the wrong size is dropped, not reported."""
    data = build()
    at = data.index(shoc.SHDR)
    bad = bytearray(data)
    struct.pack_into(">I", bad, at + 16, 999)
    assert shoc.members(bytes(bad)) == []


def test_raw_members_carry_a_forty_byte_prefix():
    """2003, 2004 and 2005 store SDAT rather than zlib, and the payload runs 40 bytes long."""
    body = b"raw" * 20
    data = build(body=body, compress=False, pad=bytes(shoc.RAW_PREFIX))
    (m,) = shoc.members(data)
    assert m.data == body


def test_a_member_spanning_several_data_chunks_is_joined():
    """txf members reach 1.3 MB across many continuation chunks - one chunk each would
    truncate every one of them.  (06 continues a zlib stream with more Zdat chunks; an Rdat
    chunk is a separately packed block, see test_ea_rcmp.)"""
    body = b"abcdefgh" * 64
    packed = zlib.compress(body)
    half = len(packed) // 2
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"txf ", 3, len(body))
        + wrap(chunk(shoc.ZDAT, packed[:half]))
        + wrap(chunk(shoc.ZDAT, packed[half:]))
    )
    (m,) = shoc.members(data)
    assert m.data == body


def test_a_second_shdr_closes_the_first_member():
    data = build() + shdr(b"sfx ", 1, 4) + wrap(chunk(shoc.ZDAT, zlib.compress(b"beep")))
    got = shoc.members(data)
    assert [(m.kind, len(m.data)) for m in got] == [("ter", 52), ("sfx", 4)]


def test_detection_is_the_ctrl_magic_not_the_extension():
    assert shoc.is_shoc(build()[:64])
    assert not shoc.is_shoc(b"WART3.00" + bytes(56))
    assert plugin.is_container("hole.hog", build()[:64])


def test_repeated_kind_and_index_do_not_collide():
    data = (
        build(kind=b"sfx ", index=1, body=b"one!")
        + shdr(b"sfx ", 1, 4)
        + wrap(chunk(shoc.ZDAT, zlib.compress(b"two!")))
    )
    assert [n for n, _ in plugin.expand(data)] == ["sfx_1", "sfx_1.1"]


def test_a_bare_fill_pad_does_not_end_the_walk():
    """FILL is usually a sized chunk, but it is also used as a bare four-byte pad, and there
    the next four bytes are another tag rather than a size.  Reading that as a sized chunk
    takes the next tag's letters as its length and ends the walk mid-archive - it stopped
    958,460 bytes into a 3.5 MB file on Tiger Woods 2005, and fixing it took that disc from
    60 members to 953."""
    body = build() + b"FILL" + shdr(b"sfx ", 2, 4) + wrap(chunk(shoc.ZDAT, zlib.compress(b"ping")))
    got = shoc.members(body)
    assert [(m.kind, m.data) for m in got] == [("ter", b"terrain bytes" * 4), ("sfx", b"ping")]


def test_a_sized_fill_chunk_is_still_skipped_by_its_size():
    """Treating every FILL as four bytes breaks the other reading - it took Tiger Woods 06
    from 11 of 12 archives landing exactly to none."""
    pad = chunk(b"FILL", bytes(24))
    body = build() + pad + shdr(b"sfx ", 2, 4) + wrap(chunk(shoc.ZDAT, zlib.compress(b"ping")))
    assert [m.kind for m in shoc.members(body)] == ["ter", "sfx"]


def test_a_payload_shorter_than_declared_and_not_zlib_is_declined():
    """The 731 Rdat chunks in a 2005 hole.hog each follow an 'sfx ' header wanting 812 bytes
    and carry 340 - compressed by something that is not zlib.  Emitting them would produce 731
    members of wrong-sized garbage; declining is what keeps the reader honest."""
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"sfx ", 10, 812)
        + wrap(chunk(b"Rdat", bytes(340)))
    )
    assert shoc.members(data) == []


def test_a_long_run_of_untagged_chunks_between_members_is_not_swallowed():
    """A hole.hog puts hundreds of 8 KB SONO audio chunks between its config members.  They are
    not SHOC wrappers, so they must neither end the walk nor be joined onto the open member."""
    sono = b"".join(chunk(b"SONO", bytes(120)) for _ in range(200))
    body = b"config" * 4
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + sono
        + shdr(b"Cact", 3, len(body))
        + wrap(chunk(b"SDAT", body))
        + sono
    )
    (m,) = shoc.members(data)
    assert (m.kind, m.data) == ("Cact", body)


def test_chunk_header_is_forty_four_bytes():
    """Proven by size identity on Tiger Woods 2005, not by inspection: summing payload - 44 over
    a resource's data chunks reproduces its declared size exactly for RLst (8,548 over 2 chunks)
    and sync (65,536 over 9).  The same sum is 63% of declared for `ter`, which is what says
    `ter` is genuinely compressed rather than simply read wrong."""
    from gcrip.formats import shoc

    assert shoc.CHUNK_HEADER == 44
    # the two identities, as arithmetic
    assert (8636 - 2 * shoc.CHUNK_HEADER) == 8548
    assert (65932 - 9 * shoc.CHUNK_HEADER) == 65536
    # and the one that does NOT reconcile, which is the point
    assert (1724896 - 212 * shoc.CHUNK_HEADER) != 2716800


def test_the_inner_tag_says_how_a_block_is_stored():
    """This is the whole difference between the discs that read and the ones that did not.

    SDAT is stored, Zdat is zlib (Tiger Woods 06), Rdat is EA's own LZ with a u32 uncompressed
    size in front (2003/2004/2005).  The old reader knew the first two and treated Rdat as one
    of them, which is why those three discs produced 57 members totalling 5 KB from a 4.9 MB
    archive.
    """
    from gcrip.formats import shoc

    assert shoc.STORED == b"SDAT"
    assert shoc.ZLIB == b"Zdat"
    assert shoc.EALZ == b"Rdat"
    assert set(shoc.DATA) == {shoc.STORED, shoc.ZLIB, shoc.EALZ, shoc.LDAT}


def test_a_zlib_block_reports_an_unknown_size_rather_than_a_wrong_one():
    """deflate does not record its output size, so a Zdat resource is not evidence either way -
    counting its compressed length as its unpacked length would fail the identity for a reason
    that has nothing to do with the format being read wrong."""
    from gcrip.formats import shoc

    zlib_block = shoc.Block(shoc.ZLIB, 0, 100, shoc.UNKNOWN)
    stored = shoc.Block(shoc.STORED, 0, 50, 50)
    assert not shoc.Resource("x", 0, 50, [zlib_block, stored]).sizes_known
    assert not shoc.Resource("x", 0, 50, [zlib_block, stored]).reconciles
    assert shoc.Resource("x", 0, 50, [stored]).reconciles


def test_a_stored_block_is_its_own_payload():
    from gcrip.formats import shoc

    b = shoc.Block(shoc.STORED, 64, 8128, 8128)
    assert b.stored and b.unpacked == b.size


def test_an_ldat_member_is_a_bare_zlib_stream_behind_a_size_word():
    """The Third Age's data tag: u32 packed size then a zlib stream, with none of the
    44-byte chunk header the other data tags carry."""
    body = b"third age bytes" * 20
    packed = zlib.compress(body)
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"Cobj", 3, len(body))
        + wrap(shoc.LDAT + struct.pack(">I", len(packed)) + packed)
    )
    (m,) = shoc.members(data)
    assert (m.kind, m.index, m.data) == ("Cobj", 3, body)
    (r,) = [r for r in shoc.resources(data) if r.blocks]
    assert r.blocks[0].how == shoc.LDAT and r.blocks[0].unpacked == shoc.UNKNOWN


def test_an_ldat_stream_may_continue_across_chunks_or_start_anew():
    """A resource's chunks are fed to one inflater that is renewed when its stream ends, so
    both a split stream and back-to-back independent streams assemble - 341 of 341 resources
    on The Third Age's e98c02.scg reconcile this way."""
    a, b = b"first stream" * 30, b"second stream" * 30
    za, zb = zlib.compress(a), zlib.compress(b)
    split = len(za) // 2
    parts = [za[:split], za[split:] + zb]  # continuation, then a new stream in the same chunk
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"txfx", 9, len(a) + len(b))
        + b"".join(wrap(shoc.LDAT + struct.pack(">I", len(p)) + p) for p in parts)
    )
    (m,) = shoc.members(data)
    assert m.data == a + b
