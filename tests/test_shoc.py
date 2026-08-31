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
    """txf members reach 1.3 MB across many Rdat continuations - one chunk each would
    truncate every one of them."""
    body = b"abcdefgh" * 64
    packed = zlib.compress(body)
    half = len(packed) // 2
    data = (
        shoc.MAGIC
        + struct.pack(">I", 16)
        + bytes(8)
        + shdr(b"txf ", 3, len(body))
        + wrap(chunk(shoc.ZDAT, packed[:half]))
        + wrap(chunk(b"Rdat", packed[half:]))
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
