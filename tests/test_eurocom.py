"""Eurocom EngineX: Filelist.bin directories and GEOM .edb mesh entities (v182 layout)."""

import struct

import numpy as np

from gcrip.formats import eurocom
from gcrip.plugins import eurocom as plug


def rel(at: int, target: int) -> bytes:
    return struct.pack(">i", target - at)


def build_edb() -> bytes:
    """One mesh entity: a quad as a 4-vertex strip, one 8x8 CMPR texture."""
    d = bytearray(0x400)
    d[:4] = b"GEOM"
    struct.pack_into(">6I", d, 4, 0x01000254, 182, 0x2000001B, 0, len(d), len(d))
    # hash arrays at 0x54: sections, refpointers, entities(2), anims, animskins(4) ...
    ent_off, tex_off = 0x120, 0x140
    struct.pack_into(">hh", d, 0x54 + 2 * 8, 1, 1)
    d[0x54 + 2 * 8 + 4 : 0x54 + 2 * 8 + 8] = rel(0x54 + 2 * 8 + 4, ent_off)
    tex_list = 0x54 + 13 * 8
    struct.pack_into(">hh", d, tex_list, 1, 1)
    d[tex_list + 4 : tex_list + 8] = rel(tex_list + 4, tex_off)
    # entity list element (32 B for v182): hashcode, section, debug, address
    entity = 0x200
    struct.pack_into(">IHHI", d, ent_off, 0x02000001, 0, 0, entity)
    # texture element (28 B): hashcode, section, debug, address, ptr, w, h
    texture = 0x320
    struct.pack_into(">IHHIIHH", d, tex_off, 0x06000001, 0, 0, texture, 0, 8, 8)
    # mesh entity @0x200
    strips, verts, uvs, cols = 0x280, 0x2D0, 0x300, 0x310
    struct.pack_into(">I", d, entity, 0x601)
    d[entity + 0x44 : entity + 0x48] = rel(entity + 0x44, strips)
    d[entity + 0x48 : entity + 0x4C] = rel(entity + 0x48, verts)
    d[entity + 0x4C : entity + 0x50] = rel(entity + 0x4C, uvs)
    d[entity + 0x50 : entity + 0x54] = rel(entity + 0x50, cols)
    struct.pack_into(">II", d, entity + 0x5C, 1, 4)
    struct.pack_into(">I", d, entity + 0x68, 0x20000000)  # uv divisor 16384
    # strip: header 32 B (tex 0, flags, data size 4 + 4*8) + display list
    dl = struct.pack(">HH", 0x98, 4) + b"".join(struct.pack(">4H", i, 0, 0, i) for i in range(4))
    struct.pack_into(">4HI", d, strips, 0, 0, 0x90, 0, len(dl))
    d[strips + 32 : strips + 32 + len(dl)] = dl
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        struct.pack_into(">3f", d, verts + i * 12, x, y, 0.0)
        struct.pack_into(">2h", d, uvs + i * 4, x * 16384, y * 16384)
    d[cols : cols + 4] = bytes([255, 128, 0, 255])
    # texture struct (v182: u32 pad first) + frame: 64-byte GX header + 32 bytes CMPR
    struct.pack_into(">I4H2h8B", d, texture, 0, 8, 8, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0)
    frame = 0x380
    struct.pack_into(">I", d, texture + 4 + 0x24, 64 + 32)
    d[texture + 4 + 0x28 : texture + 4 + 0x2C] = rel(texture + 4 + 0x28, frame)
    d[frame + 27] = 14
    d[frame + 64 : frame + 96] = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0]) * 4
    return bytes(d)


def test_edb_mesh_and_texture():
    data = build_edb()
    assert eurocom.is_edb(data[:16])
    edb = eurocom.parse(data)
    assert edb.version == 182 and len(edb.entities) == 1 and len(edb.textures) == 1
    meshes = eurocom.mesh_entity(edb, edb.entities[0])
    assert len(meshes) == 1 and len(meshes[0].strips) == 1
    s = meshes[0].strips[0]
    assert len(s.indices) == 6 and s.positions.shape == (4, 3)
    assert np.allclose(s.uvs, [[0, 0], [1, 0], [0, 1], [1, 1]])
    assert np.allclose(s.colors[0], [1.0, 128 / 255, 0.0, 1.0])
    img = eurocom.texture_rgba(edb, edb.textures[0])
    assert img is not None and img.shape == (8, 8, 4) and int(img[0, 0, 0]) == 255


def build_filelist(ver: int) -> tuple[bytes, bytes]:
    edb = build_edb()
    payload = bytes(0x800) + edb
    names = [b"x:\\game\\binary\\_bin_gc\\quad.edb"]
    hdr = struct.pack(">3I", ver, 0, 1)
    if ver >= 5:
        hdr += struct.pack(">HH", 1, 0)
    body = bytearray(hdr + bytes(4))
    entry_len = len(edb) - 16  # base size smaller than the real EDB size
    if ver <= 4:
        body += struct.pack(">I", 0x800)
    body += struct.pack(">4I", entry_len, 0x01000001, 182, 0x2000001B)
    if ver >= 5:
        body += struct.pack(">I", 1) + struct.pack(">2I", 0x800, 0)
    ptr_at = len(hdr)
    body[ptr_at : ptr_at + 4] = rel(ptr_at, len(body))
    table = len(body)
    body += bytes(4)
    body[table : table + 4] = rel(table, len(body))
    for i, n in enumerate(names):
        n += b"\0"
        if ver >= 7:  # the terminator is obfuscated like every other byte
            n = bytes(((c - 0x16 + i + j) & 0xFF) for j, c in enumerate(n))
        body += n
    struct.pack_into(">I", body, 4, len(body))
    return bytes(body), payload


def test_filelist_versions():
    for ver in (4, 5, 7):
        listing, payload = build_filelist(ver)
        ents = eurocom.filelist(listing)
        assert [e.name for e in ents] == ["x:\\game\\binary\\_bin_gc\\quad.edb"], ver
        members = plug.expand_with(payload, "Filelist.000", lambda n, b=listing: b)
        assert [m[0] for m in members] == ["game/binary/_bin_gc/quad.edb"]
        assert members[0][1] == payload[0x800:]  # full EDB size from its header


def test_plugin_extract():
    data = build_edb()
    assert plug.detect("files/Filelist.000/game/binary/_bin_gc/quad.edb", data[:64], len(data))
    scenes = plug.extract(data, "files/Filelist.000/game/binary/_bin_gc/quad.edb", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2
    assert scenes[0].materials[0].texture == "06000001" and len(scenes[0].textures) == 1
