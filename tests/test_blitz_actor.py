"""Blitz Games packs: the resource index, actors in both geometry encodings, textures, and the
plugin chain that binds them by CRC."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import blitz_actor, blitz_pack, gx_texture
from gcrip.plugins import blitz as container
from gcrip.plugins import blitz_actor as plugin
from gcrip.plugins import blitz_tbt


def _resinfo(kind: int, crc: int) -> bytes:
    r = bytearray(32)
    r[6] = kind
    struct.pack_into(">I", r, 12, crc)
    return bytes(r)


def _dl_actor(crc: int = 0x1234, texture_crc: int = 0xAAAA) -> bytes:
    """One mesh node (vertexType 16): a quad as a strip over indexed arrays, stride 8."""
    body = bytearray(_resinfo(blitz_pack.TYPE_ACTOR, crc))
    body += bytes(128)  # no soft skin
    body += bytes(244 - len(body))
    body[blitz_actor.VERTEX_TYPE_AT] = 16
    body[blitz_actor.NODE_COUNT_AT] = 1
    struct.pack_into(">6f", body, 192, -1, 1, -1, 1, 0, 0)
    body += b"\0" * (-len(body) % 32)
    pos_at = len(body)
    for p in ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)):
        body += struct.pack(">3f", *p)
    nrm_at = len(body)
    body += bytes([0, 0, 64]) * 4
    body += b"\0" * (-len(body) % 4)
    tex_at = len(body)
    for uv in ((0, 0), (1, 0), (1, 1), (0, 1)):
        body += struct.pack(">2f", *uv)
    clr_at = len(body)
    body += bytes([255, 0, 0, 255]) * 4
    dl_at = len(body)
    dl = bytes([0x99]) + struct.pack(">H", 4)
    for v in (0, 1, 3, 2):
        dl += struct.pack(">4H", v, 0, v, v)
    dl += b"\0" * (-len(dl) % 32)
    body += dl
    batches_at = len(body)
    body += struct.pack(">4I", 1, texture_crc, 0, 0)
    prims_at = len(body)
    body += struct.pack(">BBHHH", 5, 3, 4, 2, 0)
    name_at = len(body)
    body += b"polySurface1\0"
    body += b"\0" * (-len(body) % 16)
    node_at = len(body)
    node = bytearray(blitz_actor.NODE)
    struct.pack_into(">3f", node, 0, 1.0, 2.0, 3.0)
    struct.pack_into(">4f", node, 80, 0, 0, 0, 1)
    mesh = bytearray(blitz_actor.MESH)
    struct.pack_into(">5I", mesh, 0, 4, 0, 1, batches_at, prims_at)
    struct.pack_into(">6I", mesh, 80, pos_at, nrm_at, tex_at, clr_at, dl_at, len(dl))
    node[112 : 112 + blitz_actor.MESH] = mesh
    node[272] = blitz_actor.TYPE_MESH
    struct.pack_into(">I", node, 304, name_at)
    body += node
    struct.pack_into(">I", body, blitz_actor.ROOT_AT, node_at)
    return bytes(body)


def _stream_actor(crc: int = 0x5678) -> bytes:
    """vertexType 2: a lightmapped strip of _TBDualPrimVertex records, no display list."""
    body = bytearray(_resinfo(blitz_pack.TYPE_ACTOR, crc))
    body += bytes(244 - len(body))
    body[blitz_actor.VERTEX_TYPE_AT] = 2
    body[blitz_actor.NODE_COUNT_AT] = 1
    body += b"\0" * (-len(body) % 32)
    verts_at = len(body)
    for i, p in enumerate(((-1, -1, 0), (1, -1, 0), (-1, 1, 0), (1, 1, 0))):
        body += struct.pack(">3f", *p) + struct.pack(">3f", 0, 0, 1) + bytes([i * 60, 0, 0, 255]) + struct.pack(">2f", i % 2, i // 2) + struct.pack(">2f", 0.5, 0.5)
    batches_at = len(body)
    body += struct.pack(">4I", 1, 0xBBBB, 0xCCCC, 0)
    prims_at = len(body)
    body += struct.pack(">BBHHH", 5, 3, 4, 2, 0)
    node_at = len(body)
    node = bytearray(blitz_actor.NODE)
    mesh = bytearray(blitz_actor.MESH)
    struct.pack_into(">5I", mesh, 0, 4, verts_at, 1, batches_at, prims_at)
    node[112 : 112 + blitz_actor.MESH] = mesh
    node[272] = blitz_actor.TYPE_MESH
    body += node
    struct.pack_into(">I", body, blitz_actor.ROOT_AT, node_at)
    return bytes(body)


def _texture(crc: int = 0xAAAA, w: int = 8, h: int = 8) -> bytes:
    body = bytearray(_resinfo(blitz_pack.TYPE_TEXTURE, crc))
    body += bytes(160 - len(body))
    struct.pack_into(">3I", body, 32, w, h, 21)
    struct.pack_into(">HBB", body, 44, 0, 1, 1)
    struct.pack_into(">I", body, 56, w * h)
    struct.pack_into(">II", body, 108, 0, 160)
    body += bytes(gx_texture.encoded_size(0xE, w, h))
    return bytes(body)


def _pack(resources: list[tuple[str, bytes]]) -> bytes:
    """A bare pack: header, resources at 32-byte units, filename table, index."""
    body = bytearray(0x800)
    names = bytearray()
    entries = []
    for name, blob in resources:
        body += b"\0" * (-len(body) % 32)
        off = len(body)
        body += blob
        crc = struct.unpack_from(">I", blob, 12)[0] if len(blob) >= 16 else 0
        entries.append((off, crc, len(blob), len(names)))
        names += name.encode() + b"\0"
    body += b"\0" * (-len(body) % 32)
    names_at = len(body)
    body += names
    body += b"\0" * (-len(body) % 32)
    index_at = len(body)
    for off, crc, size, name_off in entries:
        body += struct.pack(">8I", off // 32, crc, size, name_off, 1, 0, 0, 0)
    struct.pack_into(">4I", body, 0, 0x11223344, 0x20, 0, len(entries))
    struct.pack_into(">I", body, 0x10, index_at // 32)
    struct.pack_into(">II", body, 0x28, names_at // 32, len(names))
    struct.pack_into(">I", body, 0x30, len(entries) * 32)
    return bytes(body)


def test_index_names_types_and_crcs():
    pack = _pack([("t_wall", _texture()), ("o_thing", _dl_actor()), ("dummy", b"a")])
    assert blitz_pack.is_bare_pack(pack[:64])
    res = blitz_pack.resources(pack)
    assert [(r.name, r.kind) for r in res] == [("t_wall", 0), ("o_thing", 1), ("dummy", -1)]
    assert res[1].crc == 0x1234 and res[0].crc == 0xAAAA


def test_display_list_actor_reads_indexed_arrays():
    a = blitz_actor.parse(_dl_actor())
    assert a.vertex_type == 16 and [n.name for n in a.nodes] == ["polySurface1"]
    assert a.nodes[0].position == (1.0, 2.0, 3.0)
    (m,) = a.meshes
    assert m.texture == 0xAAAA and m.indices.size == 6
    assert m.positions.shape == (4, 3) and m.normals[0].tolist() == [0.0, 0.0, 1.0]
    assert m.uvs.max() == 1.0 and tuple(m.colors[0]) == (255, 0, 0, 255)


def test_prim_vertex_stream_actor():
    a = blitz_actor.parse(_stream_actor())
    (m,) = a.meshes
    assert m.indices.size == 6 and m.positions.shape == (4, 3)
    assert m.uvs2 is not None and m.uvs2[0].tolist() == [0.5, 0.5]
    assert m.texture == 0xBBBB and m.texture2 == 0xCCCC
    assert tuple(m.colors[1]) == (60, 0, 0, 255)


def test_texture_resource_decodes_cmpr():
    rgba = blitz_actor.texture(_texture())
    assert rgba.shape == (8, 8, 4)
    with pytest.raises(blitz_actor.TextureError):
        blitz_actor.texture(_texture()[:100])


def test_container_and_plugins_bind_textures_by_crc():
    pack = _pack([("t_wall", _texture()), ("o_thing", _dl_actor()), ("m_anim", _resinfo(1, 9) + bytes(300))])
    members = container.expand(pack)
    names = [n for n, _ in members]
    assert "o_thing.00001234.tba" in names and "t_wall.0000aaaa.tbt" in names
    assert not any(n.startswith("m_anim") for n in names), "animations are not actors"

    class Src:
        by_path = {f"pak.gcp/{n}": None for n in names}

        def get(self, p):
            return dict(members)[p.split("/", 1)[1]]

    src = Src()
    path = "pak.gcp/o_thing.00001234.tba"
    blob = dict(members)["o_thing.00001234.tba"]
    assert plugin.detect(path, blob[:64], len(blob))
    (scene,) = plugin.extract(blob, path, src)
    assert scene.materials[0].texture == "t_wall" and "t_wall" in scene.textures
    tex_blob = dict(members)["t_wall.0000aaaa.tbt"]
    (tex_scene,) = blitz_tbt.extract(tex_blob, "pak.gcp/t_wall.0000aaaa.tbt", None)
    assert tex_scene.textures["t_wall"].shape == (8, 8, 4)
