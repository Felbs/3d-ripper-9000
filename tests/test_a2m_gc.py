"""The .gc resource files - Teen Titans, Monster House, Ed Edd n Eddy, Ant Bully, Happy Feet."""

import struct
import zlib

import numpy as np

from gcrip.formats import a2m_gc
from gcrip.plugins import a2m_gc as plugin

TYPE = 91
FILE_ID = 0x0670
QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
MESH_AT = 64
VERTS_AT = 128
DL_AT = 352


def vertex(pos, normal=(0.0, 0.0, 1.0), uv=(0.0, 0.0), colour=0x808080FF):
    out = bytearray(a2m_gc.STRIDE)
    struct.pack_into(">3f", out, 0, *pos)
    struct.pack_into(">I", out, a2m_gc.COLOUR_AT, colour)
    struct.pack_into(">3f", out, a2m_gc.NORMAL_AT, *normal)
    struct.pack_into(">2f", out, a2m_gc.UV_AT, *uv)
    return bytes(out)


def resource(
    name="barrel",
    positions=QUAD,
    normal=(0.0, 0.0, 1.0),
    strip=(0, 1, 2, 3),
    count=None,
    dl_end=None,
    pad=b"\x00" * 5,
):
    """A resource whose payload holds one mesh: a quad as a four-vertex strip."""
    body = bytearray(DL_AT)
    body[0:4] = b"\xab\xab\xab\xab"
    struct.pack_into(">I", body, 12, (TYPE << 24) | (FILE_ID << 8))
    body[a2m_gc.RES_NAME_AT : a2m_gc.RES_NAME_AT + len(name)] = name.encode()
    body[48:64] = b"\xef" * 16
    struct.pack_into(">I", body, MESH_AT, len(positions) if count is None else count)
    struct.pack_into(">I", body, MESH_AT + 4, a2m_gc.SENTINEL)
    struct.pack_into(">I", body, MESH_AT + 8, VERTS_AT)
    for i, pos in enumerate(positions):
        body[VERTS_AT + i * a2m_gc.STRIDE : VERTS_AT + (i + 1) * a2m_gc.STRIDE] = vertex(
            pos, normal
        )
    dl = bytearray(b"\x98" + struct.pack(">H", len(strip)))
    for v in strip:
        dl += struct.pack(">4H", v, v, v, v)
    dl += pad
    struct.pack_into(">I", body, MESH_AT + 52, DL_AT)
    struct.pack_into(">I", body, MESH_AT + 56, DL_AT + len(dl) if dl_end is None else dl_end)
    return bytes(body) + bytes(dl)


def build(payload=None, handle_type=TYPE, offset=None):
    payload = resource() if payload is None else payload
    head = bytearray(a2m_gc.TABLE_AT + a2m_gc.SLOTS * a2m_gc.SLOT)
    struct.pack_into(">I", head, 0, 0x0301081F)
    head[a2m_gc.NAME_AT : a2m_gc.NAME_AT + 6] = b"ppdusk"
    head[a2m_gc.MAGIC_AT : a2m_gc.MAGIC_AT + 5] = a2m_gc.MAGIC
    for i in range(a2m_gc.SLOTS):
        struct.pack_into(">2I", head, a2m_gc.TABLE_AT + i * a2m_gc.SLOT, 0, a2m_gc.NO_TYPE)
    entries_at = len(head)
    data_at = entries_at + a2m_gc.SLOT
    struct.pack_into(">2I", head, a2m_gc.TABLE_AT + TYPE * a2m_gc.SLOT, 1, entries_at)
    entry = struct.pack(
        ">2I", (handle_type << 24) | (FILE_ID << 8), data_at if offset is None else offset
    )
    return bytes(head) + entry + payload


def test_detection_is_the_build_word_at_fifty_six():
    """It sits inside the 64 bytes classify sniffs, which is what makes it usable."""
    data = build()
    assert a2m_gc.is_gc(data[:64]) and plugin.detect("ppdusk.gc", data[:64], len(data))
    bad = bytearray(data)
    bad[a2m_gc.MAGIC_AT] = ord("X")
    assert not a2m_gc.is_gc(bytes(bad)[:64])


def test_a_resource_comes_out_named():
    (res,) = a2m_gc.resources(build())
    assert (res.kind, res.name) == (TYPE, "barrel")


def test_the_handle_must_repeat_its_own_slot_index():
    """The handle's top byte is the type; a slot whose entries disagree is not this format."""
    assert a2m_gc.resources(build(handle_type=TYPE + 1)) == []


def test_a_resource_with_no_payload_is_skipped():
    assert a2m_gc.resources(build(offset=a2m_gc.NO_PAYLOAD)) == []


def test_a_mesh_round_trips():
    (mesh,) = a2m_gc.meshes(resource(), "barrel")
    assert mesh.name == "barrel"
    assert len(mesh.positions) == 4 and len(mesh.indices) == 6
    assert np.allclose(mesh.positions[1], (1.0, 0.0, 0.0))
    assert mesh.unsigned_agreement > 0.99


def test_the_display_list_must_walk_to_its_declared_end():
    """Padding is zero or 0xef; anything else means the walk landed somewhere it should not."""
    assert a2m_gc.meshes(resource(pad=b"\x01\x02\x03")) == []
    assert a2m_gc.meshes(resource(pad=b"\xef" * 4)) != []


def test_an_index_outside_the_vertex_count_is_refused():
    assert a2m_gc.meshes(resource(strip=(0, 1, 2, 9))) == []


def test_a_list_that_leaves_a_vertex_unreferenced_is_refused():
    """Every vertex is used by the strip; a header pointing at the wrong array is not."""
    assert a2m_gc.meshes(resource(strip=(0, 1, 2, 0))) == []


def test_normals_that_are_not_unit_length_are_refused():
    """The stored normals are the anchor: if they are not unit vectors this is not a vertex
    array, whatever else lines up."""
    assert a2m_gc.meshes(resource(normal=(0.0, 0.0, 0.4))) == []


def test_triangles_are_flipped_to_agree_with_their_own_normals():
    """The winding is not consistent, as in Terminal Reality's _smf.  Raw, the signed
    agreement averages 0.41 across a real file while the unsigned figure is 0.90 to 1.00 -
    the triangles are right and their orientation is not."""
    (mesh,) = a2m_gc.meshes(resource(normal=(0.0, 0.0, -1.0)))
    tri = mesh.indices.reshape(-1, 3).astype(np.int64)
    a, b, c = mesh.positions[tri[:, 0]], mesh.positions[tri[:, 1]], mesh.positions[tri[:, 2]]
    face = np.cross(b - a, c - a)
    face /= np.linalg.norm(face, axis=1)[:, None]
    assert (face @ np.array([0.0, 0.0, -1.0]) > 0.99).all()


def blocks(*payloads):
    out = b""
    for p in payloads:
        packed = zlib.compress(p)
        out += struct.pack(">I", len(packed)) + packed
    return out


def test_a_cp_is_a_chain_of_sized_zlib_blocks():
    data = blocks(b"first block" * 40, b"second block" * 40)
    assert a2m_gc.is_cp(data[:8])
    assert a2m_gc.decompress(data) == b"first block" * 40 + b"second block" * 40


def test_reading_the_cp_as_one_continuous_chain_loses_every_block_but_the_first():
    """Letting each stream end and starting the next where it stopped skips the four-byte
    size in between, so only block one survives - and it still passes every header check,
    which is how dr_final.cp came back as a valid 53,248-byte file with no meshes in it."""
    data = blocks(b"a" * 500, b"b" * 500)
    naive = zlib.decompressobj()
    first = naive.decompress(data[4:])
    assert first == b"a" * 500
    assert len(a2m_gc.decompress(data)) == 1000


def test_the_cp_container_hands_back_a_gc_named_after_itself():
    data = blocks(build())
    assert plugin.is_container("dr_final.cp", data[:64])
    ((name, inner),) = plugin.expand(data)
    assert name == "ppdusk.gc" and a2m_gc.is_gc(inner[:64])


def test_the_plugin_builds_one_primitive_a_mesh():
    (scene,) = plugin.extract(build(), "files/ppdusk.gc", None)
    assert len(scene.primitives) == 1 and scene.triangles == 2
    assert scene.materials[0].name == "barrel"
    assert scene.primitives[0].colors is not None
