"""TT reversed-tag NU2 .hgo / .nus (Crash WoC, Finding Nemo): meshes, skin, textures, INST."""

import struct

import numpy as np

from gcrip.formats import hgo
from gcrip.plugins import hgo as plugin


def chunk(tag: bytes, body: bytes) -> bytes:
    return tag[::-1] + struct.pack(">I", 8 + len(body)) + body


def vertex(x, y, z, uv=True):
    v = struct.pack(">6f", x, y, z, 0, 0, 1) + bytes([255, 128, 64, 255])
    if uv:
        v += struct.pack(">2f", x, y)
    return v


def mesh_block(material: int, verts: list[bytes], strip: bool = False, skin: bool = False) -> bytes:
    body = struct.pack(">3I", 1, material, len(verts)) + b"".join(verts)
    idx = list(range(len(verts)))
    body += struct.pack(">4I", 0, 1, 6 if strip else 5, len(idx)) + struct.pack(
        f">{len(idx)}H", *idx
    )
    body += bytes(-len(body) % 4)
    if skin:
        body += b"\x01\x01" + b"".join(
            struct.pack(">3f", 0.5, 0.5, 0) + bytes([1, 2, 0, 0]) for _ in verts
        )
    return body


def make_hgo() -> bytes:
    names = b"\0".join([b"root", b"one", b"two"]) + b"\0"
    ntbl = chunk(b"NTBL", struct.pack(">I", len(names)) + names)
    pix = struct.pack(">64H", *([0x8000 | (31 << 10)] * 64))  # 8x8 RGB5A3 red
    txm = chunk(b"TXM0", struct.pack(">4I", 0x81, 8, 8, len(pix)) + pix)
    tst = chunk(b"TST0", chunk(b"TSH0", struct.pack(">I", 1)) + txm)
    mat = bytearray(84)
    struct.pack_into(">3f", mat, 20, 1.0, 0.5, 0.25)
    struct.pack_into(">i", mat, 56, 0)
    ms = chunk(b"MS00", struct.pack(">I", 1) + bytes(mat))
    node = struct.pack(">16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    hg = bytes([3, 8]) + node * 3 + bytes(16)
    hg += mesh_block(0, [vertex(0, 0, 0), vertex(1, 0, 0), vertex(0, 1, 0)], skin=True)
    hgo0 = chunk(b"HGO0", hg)
    return chunk(b"HGOF", ntbl + tst + ms + hgo0)


def make_nus() -> bytes:
    names = b"letterA\0letterB\0"
    ntbl = chunk(b"NTBL", struct.pack(">I", len(names)) + names)
    mat = bytearray(84)
    struct.pack_into(">i", mat, 56, -1)
    ms = chunk(b"MS00", struct.pack(">I", 1) + bytes(mat))
    gst = struct.pack(">6I", 2, 1, 0, 0, 0, 0)
    gst += mesh_block(
        0, [vertex(0, 0, 0, uv=False), vertex(1, 0, 0, uv=False), vertex(0, 1, 0, uv=False)]
    )
    gst += mesh_block(
        0,
        [vertex(0, 0, 0, uv=False), vertex(2, 0, 0, uv=False), vertex(0, 2, 0, uv=False)],
        strip=True,
    )
    gst0 = chunk(b"GST0", gst)
    ident = struct.pack(">16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1) + bytes(16)
    moved = struct.pack(">16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1) + bytes(16)
    inst = chunk(b"INST", struct.pack(">I", 2) + ident + moved)
    return chunk(
        b"GSC0", ntbl + chunk(b"TST0", chunk(b"TSH0", struct.pack(">I", 0))) + ms + gst0 + inst
    )


def test_hgo_character():
    data = make_hgo()
    assert hgo.is_hgo(data[:16]) and plugin.detect("files/chars/x.hgo", data[:16], len(data))
    m = hgo.parse(data)
    assert m.kind == "hgo" and m.names == ["root", "one", "two"] and m.node_count == 3
    assert len(m.textures) == 1 and m.textures[0].rgba.shape == (8, 8, 4)
    assert tuple(m.textures[0].rgba[0, 0]) == (255, 0, 0, 255)
    assert len(m.meshes) == 1
    mesh = m.meshes[0]
    assert mesh.indices.tolist() == [0, 1, 2] and mesh.uvs is not None
    np.testing.assert_allclose(mesh.weights[0], [0.5, 0.5, 0, 0])
    assert mesh.joints[0].tolist() == [1, 2, 0, 0]
    scenes = plugin.extract(data, "files/chars/x.hgo", None)
    assert len(scenes) == 1 and scenes[0].extras["skinned"] is True
    s = scenes[0]
    assert [j.name for j in s.joints] == ["root", "one", "two"]
    assert s.materials[0].texture == "tex000" and s.primitives[0].joints is not None


def test_nus_level_instances():
    data = make_nus()
    assert plugin.detect("files/stuff/a.nus", data[:16], len(data))
    m = hgo.parse(data)
    assert m.kind == "gsc" and len(m.meshes) == 2 and len(m.instances) == 2
    assert m.meshes[0].uvs is None and len(m.meshes[1].indices) == 3
    scenes = plugin.extract(data, "files/stuff/a.nus", None)
    s = scenes[0]
    assert s.extras["format"] == "tt-gsc" and len(s.primitives) == 2
    np.testing.assert_allclose(s.primitives[1].positions[1], [12, 20, 30])
