"""Sonic Adventure 2: Battle model archives (big-endian Ninja chunk models) and Sega PRS."""

import struct

import numpy as np

from gcrip.formats import prs, sa2b
from gcrip.plugins import sa2b as plug
from gcrip.plugins import segaprs


def build_model() -> bytes:
    """id table + one NJS_OBJECT with a chunk attach: 4 vertices (type 0x22) and one
    textured strip chunk (type 0x41, UVs) drawing a quad."""
    d = bytearray(0x200)
    struct.pack_into(">2I", d, 0, 7, 0x40)  # table: id 7 -> object at 0x40
    struct.pack_into(">I", d, 8, 0xFFFFFFFF)
    obj, attach, vlist, plist = 0x40, 0x80, 0xA0, 0x120
    struct.pack_into(">II3f3i3fII", d, obj, 0, attach, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0)
    struct.pack_into(">II4f", d, attach, vlist, plist, 0, 0, 0, 1)
    # vertex chunk 0x22 (position only, 12 bytes each): size in words = (4*12 + 4) / 4
    struct.pack_into(">HBBHH", d, vlist, (4 * 12 + 4) // 4, 0, 0x22, 4, 0)
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        struct.pack_into(">3f", d, vlist + 8 + i * 12, x, y, 0)
    struct.pack_into(">HBB", d, vlist + 8 + 48, 0, 0, 0xFF)  # end chunk
    # poly list: tiny texture chunk (type 8, texture 3), strip chunk 0x41 with 1 strip of 4
    p = plist
    struct.pack_into(">BBH", d, p, 0, 0x08, 3)
    p += 4
    body = struct.pack(">H", 1) + struct.pack(">h", 4)
    for i in range(4):
        body += struct.pack(">Hhh", i, (i % 2) * 1024, (i // 2) * 1024)
    struct.pack_into(">BBH", d, p, 0x10, 0x41, len(body) // 2)
    d[p + 4 : p + 4 + len(body)] = body
    p += 4 + len(body)
    struct.pack_into(">BB", d, p, 0, 0xFF)
    return bytes(d)


def test_sa2b_model():
    d = build_model()
    assert sa2b.model_table(d) == [(7, 0x40)]
    models = sa2b.parse(d)
    assert len(models) == 1 and models[0][0] == 7
    nj = models[0][1]
    assert len(nj.objects) == 1 and nj.objects[0].model is not None
    m = nj.objects[0].model
    assert len(m.vertices) == 4 and len(m.strips) == 1
    assert m.strips[0].material.texture == 3 and len(m.strips[0].indices) == 6
    assert not nj.warnings
    scenes = plug.extract(d, "files/x.prs/payload.bin", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2
    assert np.allclose(scenes[0].primitives[0].positions[:, 2], 0.0)


def test_sega_prs_roundtrip_literals():
    payload = build_model()
    # literal-only PRS stream: flag bytes of all ones then 8 literals each
    packed = bytearray()
    for i in range(0, len(payload), 8):
        packed.append(0xFF)
        packed += payload[i : i + 8]
    packed += bytes([0x02, 0x00, 0x00])  # flag bits 0,1 then u16 0 = end of stream
    assert prs.decompress(bytes(packed)) == payload
    members = segaprs.expand(bytes(packed))
    assert members == [("payload.bin", payload)]
    assert plug.detect("files/x.prs/payload.bin", payload[:64], len(payload))
