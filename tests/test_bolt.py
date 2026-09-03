"""Mass Media BOLT archives: the directory and the prefix-byte LZ, written from MMI::Decompress."""

from __future__ import annotations

import struct

import pytest

from gcrip.formats import bolt
from gcrip.plugins import bolt as plugin


def _lit(data: bytes) -> bytes:
    assert 1 <= len(data) <= 16
    return bytes([0x80 | (len(data) - 1)]) + data


def _copy(length: int, offset: int) -> bytes:
    """A copy of ``length`` bytes from ``offset`` back, using prefix bytes when needed."""
    assert length >= 2 and offset >= 1
    out = b""
    prefixes = 0
    hi_len = (length - 2) >> 3
    hi_off = (offset - 1) >> 4
    if hi_len or hi_off:
        out += bytes([0xA0 | (hi_len & 0x1F)])
        prefixes += 1
        if hi_off:
            out += bytes([0xC0 | (hi_off & 0x3F)])
            prefixes += 1
    length -= prefixes
    lo_len = (length - 2) & 7
    assert (length - 2) >> 3 == hi_len
    return out + bytes([(lo_len << 4) | ((offset - 1) & 0x0F)])


def test_literals_and_short_copies():
    plain = b"muppets " + b"muppets " + b"muppets "
    stream = _lit(b"muppets ") + _copy(16, 8)
    assert bolt.decompress(stream, len(plain)) == plain


def test_prefix_bytes_widen_length_and_offset():
    head = bytes(range(200))
    plain = head + head[:60]
    stream = _lit(head[:16]) + _lit(head[16:32]) + _lit(head[32:48]) + _lit(head[48:64])
    stream += _lit(head[64:80]) + _lit(head[80:96]) + _lit(head[96:112]) + _lit(head[112:128])
    stream += (
        _lit(head[128:144])
        + _lit(head[144:160])
        + _lit(head[160:176])
        + _lit(head[176:192])
        + _lit(head[192:200])
    )
    stream += _copy(60, 200)
    assert bolt.decompress(stream, len(plain)) == plain


def test_long_literal_runs_take_a_length_prefix():
    plain = bytes(range(40))
    # 0xa0 prefix: len = 2 -> literal count = (2 << 4) + (b & 15) + 1 = 40 with b & 15 == 7
    stream = bytes([0xA0 | 2, 0x80 | 7]) + plain
    assert bolt.decompress(stream, 40) == plain


def test_short_stream_and_bad_copy_raise():
    with pytest.raises(bolt.BoltError):
        bolt.decompress(_lit(b"ab"), 10)
    with pytest.raises(bolt.BoltError):
        bolt.decompress(_copy(3, 5), 3)


def _archive(members: list[tuple[int, bytes, bytes | None]], groups: int = 1) -> bytes:
    """(kind, plain, packed-or-None) -> a BOLT file; None stores the member raw (flag 0x08).
    ``groups`` > 1 splits the members over that many groups, the last one taking the rest."""
    head = bytearray(16)
    head[:4] = bolt.MAGIC
    head[11] = groups
    per = max(1, len(members) // groups)
    split = [members[i * per : (i + 1) * per] for i in range(groups - 1)]
    split.append(members[(groups - 1) * per :])
    group_table = bytearray()
    tables = bytearray()
    body = bytearray()
    tables_at = 16 + groups * bolt.ENTRY
    data_at = tables_at + bolt.ENTRY * len(members)
    for chunk in split:
        group_table += struct.pack(">BBBBIII", 0, 0, 0, len(chunk), 0, tables_at + len(tables), 0)
        for kind, plain, packed in chunk:
            blob = packed if packed is not None else plain
            tables += struct.pack(
                ">BBBBIII",
                bolt.PACKED if packed is not None else bolt.STORED,
                0,
                0,
                kind,
                len(plain),
                data_at + len(body),
                0x1234,
            )
            body += blob
    out = head + group_table + tables + body
    struct.pack_into(">I", out, 12, len(out))
    return bytes(out)


def test_archive_members_and_container_plugin():
    plain = b"model data " * 4
    packed = _lit(b"model data ") + _copy(33, 11)
    arc = _archive(
        [(0x0B, plain, packed), (0x03, b"raw!", None), (0x0B, b"second group", None)], groups=2
    )
    ms = bolt.members(arc)
    assert [(m.group, m.slot, m.kind, m.size, bool(m.flags & bolt.STORED)) for m in ms] == [
        (0, 0, 0x0B, len(plain), False),
        (1, 0, 3, 4, True),
        (1, 1, 0x0B, 12, True),
    ]
    assert bolt.unpack(arc, ms[0]) == plain and bolt.unpack(arc, ms[1]) == b"raw!"
    assert plugin.is_container("BMG00.BLT", arc[:64])
    assert plugin.expand(arc) == [
        ("g00_0000_t0b.bin", plain),
        ("g01_0000_t03.bin", b"raw!"),
        ("g01_0001_t0b.bin", b"second group"),
    ]
