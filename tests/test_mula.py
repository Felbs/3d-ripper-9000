"""Cabela's ``MULA`` texture archives (gcrip.formats.mula).

The archives are built here rather than checked in, so the tests exercise the two identities
that identified the format on the real discs: the payloads tile the block exactly, and
``32 + palette + pixel bytes`` equals the entry's size.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from gcrip.formats import mula
from gcrip.plugins import cabelas_arc
from gcrip.plugins import mula as pmula

GCT_HEADER = 32


def make_gct(width: int, height: int, fmt: int, levels: int = 1, pad: int = 2) -> bytes:
    """One payload: `pad` bytes, then the header, then the palette and pixels."""
    from gcrip.formats import gx_texture as gx

    pixels = gx.encoded_size(fmt, width, height)
    pal = mula.PALETTE_BYTES.get(fmt, 0)
    head = bytearray(pad + GCT_HEADER)
    head[pad : pad + 4] = b"GCT "
    struct.pack_into(">3H", head, pad + 4, width, height, fmt)
    head[pad + 12] = levels
    struct.pack_into(">I", head, pad + 16, pixels)
    return bytes(head) + b"\x01" * pal + b"\x02" * pixels


def make_mula(items: list[tuple[str, bytes]]) -> bytes:
    strings = bytearray()
    offsets = []
    for name, _ in items:
        offsets.append(len(strings))
        strings += name.encode("latin-1") + b"\0"
    out = bytearray(b"MULA")
    out += struct.pack("<I", len(items))
    for (_, blob), noff in zip(items, offsets):
        out += struct.pack("<2I", len(blob), noff)
    out += struct.pack("<I", len(strings))
    out += strings
    for _, blob in items:
        out += blob
    return bytes(out)


def test_members_tile_the_block_exactly():
    items = [
        ("TEXTURES\\A.GCT", make_gct(64, 64, 14)),
        ("TEXTURES\\B.GCT", make_gct(32, 32, 9)),
        ("TEXTURES\\C.GCT", make_gct(16, 16, 8)),
    ]
    data = make_mula(items)
    got = mula.members(data)
    assert [m.name for m in got] == [n for n, _ in items]
    assert got[-1].offset + got[-1].size == len(data)


def test_a_truncated_block_yields_nothing():
    """The tiling check is what rejects a block read with the wrong count or string table."""
    data = make_mula([("A.GCT", make_gct(32, 32, 9))])
    assert mula.members(data[:-16]) == []


def test_palette_size_is_by_format():
    """C4 holds 16 entries and C8 holds 256 - the 480-byte difference is what separated them
    on the real discs, where 64 of 200 textures missed by exactly that."""
    assert mula.PALETTE_BYTES[8] == 32
    assert mula.PALETTE_BYTES[9] == 512
    for fmt in (8, 9, 14):
        blob = make_gct(32, 32, fmt)
        tex = mula.texture(blob, "x")
        assert tex is not None, fmt
        assert len(tex.palette) == mula.PALETTE_BYTES.get(fmt, 0)
        assert GCT_HEADER + len(tex.palette) + len(tex.pixels) + 2 == len(blob)


@pytest.mark.parametrize("pad", [0, 2])
def test_the_magic_is_found_at_either_padding(pad):
    """Some archives put `GCT ` at 0 and others at 2; both appear on Dangerous Hunts 2."""
    blob = make_gct(64, 64, 14, pad=pad)
    assert mula.gct_at(blob) == pad
    tex = mula.texture(blob, "x")
    assert tex is not None and tex.width == 64 and tex.fmt == 14


def test_a_size_that_does_not_reconcile_is_dropped():
    blob = bytearray(make_gct(64, 64, 14))
    struct.pack_into(">I", blob, 2 + 16, 999999)  # a wrong pixel count
    assert mula.texture(bytes(blob), "x") is None


def test_plugin_decodes_every_texture():
    items = [
        ("TEXTURES\\LEVELS\\A.GCT", make_gct(64, 64, 14)),
        ("TEXTURES\\B.GCT", make_gct(32, 32, 9)),
    ]
    scenes = pmula.extract(make_mula(items), "block000.mula", None)
    assert len(scenes) == 1
    scene = scenes[0]
    assert set(scene.textures) == {"A.GCT", "B.GCT"}
    assert scene.textures["A.GCT"].shape == (64, 64, 4)
    assert scene.extras["textures_only"] is True
    # every texture must be named by a material or export drops it
    assert {m.texture for m in scene.materials} == set(scene.textures)


def test_arc_container_keeps_only_mula_blocks():
    """data.arc is a chain of zlib streams whose contents differ - navigation data, Lua, and
    texture archives.  Only the archives are worth handing back."""
    archive = make_mula([("A.GCT", make_gct(32, 32, 9))])
    other = b"PathGen 3.2 navigation data, not a texture archive" * 8
    blob = bytearray()
    for payload in (other, archive, other):
        blob += zlib.compress(payload)
        blob += b"\0" * (-len(blob) % cabelas_arc.ALIGN)
    data = bytes(blob)
    assert cabelas_arc.is_container("Data/data.arc", data[:64])
    got = cabelas_arc.expand(data)
    assert len(got) == 1
    assert got[0][1][:4] == b"MULA"


def test_arc_container_declines_a_non_arc_name():
    archive = make_mula([("A.GCT", make_gct(32, 32, 9))])
    data = zlib.compress(archive)
    assert not cabelas_arc.is_container("Data/data.bin", data[:64])
