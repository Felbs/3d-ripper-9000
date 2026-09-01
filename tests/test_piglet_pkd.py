"""Piglet's PIGGCN.pkd - a zlib chain whose RenderWare assets span blocks."""

import struct
import zlib

from gcrip.formats import piglet_pkd
from gcrip.plugins import piglet_pkd as plugin

LIB = 0x1003FFFF


def rw_chunk(kind: int, payload: bytes) -> bytes:
    return struct.pack("<3I", kind, len(payload), LIB) + payload


def blocks(*chunks: bytes, block: int = 64) -> bytes:
    """Compress a logical image as a chain of independent zlib streams, splitting it on
    `block` boundaries so an asset spans several - which is what the real file does."""
    image = b"".join(chunks)
    out = b""
    for at in range(0, len(image), block):
        out += zlib.compress(image[at : at + block])
    return out


def test_the_chain_covers_the_archive_exactly():
    data = blocks(rw_chunk(0x10, bytes(200)))
    got = piglet_pkd.inflate(data)
    assert got is not None
    image, starts = got
    assert len(image) == 212 and len(starts) > 1  # it really did split into several blocks
    # a trailing byte is not a zlib stream, so the covering identity fails
    assert piglet_pkd.inflate(data + b"\0") is None


def test_an_asset_spanning_blocks_is_recovered_whole():
    """Read a block alone and the chunk declares more than it holds; that cost 21 of 23 clumps
    on the real archive until the blocks were concatenated."""
    payload = bytes(range(256)) * 3
    data = blocks(rw_chunk(0x10, payload))
    image, starts = piglet_pkd.inflate(data)
    (asset,) = piglet_pkd.assets(image, starts)
    assert asset.kind == 0x10
    assert asset.size == 12 + len(payload)
    assert image[asset.offset : asset.offset + asset.size] == rw_chunk(0x10, payload)


def test_several_assets_are_found_at_their_block_starts():
    a, b = rw_chunk(0x10, bytes(128)), rw_chunk(0x16, bytes(64))
    # each asset begins on a block boundary, which is how they are located
    data = zlib.compress(a) + zlib.compress(b)
    image, starts = piglet_pkd.inflate(data)
    found = piglet_pkd.assets(image, starts)
    assert [f.kind for f in found] == [0x10, 0x16]
    assert [f.size for f in found] == [len(a), len(b)]


def test_a_block_that_is_not_a_renderware_chunk_is_skipped():
    """3,089 blocks are `XMD` property text and 162 are `DSBH`; neither is a chunk."""
    data = zlib.compress(b"XMD\0" + bytes(64)) + zlib.compress(rw_chunk(0x10, bytes(64)))
    image, starts = piglet_pkd.inflate(data)
    found = piglet_pkd.assets(image, starts)
    assert len(found) == 1 and found[0].kind == 0x10


def test_a_chunk_that_overruns_the_image_is_not_claimed():
    """The size field is the only thing saying how long an asset is, so a value past the end
    has to be rejected rather than clamped."""
    bad = struct.pack("<3I", 0x10, 1 << 20, LIB) + bytes(32)
    image, starts = piglet_pkd.inflate(zlib.compress(bad))
    assert piglet_pkd.assets(image, starts) == []


def test_the_container_names_members_by_kind():
    data = zlib.compress(rw_chunk(0x10, bytes(64))) + zlib.compress(rw_chunk(0x16, bytes(64)))
    names = [n for n, _ in plugin.expand(data)]
    assert names == ["00000.dff", "00001.txd"]


def test_something_that_is_not_a_zlib_chain_is_declined():
    assert not plugin.is_container("PIGGCN.pkd", b"NOTZLIB!")
    assert plugin.expand(b"NOTZLIB!" * 8) == []
