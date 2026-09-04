"""'res\\n' resource files (Digimon Rumble Arena 2, Lemony Snicket, Samurai Jack)."""

import struct

from gcrip.formats import res
from gcrip.plugins import res as plugin


def build() -> bytes:
    data_off = 0x1000
    payloads = [(b"wave", 4, b"AUDIODATA"), (b"surf", 44, b"TEXTUREBYTES!"), (b"strg", 28, b"hi")]
    body = bytearray()
    entries = []
    for tag, ident, blob in payloads:
        entries.append((ident, tag, len(body), len(blob)))
        body += blob
    dir_off = data_off + 0x1000
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)  # version, little-endian
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, tag, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, tag, off, size, 0)
    return bytes(out) + bytes(dirbuf)


def test_sections():
    d = build()
    assert res.is_res(d[:0x28])
    secs = res.sections(d)
    assert [(s.tag, s.ident, s.size) for s in secs] == [
        ("wave", 4, 9),
        ("surf", 44, 13),
        ("strg", 28, 2),
    ]
    assert d[secs[1].offset : secs[1].offset + secs[1].size] == b"TEXTUREBYTES!"


def test_plugin_expands_named_sections():
    d = build()
    assert plugin.is_container("final_cavern.res", d[:0x28])
    out = plugin.expand(d)
    assert [n for n, _ in out] == ["000_wave_4.bin", "001_surf_44.bin", "002_strg_28.bin"]
    assert out[1][1] == b"TEXTUREBYTES!"
    assert plugin.detect("x.res", d[:0x28], len(d)) is False
    assert plugin.extract(d, "x.res", None) == []
    assert not res.is_res(b"nope" + bytes(0x28))


def build_linked() -> bytes:
    """A level-shaped file: an rdms whose word at +4 reaches a gshd whose word at +0x5c
    reaches a surf - the way every mesh finds its texture."""
    from tests.test_res_rdms import build as build_rdms
    from tests.test_res_surf import build as build_surf

    data_off = 0x1000
    surf = build_surf()
    gshd = bytearray(208)
    rdms = bytearray(build_rdms())
    # layout: surf at data_off, gshd after it (32-byte aligned), rdms after that
    gshd_at = data_off + len(surf) + (-len(surf) % 32)
    rdms_at = gshd_at + len(gshd) + (-len(gshd) % 32)
    struct.pack_into(">i", gshd, len(gshd) - res.SURF_TAIL, data_off - (gshd_at + len(gshd) - res.SURF_TAIL))
    struct.pack_into(">i", rdms, res.SHADER_LINK, gshd_at - (rdms_at + res.SHADER_LINK))
    body = bytearray()
    entries = []
    for tag, ident, at, blob in (
        (b"surf", 1, data_off, surf),
        (b"gshd", 2, gshd_at, bytes(gshd)),
        (b"rdms", 3, rdms_at, bytes(rdms)),
    ):
        body += bytes(at - data_off - len(body))
        entries.append((ident, tag, at - data_off, len(blob)))
        body += blob
    dir_off = data_off + len(body) + (-len(body) % 32)
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, tag, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, tag, off, size, 0)
    return bytes(out) + bytes(dirbuf)


def test_meshes_find_their_texture_through_the_shader():
    d = build_linked()
    assert res.shader_textures(d) == {2: 0}
    out = plugin.expand(d)
    names = [n for n, _ in out]
    assert names[0].startswith("000_surf_") and names[2] == "002_rdms_3_t000.bin"

    class Src:
        by_path = {"lv.res/" + n: b for n, b in out}

        def get(self, p):
            return self.by_path[p]

    (scene,) = plugin.extract(out[2][1], "lv.res/" + names[2], Src())
    assert scene.materials[0].texture == "surf_000" and "surf_000" in scene.textures
    # without the container the mesh still comes out, untextured
    (bare,) = plugin.extract(out[2][1], names[2], None)
    assert bare.materials[0].texture is None and bare.triangles == scene.triangles
