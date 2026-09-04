"""Neko NGDK level worlds - Cocoto and Charlie's Angels."""

import struct

import numpy as np

from gcrip.formats import neko_mwld
from gcrip.plugins import neko_lz as plugin
from tests.test_neko_lz import pack


def build_world(objects=True):
    # two objects of a quad each; the second object's faces index its own vertices from 0
    verts = []
    for base in ((0, 0, 0), (4096, 0, 0)):
        for x, z in ((0, 0), (256, 0), (256, 256), (0, 256)):
            verts.append((base[0] + x, 0, base[2] + z))
    faces = [(0, 1, 2), (0, 2, 3)] * 2
    payload = struct.pack(">5I", len(faces), len(verts), 1, 0, 0)
    for k, (a, b, c) in enumerate(faces):
        material = 7 if k < 2 else 9
        payload += struct.pack(">HH", 0, 0)
        payload += struct.pack(">HBB", a, 0xFF, 0) + struct.pack(">HBB", b, 0xFF, 0)
        payload += struct.pack(">HBB", c, 0xFF, 0) + struct.pack(">HH", material, 15)
    for k, (x, y, z) in enumerate(verts):
        payload += struct.pack(">3hBB", x, y, z, 0xFF, 0)
        payload += struct.pack(">2h", (k % 4) * 1024, 4096) + bytes([255, 128, 64, 255])
    payload += struct.pack(">3hH", 0, 4096, 0, 1)
    if objects:
        for name, vbase, fbase in (("01", 0, 0), ("02", 4, 2)):
            rec = bytearray(neko_mwld.OBJECT)
            rec[: len(name)] = name.encode()
            struct.pack_into(">2I", rec, neko_mwld.OBJECT_VERTEX_BASE, vbase, fbase)
            payload += bytes(rec)
    body = b"MWLD" + struct.pack(">I", len(payload)) + payload
    body += bytes(-len(body) % 4) + b"STAO" + struct.pack(">I", 4) + bytes(4)
    return struct.pack(">3I", 3, 4, len(body) + 12) + body


def test_is_level_and_chunks():
    data = build_world()
    assert neko_mwld.is_level(data[:16], len(data))
    assert [t for t, _ in neko_mwld.chunks(data)] == ["MWLD", "STAO"]
    assert not neko_mwld.is_level(bytes(16), 16)


def test_world_adds_object_vertex_bases():
    w = neko_mwld.parse(build_world())
    assert w is not None and not w.warnings
    assert [o[0] for o in w.objects] == ["01", "02"]
    assert w.triangles[2].tolist() == [4, 5, 6] and w.triangles[0].tolist() == [0, 1, 2]
    assert np.allclose(w.positions[5], (4352 / 256.0, 0, 0))
    assert np.allclose(w.uvs[1], (0.25, 1.0)) and w.colors[0].tolist() == [255, 128, 64, 255]
    assert w.materials.tolist() == [7, 7, 9, 9]


def test_world_without_objects_keeps_indices():
    w = neko_mwld.parse(build_world(objects=False))
    assert w.triangles[2].tolist() == [0, 1, 2] and w.objects == []


def test_container_names_the_level_and_extracts_a_scene():
    packed = pack(build_world())
    members = plugin.expand(packed)
    assert members[0][0] == "world.mwld"
    path = "files/data/L11/L11.GCN/world.mwld"
    assert plugin.detect(path, members[0][1][:64], len(members[0][1]))
    scenes = plugin.extract(members[0][1], path, None)
    assert len(scenes) == 1 and scenes[0].name == "L11"
    assert len(scenes[0].primitives) == 2 and scenes[0].extras["objects"] == ["01", "02"]
    assert scenes[0].primitives[0].colors.max() <= 1.0


def build_tin(textures):
    """textures: list of (kind, width, blob); slots map 1:1, materials map to slots 1:1."""
    a = b = c = len(textures)
    head = struct.pack(">5I", 3, 4, a, b, c) + bytes(neko_mwld.TIN_HEADER - 20)
    slots = b"".join(struct.pack(">HHI", k, 16, 0) for k in range(a))
    mats = b"".join(struct.pack(">HH", 1, k) + bytes(12) for k in range(b))
    recs = b""
    gfx = b""
    for kind, width, blob in textures:
        recs += struct.pack(">4I", kind, len(blob), width, len(gfx))
        gfx += blob
    return head + slots + mats + recs, gfx


def test_tin_tables_and_textures():
    from gcrip.formats import gx_texture

    cmpr = bytes(gx_texture.encoded_size(14, 8, 8))
    rgba = bytes([1, 2, 3, 4]) * 64
    c8 = struct.pack(">256H", *([0x801F] * 256)) + bytes(gx_texture.encoded_size(9, 8, 8))
    tin, gfx = build_tin([(1, 8, cmpr), (5, 8, rgba), (1, 8, c8)])
    t = neko_mwld.tin(tin)
    assert t is not None and len(t.textures) == 3 and t.materials == [0, 1, 2]
    assert neko_mwld.texture_of_material(t, 2) == 2 and neko_mwld.texture_of_material(t, 9) is None
    assert neko_mwld.decode_texture(gfx, t.textures[0]).shape == (8, 8, 4)
    # a Charlie's Angels kind-1 picture: palette first, 8-bit indices - not a CMPR chain
    px = neko_mwld.decode_texture(gfx, t.textures[2])
    assert px.shape == (8, 8, 4) and px[0, 0].tolist() == [0, 0, 255, 255]
    assert neko_mwld.tin(bytes(64)) is None
