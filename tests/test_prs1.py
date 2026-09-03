"""Hudson PRS1 (Okumura LZSS with absolute ring positions), the RenderWare platform-independent
texture dictionary, and the hfs container plugin that joins them."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import frogger_hfs as hfs
from gcrip.formats import prs1, rw_pitxd
from gcrip.plugins import frogger_hfs as plugin


def encode(plain: bytes) -> bytes:
    """Reference LZSS encoder: greedy matches against the same 4 KiB ring, absolute positions."""
    ring = bytearray(prs1.RING)
    r = prs1.RING_START
    out = bytearray()
    i = 0
    flags = 0
    nflag = 0
    block = bytearray()

    def flush():
        nonlocal flags, nflag, block
        if nflag:
            out.append(flags)
            out.extend(block)
        flags = 0
        nflag = 0
        block = bytearray()

    while i < len(plain):
        best_n, best_pos = 0, 0
        if i >= 1:
            for pos in range(prs1.RING):
                n = 0
                # the decoder writes as it copies, so a match must not run into the bytes
                # it is about to overwrite
                while n < 18 and i + n < len(plain) and ring[(pos + n) & 0xFFF] == plain[i + n]:
                    if (pos + n - r) & 0xFFF < 18:
                        break
                    n += 1
                if n > best_n:
                    best_n, best_pos = n, pos
        if best_n >= 3:
            block += bytes([best_pos & 0xFF, ((best_pos >> 4) & 0xF0) | (best_n - 3)])
            for k in range(best_n):
                ring[r] = plain[i + k]
                r = (r + 1) & 0xFFF
            i += best_n
        else:
            flags |= 1 << nflag
            block.append(plain[i])
            ring[r] = plain[i]
            r = (r + 1) & 0xFFF
            i += 1
        nflag += 1
        if nflag == 8:
            flush()
    flush()
    return bytes(out)


def member(plain: bytes) -> bytes:
    packed = encode(plain)
    return prs1.MAGIC + struct.pack("<2I", len(plain), len(packed)) + packed


def test_literals_and_ring_copies_round_trip():
    plain = b"RenderWare " * 20 + bytes(range(200)) + b"\0" * 300 + b"RenderWare "
    m = member(plain)
    assert len(m) < len(plain)
    assert prs1.unpack(m) == plain


def test_zero_ring_lets_the_first_bytes_be_copied():
    # a copy from the untouched (zero) part of the ring, before any literal
    stream = bytes([0x00, 0x00, 0x0F])  # flag 0: copy pos 0, length 18
    assert prs1.decode(stream, 18) == bytes(18)


def test_short_stream_raises():
    with pytest.raises(prs1.Prs1Error):
        prs1.unpack(prs1.MAGIC + struct.pack("<2I", 100, 3) + b"\x07abc")


def _chunk(t: int, body: bytes, lib: int = 0x1803FFFF) -> bytes:
    return struct.pack("<3I", t, len(body), lib) + body


def _string(s: str) -> bytes:
    raw = s.encode() + b"\0"
    raw += b"\0" * (-len(raw) % 4)
    return _chunk(0x02, raw)


def _pitxd(names: list[str], w: int = 4, h: int = 2) -> bytes:
    body = struct.pack("<HH", len(names), 1)
    for i, name in enumerate(names):
        pixels = bytes((k + i) % 2 for k in range(w * h))
        pal = bytearray(256 * 4)
        pal[0:4] = (10, 20, 30, 255)
        pal[4:8] = (200, 100, 0, 128)
        image = _chunk(0x18, _chunk(0x01, struct.pack("<4I", w, h, 8, w)) + pixels + bytes(pal))
        tex = _chunk(0x06, _chunk(0x01, struct.pack("<I", 0x1106)) + _string(name) + _string(""))
        body += struct.pack("<I", 1) + image + tex
    return _chunk(rw_pitxd.PITEXDICT, body)


def test_pi_texture_dictionary_decodes_paletted_images():
    blob = _pitxd(["skin", "eye"])
    assert rw_pitxd.is_pitxd(blob[:64], len(blob))
    assert rw_pitxd.names(blob) == ["skin", "eye"]
    tex = rw_pitxd.parse(blob)
    assert tex[0].image.shape == (2, 4, 4)
    assert tuple(tex[0].image[0, 0]) == (10, 20, 30, 255)
    assert tuple(tex[0].image[0, 1]) == (200, 100, 0, 128)
    assert tuple(tex[1].image[0, 0]) == (200, 100, 0, 128), "the second texture starts on entry 1"


def _archive(members: list[bytes]) -> bytes:
    data_at = hfs.BLOCK
    block = bytearray(hfs.BLOCK)
    body = bytearray()
    for k, m in enumerate(members):
        struct.pack_into("<2I", block, hfs.HEADER + k * hfs.ENTRY, (len(body) // hfs.SECTOR) | hfs.SECTOR_FLAG, len(m))
        body += m + b"\0" * (-len(m) % hfs.SECTOR)
    struct.pack_into("<4s3I", block, 0, hfs.MAGIC, len(body), len(members), data_at)
    return bytes(block + body)


def test_container_decodes_members_and_splits_renderware_chunks():
    clump = _chunk(0x10, _chunk(0x01, struct.pack("<3I", 1, 0, 0)))
    world = _chunk(0x0B, _chunk(0x01, bytes(16)))
    txd = _pitxd(["skin"])
    stream = txd + _chunk(0x29, _string("locator1")) + clump + _chunk(0x2A, b"") + world
    audio = _chunk(0x809, bytes(32), 0x1C02002D)
    arc = _archive([member(stream), audio, member(b"not renderware at all" * 3)])
    assert plugin.is_container("gamedata.bin", arc[:64])
    out = plugin.expand(arc)
    assert [n for n, _ in out] == ["00_0000_0.txd", "00_0000_1_locator1.dff", "00_0000_2.bsp"]
    assert dict(out)["00_0000_1_locator1.dff"] == clump
    assert dict(out)["00_0000_0.txd"] == txd


def test_the_rescue_version_byte_is_an_hfs_too():
    arc = bytearray(_archive([member(b"x" * 40)]))
    arc[3] = 7
    assert hfs.is_hfs(bytes(arc[:16]))
    assert len(hfs.members(bytes(arc))) == 1
