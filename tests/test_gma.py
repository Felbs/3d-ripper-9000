"""Amusement Vision GMA / TPL / LZ: synthetic files only (no game data)."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import avlz, gma, gma_tpl
from gcrip.plugins import gma as plugin


def _pad32(b: bytearray) -> None:
    while len(b) % 0x20:
        b.append(0)


def _display_list(vertices: list[tuple], fmt: str, opcode: int = 0x98) -> bytes:
    dl = bytearray(b"\x00")  # GX NOP the stock files start with
    dl += struct.pack(">BH", opcode, len(vertices))
    for v in vertices:
        dl += struct.pack(fmt, *v)
    _pad32(dl)
    return bytes(dl)


def _mesh(vflags: int, dl_a: bytes, dl_b: bytes, dest: int, tex_slot: int) -> bytes:
    """0x60 mesh header followed by its display lists."""
    h = bytearray(0x60)
    struct.pack_into(">IIII", h, 0, 0x0, 0xFFFFFFFF, 0x80808080, 0)
    struct.pack_into(">BBBB", h, 0x10, 0, 0xFF, 1 if tex_slot >= 0 else 0, dest)
    struct.pack_into(">hhh", h, 0x16, tex_slot, -1, -1)
    struct.pack_into(">I", h, 0x1C, vflags)
    h[0x20:0x28] = b"\xff" * 8
    struct.pack_into(">II", h, 0x28, len(dl_a), len(dl_b))
    return bytes(h) + dl_a + dl_b


def _gcmf(attrs: int, meshes: list[bytes], tex_count: int, matrices: int = 0) -> bytes:
    g = bytearray(0x40)
    g[0:4] = b"GCMF"
    struct.pack_into(">Iffff", g, 4, attrs, 0.0, 0.0, 0.0, 2.0)
    struct.pack_into(">HHHB", g, 0x18, tex_count, len(meshes), 0, matrices)
    g[0x28:0x30] = b"\xff" * 8
    for t in range(tex_count):
        layer = bytearray(0x20)
        struct.pack_into(">HBBHBB", layer, 0, 0, 0x07, 0x94, t, 0, 0)  # repeat U and V
        struct.pack_into(">H", layer, 0x0E, t)
        struct.pack_into(">I", layer, 0x10, 0x30)
        g += layer
    for _ in range(matrices):
        g += struct.pack(">12f", 1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, 0)
    struct.pack_into(">I", g, 0x20, len(g))
    for m in meshes:
        g += m
    return bytes(g)


def _gma(models: list[tuple[str, bytes]]) -> bytes:
    names = bytearray()
    entries = bytearray()
    blobs = bytearray()
    for name, blob in models:
        entries += struct.pack(">II", len(blobs), len(names))
        names += name.encode() + b"\0"
        blobs += blob
    header = struct.pack(">II", len(models), 0) + entries + names
    base = (len(header) + 0x1F) & ~0x1F
    out = bytearray(header)
    out += b"\0" * (base - len(header))
    struct.pack_into(">I", out, 4, base)
    out += blobs
    return bytes(out)


def _tpl(textures: list[tuple[int, int, int, bytes]]) -> bytes:
    """[(fmt, w, h, image bytes)] -> AV TPL."""
    head = bytearray(struct.pack(">I", len(textures)))
    body = bytearray()
    entries = []
    data_start = (4 + 16 * len(textures) + 0x1F) & ~0x1F
    for fmt, w, h, img in textures:
        entries.append((fmt, data_start + len(body), w, h))
        body += img
        _pad32(body)
    for fmt, off, w, h in entries:
        head += struct.pack(">HBBIHHHH", 0, 0, fmt, off, w, h, 1, 0x1234)
    head += b"\0" * (data_start - len(head))
    return bytes(head + body)


# POS | NRM | TEX0 float quad as one strip, then the same in 16-bit form
VF = (1 << gma.VA_POS) | (1 << gma.VA_NRM) | (1 << gma.VA_TEX0)
QUAD = [
    (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0),
    (1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
]


def _quad16():
    out = []
    for x, y, z, nx, ny, nz, u, v in QUAD:
        out.append(
            (
                int(x * 8192), int(y * 8192), int(z * 8192),
                int(nx * 16384), int(ny * 16384), int(nz * 16384),
                int(u * 8192), int(v * 8192),
            )
        )
    return out


def _sample_gma() -> bytes:
    dl = _display_list(QUAD, ">8f")
    plain = _gcmf(0, [_mesh(VF, dl, b"", 0x1, 0)], tex_count=1)
    dl16 = _display_list(_quad16(), ">8h", opcode=0x99)
    both = _mesh(VF, dl16, dl16, 0x3, 0)
    compact = _gcmf(gma.ATTR_16BIT, [both], tex_count=1)
    skin = _gcmf(gma.ATTR_SKIN, [], tex_count=0)
    return _gma([("PLAIN", plain), ("COMPACT", compact), ("SKIN_SKL", skin)])


def test_parse_gma_plain_and_16bit():
    data = _sample_gma()
    assert gma.looks_like(data[:8], len(data))
    model = gma.parse(data)
    assert [g.name for g in model.models] == ["PLAIN", "COMPACT", "SKIN_SKL"]
    plain, compact, skin = model.models
    assert not plain.warnings and not compact.warnings
    assert plain.layers[0].repeat_u and plain.layers[0].repeat_v and not plain.layers[0].mirror_u
    (s,) = plain.meshes[0].strips
    assert s.opcode == 0x98 and s.count == 4
    np.testing.assert_allclose(s.positions[3], [1, 1, 0])
    np.testing.assert_allclose(s.uvs[0][1], [1, 0])
    np.testing.assert_allclose(gma.strip_triangles(s), [[0, 1, 2], [1, 3, 2]])
    (s16,) = compact.meshes[0].strips
    np.testing.assert_allclose(s16.positions, s.positions, atol=1e-3)
    np.testing.assert_allclose(s16.normals, s.normals, atol=1e-3)
    np.testing.assert_allclose(s16.uvs[0], s.uvs[0], atol=1e-3)
    assert len(compact.meshes[0].strips_b) == 1
    assert skin.skinned and skin.meshes == []


def test_parse_rejects_garbage():
    with pytest.raises(gma.GmaError):
        gma.parse(b"\0" * 64)
    assert not gma.looks_like(b"\0\0\0\x05\0\0\0\x07", 1000)


def test_av_tpl_parse():
    # a 4x4 RGB565 texture (one 4x4 tile, 32 bytes) and an 8x8 CMPR one (32 bytes)
    data = _tpl([(4, 4, 4, bytes(32)), (14, 8, 8, bytes(32))])
    assert gma_tpl.looks_like(data)
    texs = gma_tpl.parse(data)
    assert len(texs) == 2
    assert texs[0].width == 4 and texs[0].fmt == 4 and texs[1].fmt == 14
    assert texs[1].decode(0).shape == (8, 8, 4)
    assert texs[0].decode(0).shape == (4, 4, 4)


def test_lz_roundtrip():
    payload = b"GCMF" + bytes(range(256)) * 3 + b"\0" * 300 + b"abcabcabcabc" * 20
    packed = avlz.compress(payload)
    assert avlz.looks_like(packed, len(packed))
    assert len(packed) < len(payload)
    assert avlz.decompress(packed) == payload
    assert not avlz.looks_like(b"\0" * 12, 12)


class _Src:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path: str) -> bytes:
        return self.files[path]


def test_plugin_extract_with_sibling_tpl_and_lz_container():
    data = _sample_gma()
    tpl = _tpl([(4, 4, 4, bytes(32))])
    src = _Src({"bg/x.gma": data, "bg/x.tpl": tpl})
    assert plugin.detect("bg/x.gma", data[:64], len(data))
    assert not plugin.detect("bg/x.tpl", tpl[:64], len(tpl))
    (scene,) = plugin.extract(data, "bg/x.gma", src)
    assert [j.name for j in scene.joints] == ["PLAIN", "COMPACT"]
    assert scene.triangles == 4  # 2 per quad; DL B duplicates A -> double sided instead
    assert scene.materials[1].double_sided
    assert scene.materials[0].texture == "tex000" and "tex000" in scene.textures
    assert scene.textures["tex000"].shape == (4, 4, 4)
    assert any("skinned" in w for w in scene.warnings)

    # the same pair wrapped in F-Zero GX's .lz archives
    packed = avlz.compress(data)
    assert plugin.is_container("x.gma.lz", packed[:64])
    ((inner, blob),) = plugin.expand(packed)
    assert inner == "model.gma" and blob == data
    ((tinner, _),) = plugin.expand(avlz.compress(tpl))
    assert tinner == "textures.tpl"
    src2 = _Src({"bg/x.gma.lz/model.gma": data, "bg/x.tpl.lz/textures.tpl": tpl})
    (scene2,) = plugin.extract(data, "bg/x.gma.lz/model.gma", src2)
    assert scene2.name == "x" and scene2.materials[0].texture == "tex000"

    # F-Zero machines: bfalcon_02.gma shares bfalcon.tpl
    src3 = _Src({"vehicle/bfalcon_02.gma": data, "vehicle/bfalcon.tpl": tpl})
    (scene3,) = plugin.extract(data, "vehicle/bfalcon_02.gma", src3)
    assert scene3.materials[0].texture == "tex000"
