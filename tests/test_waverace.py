"""Wave Race: Blue Storm offset-table containers on synthetic data."""

from __future__ import annotations

import struct

from gcrip.formats import waverace_pack as wp
from gcrip.plugins import waverace


def _tpl_i8(width: int = 8, height: int = 4) -> bytes:
    head = struct.pack(">III", 0x0020AF30, 1, 0x0C)
    head += struct.pack(">II", 0x14, 0)
    img = struct.pack(">HHIIIIII", height, width, 1, 0x34, 0, 0, 1, 1)
    img += struct.pack(">fBBBB", 0.0, 0, 0, 0, 0)
    return head + img + bytes(range(32))


def _table(members: list[bytes], pad_to: int = 0) -> bytes:
    head_len = max(4 + 4 * len(members), pad_to)
    offs = []
    pos = head_len
    for m in members:
        offs.append(pos)
        pos += len(m)
    out = struct.pack(">I", len(members)) + struct.pack(f">{len(members)}I", *offs)
    out += b"\xcd" * (head_len - len(out))
    return out + b"".join(members)


def test_table_roundtrip_and_nesting():
    inner = _table([b"\x01\x02\x03\x04"])
    data = _table([_tpl_i8(), inner, b"\x00\x00\x00\x08" + b"\0" * 12], pad_to=0x20)
    assert wp.table_offsets(data) is not None
    assert waverace.is_container("Crs00.env", data[:64])
    got = waverace.expand(data)
    assert [n for n, _ in got] == ["000.tpl", "001.pak", "002.bin"]
    assert got[0][1][:4] == b"\x00\x20\xaf\x30"
    nested = waverace.expand(got[1][1])
    assert nested == [("000.bin", b"\x01\x02\x03\x04")]


def test_rejects_non_tables():
    assert not waverace.is_container("Crs00.env", b"\0" * 64)
    assert not waverace.is_container("HudData.bin", _tpl_i8()[:64])
    assert not waverace.is_container("track.adp", _table([b"x"])[:64])
    assert wp.table_offsets(struct.pack(">II", 2, 0x0C) + struct.pack(">I", 0x08)) is None
    assert not waverace.detect("Misc/Jumps.geo", b"\0" * 64, 100)
