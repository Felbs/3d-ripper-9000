"""Byte-swapped DDS texture packs (Home Run King data.afs)."""

import struct

import numpy as np

from gcrip.formats import dds_pack


def dds_file(w: int, h: int, big: bool = True, fourcc: bytes = b"DXT1") -> bytes:
    head = bytearray(dds_pack.HEADER)
    head[:4] = dds_pack.MAGIC
    order = ">I" if big else "<I"
    struct.pack_into(order, head, 4, dds_pack.DDSD_SIZE)
    struct.pack_into(order, head, 8, 0x000A1007)
    struct.pack_into(order, head, 12, h)
    struct.pack_into(order, head, 16, w)
    head[84:88] = fourcc[::-1] if big else fourcc
    from gcrip.formats import gx_texture as gx

    return bytes(head) + bytes(gx.encoded_size(0xE, w, h))


def test_reads_a_big_endian_header_with_a_reversed_fourcc():
    d = dds_file(64, 32)
    e = dds_pack.entries(d)[0]
    assert (e.width, e.height) == (64, 32)
    assert e.fourcc == b"DXT1"  # stored as "1TXD"
    assert e.big_endian
    assert d[84:88] == b"1TXD"
    assert dds_pack.is_pack(d[: dds_pack.HEADER])


def test_little_endian_files_still_work():
    d = dds_file(16, 16, big=False)
    e = dds_pack.entries(d)[0]
    assert (e.width, e.height, e.fourcc, e.big_endian) == (16, 16, b"DXT1", False)


def test_splits_a_run_of_concatenated_files():
    d = dds_file(8, 8) + dds_file(256, 128) + dds_file(64, 128)
    es = dds_pack.entries(d)
    assert [(e.width, e.height) for e in es] == [(8, 8), (256, 128), (64, 128)]
    assert es[1].offset == len(dds_file(8, 8))


def test_a_magic_inside_pixel_data_is_not_a_header():
    d = bytearray(dds_file(64, 64))
    d[dds_pack.HEADER : dds_pack.HEADER + 4] = dds_pack.MAGIC  # magic, but no dwSize == 124
    assert len(dds_pack.entries(bytes(d))) == 1
    assert not dds_pack.is_pack(b"DDS " + bytes(200))
    assert not dds_pack.is_pack(b"nope")


def test_decodes_as_gx_cmpr_not_linear_dxt1():
    """The fourcc says DXT1 but the payload is GX CMPR - GameCube tiling and byte order."""
    from gcrip.formats import gx_texture as gx

    d = dds_file(8, 8)
    e = dds_pack.entries(d)[0]
    rgba = dds_pack.decode(d, e)
    assert rgba.shape == (8, 8, 4)
    assert rgba.dtype == np.uint8
    # the gap to the next file is the CMPR size, which is what identified the format
    assert dds_pack.payload(e) == gx.encoded_size(0xE, 8, 8)
    assert len(d) == dds_pack.HEADER + dds_pack.payload(e)


def test_an_unsupported_fourcc_is_refused():
    import pytest

    d = dds_file(8, 8, fourcc=b"DXT5")
    with pytest.raises(ValueError):
        dds_pack.decode(d, dds_pack.entries(d)[0])


def test_detected_from_the_64_byte_sniff():
    """detect() only ever sees SNIFF_BYTES, and the fourcc sits at 84 - past the end of it."""
    from gcrip.classify import SNIFF_BYTES
    from gcrip.plugins import dds_pack as plugin

    d = dds_file(256, 128)
    assert SNIFF_BYTES < 84
    assert dds_pack.is_pack(d[:SNIFF_BYTES])
    assert plugin.detect("data.afs/m.bin", d[:SNIFF_BYTES], len(d))
    # the full parse still validates everything the short header could not
    assert [(e.width, e.height) for e in dds_pack.entries(d)] == [(256, 128)]
    assert not dds_pack.is_pack(b"DDS " + b"\x00\x00\x00\x7b")  # dwSize is not 124
    assert not dds_pack.is_pack(b"DDS ")
