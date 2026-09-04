"""007: Agent Under Fire maps - chunk stream, BOA and the ngcsurfs world."""

import struct

import numpy as np

from gcrip.formats import auf_ngc
from gcrip.plugins import auf_ngc as plugin


def boa_pack_literals(payload: bytes) -> bytes:
    """BOA with every byte a literal: a 0xff flags byte before each run of eight."""
    out = bytearray()
    for i in range(0, len(payload), 8):
        out.append(0xFF)
        out += payload[i : i + 8]
    return bytes(out)


def chunk(tag: str, payload: bytes, compressed=False) -> bytes:
    body = boa_pack_literals(payload) if compressed else payload
    head = tag.encode().ljust(8, b"\0")[::-1]
    head += struct.pack(">6I", len(payload), 0, int(compressed), 0, len(body), len(payload) + 28)
    out = head + body
    return out + bytes(-len(out) % 32)


QUAD = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)]


def build_ngcsurfs(shader=3):
    s = bytearray(0xF0)
    struct.pack_into(">f", s, 0, 1.15)
    verts = 0xF0
    body = bytearray()
    for i, (x, y, z) in enumerate(QUAD):
        body += struct.pack(">7h", x, y, z, i * 256, 512, i * 100, 200)
    idx_at = verts + len(body)
    body += bytes([0, 1, 2, 3]) + bytes(4)
    surf_at = verts + len(body)
    body += struct.pack(">BBHHBBIIHHHHI", 0, 1, 0x400, shader, 4, 4, 0, verts, 0, 0, 0x7FFF, 0, 0)
    body += struct.pack(">BBHHBBIIHHHHI", 1, 0, 0x400, shader, 4, 9, 0, verts, 0, 0, 0x7FFF, 0, 0)
    struct.pack_into(">6I", s, 8, verts, 4, idx_at, 4, surf_at, 2)
    # world matrix: scale by 0.5 and move by (10, 20, 30)
    m = np.array([[0.5, 0, 0, 10], [0, 0.5, 0, 20], [0, 0, 0.5, 30]], ">f4")
    s[0xC0 : 0xC0 + 48] = m.tobytes()
    return bytes(s + body)


def build_shaders(texture_id=0x11223344, shaders=4, shader=3):
    hdr = bytearray(0x5C)
    struct.pack_into(">f", hdr, 0, 0.945)
    shaders_at = 0x5C
    bodies_at = shaders_at + shaders * 16
    stages_at = bodies_at + shaders * 20
    out = bytearray(hdr)
    for i in range(shaders):
        out += struct.pack(">I4BII", 0x1000 + i, 1, 4, 0, 0, 2, bodies_at + i * 20)
    for i in range(shaders):
        out += struct.pack(">IBBBBIII", stages_at + i * 40, 0, 2, 0, 0, 0, 0, 0)
    for i in range(shaders):
        out += struct.pack(">HHIIII", 0, 0, auf_ngc.LIGHTMAP_ID, 0, 0, 0)
        out += struct.pack(">HHIIII", 0, 0, texture_id if i == shader else 0x55, 0, 0, 0)
    struct.pack_into(">4I", out, 4, shaders_at, shaders, bodies_at, shaders)
    return bytes(out)


def build_restxtrs(texture_id=0x11223344):
    ids = [0x77, texture_id]
    headers = 16 + 4 * len(ids)
    data_at = headers + 68 * len(ids)
    out = bytearray(struct.pack(">fIII", 1.2, len(ids), 16, headers))
    for i in ids:
        out += struct.pack(">I", i)
    pixels = bytes([0x80]) * 64  # 8x8 I8
    for k, _ in enumerate(ids):
        out += struct.pack(">IHHIIII", 1, 8, 8, 1, 1, data_at + 64 * k, 64) + bytes(68 - 24)
    out += pixels * len(ids)
    return bytes(out)


def build_map(compressed=True):
    bsp = chunk("bspinfo", bytes(32)) + chunk("ngcsurfs", build_ngcsurfs())
    return (
        chunk("snd_alb", bytes(40), compressed)
        + chunk("restxtrs", build_restxtrs(), compressed)
        + chunk("shaders", build_shaders(), compressed)
        + chunk("bspfile", bsp)
    )


def test_boa_expands_literals_and_matches():
    raw = b"abcabcabcabcabcabc"
    # three literals, then a copy of 15 bytes from 3 back: b0 = (15 - 2) | (3 << 4), b1 = 0
    packed = bytes([0b00000111, ord("a"), ord("b"), ord("c"), 0x3D, 0x00])
    assert auf_ngc.boa_expand(packed, 18) == raw
    assert auf_ngc.boa_expand(boa_pack_literals(raw), len(raw)) == raw


def test_chunk_stream_and_detection():
    data = build_map()
    assert auf_ngc.is_map(data[:32], len(data))
    assert plugin.detect("files/maps/dm1.ngc", data[:64], len(data))
    assert not plugin.detect("files/maps/dm1.gsf", data[:64], len(data))
    assert not auf_ngc.is_map(bytes(64), 4096)
    tags = [c.tag for c, _ in auf_ngc.chunks(data)]
    assert tags == ["snd_alb", "restxtrs", "shaders", "bspfile"]
    m = auf_ngc.parse(data)
    assert m is not None and m.warnings == []
    assert m.chunks == tags and len(m.textures) == 2 and m.shader_textures[3] == 0x11223344


def test_world_surfaces_are_strips_through_the_matrix():
    m = auf_ngc.parse(build_map(compressed=False))
    (s,) = m.surfaces  # the patch (type 1) is skipped
    assert s.shader == 3 and s.lightmap == 1 and len(s.indices) == 6
    assert np.allclose(s.positions[3], [60, 70, 30])
    assert np.allclose(s.uvs[1], [1.0, 2.0]) and np.allclose(
        s.lightmap_uvs[2], [200 / 32768, 200 / 32768]
    )
    t = s.indices.reshape(-1, 3)
    p = s.positions
    face = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    assert (face[:, 2] > 0).all()


def test_plugin_binds_the_maps_own_textures():
    (scene,) = plugin.extract(build_map(), "files/maps/dm1.ngc", None)
    assert scene.triangles == 2 and len(scene.primitives) == 1
    assert scene.materials[0].texture == "tex_11223344"
    assert scene.textures["tex_11223344"].shape == (8, 8, 4)
    assert scene.extras["surfaces"] == 1 and scene.extras["textures_in_map"] == 2
    assert plugin.extract(chunk("snd_alb", bytes(40)), "x.ngc", None) == []


def build_gcm(shader_id=0x1003):
    """A ``.gcm``: block header, the C_Object3D header at +0x10 whose +0x80 names the NGC
    block, and there the matrix, the (ptr, count) pairs and one section / group / strip of
    QUAD - with the models' own strip winding."""
    hdr = bytearray(0x98)
    ngc_block = 0x10 + len(hdr)
    struct.pack_into(">I", hdr, 0x80, ngc_block)
    out = bytearray(struct.pack(">II", 0x48400001, 8)) + bytes(8) + hdr
    body = bytearray(0x9C)
    m = np.array([[0.5, 0, 0, 1], [0, 0.5, 0, 2], [0, 0, 0.5, 3]], ">f4")
    body[:48] = m.tobytes()
    arrays = bytearray()
    pos_p = 0x9C + len(arrays)
    for x, y, z in QUAD:
        arrays += struct.pack(">3h", x, y, z)
    nrm_p = 0x9C + len(arrays)
    for _ in QUAD:
        arrays += struct.pack(">3b", 0, 0, 127)
    st_p = 0x9C + len(arrays)
    for i in range(4):
        arrays += struct.pack(">2h", i * 512, 1024)
    ev_p = 0x9C + len(arrays)
    for i in range(4):
        arrays += struct.pack(">3H", i, i, i)
    idx_p = 0x9C + len(arrays)
    arrays += struct.pack(">4H", 0, 1, 2, 3)
    strip_p = 0x9C + len(arrays)
    arrays += struct.pack(">3HBB", 0, 4, 0, 0, 0xFF)
    grp_p = 0x9C + len(arrays)
    arrays += struct.pack(">4H", 0, 0, 0, 1)
    sec_p = 0x9C + len(arrays)
    arrays += struct.pack(">IIHHHH", 0, shader_id, 0, 1, 2, 4)
    pairs = [
        (pos_p, 4),
        (nrm_p, 4),
        (st_p, 4),
        (ev_p, 4),
        (idx_p, 4),
        (0, 0),
        (strip_p, 1),
        (0, 0),
        (grp_p, 1),
        (sec_p, 1),
    ]
    for k, (ptr, count) in enumerate(pairs):
        struct.pack_into(">2I", body, 0x34 + 8 * k, ptr, count)
    out += struct.pack(">II", 0x3ED, 8) + bytes(8) + body + arrays
    return bytes(out)


def build_restable(gcm: bytes):
    names = b"models/weapons/test.gcm\0"
    data_at = 16 + 16 + len(names)
    data_at += -data_at % 16
    out = bytearray(struct.pack(">4I", 1, 0, 0, 0))
    out += struct.pack(">4I", 32, data_at, len(gcm), 0x1234)
    out += names
    out += bytes(data_at - len(out))
    out += gcm
    return bytes(out)


def test_restable_models_read_and_bind_shaders_by_hash():
    gcm = build_gcm()
    mdl = auf_ngc.model(gcm, "test")
    assert mdl is not None and mdl.warnings == [] and len(mdl.batches) == 1
    (b,) = mdl.batches
    assert b.shader_id == 0x1003 and len(b.indices) == 6
    assert np.allclose(b.positions[3], [51, 52, 3]) and np.allclose(b.normals[0], [0, 0, 127 / 128])
    assert np.allclose(b.uvs[2], [0.5, 0.5])
    t = b.indices.reshape(-1, 3)
    face = np.cross(
        b.positions[t[:, 1]] - b.positions[t[:, 0]], b.positions[t[:, 2]] - b.positions[t[:, 0]]
    )
    assert (face[:, 2] < 0).all()  # the models wind the other way round from the world
    assert auf_ngc.model(bytes(64)) is None
    data = build_map() + chunk("restable", build_restable(gcm))
    scenes = plugin.extract(data, "files/maps/dm1.ngc", None)
    assert len(scenes) == 2 and scenes[1].name == "test" and scenes[1].extras["kind"] == "model"
    assert scenes[0].extras["models"] == 1
    # shader 0x1003 is index 3 in the synthetic shader table, which binds texture 0x11223344
    assert scenes[1].materials[0].texture == "tex_11223344"
