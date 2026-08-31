"""TOC .wad archives and their TIM textures - Spawn: Armageddon."""

import struct

from gcrip.formats import gx_texture as gx
from gcrip.formats import toc_tim, toc_wad
from gcrip.plugins import toc_tim as tim_plugin
from gcrip.plugins import toc_wad as plugin

ENTRIES = (("GLOBALSFX", "SFX", b"sound bank bytes"), ("SPAWNTEYE", "TIM", None))


def tim(width=8, height=8, fmt=0xE, levels=1):
    size = gx.encoded_size(fmt, width, height)
    head = struct.pack(">I4HI", levels, fmt, width, height, 0x20, size)
    return head + bytes(size)


def build(entries=ENTRIES):
    payloads = [(n, k, (b if b is not None else tim())) for n, k, b in entries]
    table = b""
    body = b""
    start = toc_wad.HEADER + len(payloads) * toc_wad.ENTRY
    for name, kind, blob in payloads:
        offset = start + len(body)
        table += name.encode().ljust(toc_wad.NAME, b"\0")
        table += kind.encode().ljust(toc_wad.TYPE, b"\0")
        table += struct.pack(">3I", offset, len(blob), 0)
        body += blob
        body += bytes(-len(body) % 32)
    head = bytearray(toc_wad.HEADER)
    head[toc_wad.MAGIC_AT : toc_wad.MAGIC_AT + 4] = toc_wad.MAGIC
    struct.pack_into(">2I", head, 20, len(payloads) * toc_wad.ENTRY, len(payloads))
    return bytes(head) + table + body


def test_the_table_size_must_be_the_count_times_the_stride():
    data = build()
    assert toc_wad.is_toc_wad(data[:64])
    bad = bytearray(data)
    struct.pack_into(">I", bad, 20, 999)
    assert not toc_wad.is_toc_wad(bytes(bad)[:64])


def test_the_leading_sixteen_bytes_must_be_zero():
    """The Scorpion King's .wad open with their own name instead, and are a different
    layout - claiming them here would produce nonsense."""
    data = bytearray(build())
    data[0] = ord("L")
    assert not toc_wad.is_toc_wad(bytes(data)[:64])


def test_members_come_out_named_and_typed():
    got = dict(plugin.expand(build()))
    assert set(got) == {"GLOBALSFX.SFX", "SPAWNTEYE.TIM"}
    assert got["GLOBALSFX.SFX"] == b"sound bank bytes"


def test_the_tim_format_word_is_a_real_gx_code():
    got = toc_tim.header(tim(fmt=0xE))
    assert got is not None and got.format == 0xE and (got.width, got.height) == (8, 8)


def test_a_tim_whose_size_does_not_match_the_format_is_refused():
    """size == encoded_size(format, w, h) is what confirms the header, not just getting a
    picture out of it."""
    data = bytearray(tim())
    struct.pack_into(">I", data, 12, 999)
    assert toc_tim.header(bytes(data)) is None


def test_tim_plugin_returns_a_textures_only_scene():
    blob = tim(width=16, height=16)
    assert tim_plugin.detect("SPAWNTEYE.TIM", blob[:64], len(blob))
    assert not tim_plugin.detect("GLOBALSFX.SFX", blob[:64], len(blob))
    (scene,) = tim_plugin.extract(blob, "global.wad/SPAWNTEYE.TIM", None)
    assert scene.extras["textures_only"] and set(scene.textures) == {"SPAWNTEYE"}
