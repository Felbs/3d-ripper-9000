"""Visual Concepts ``SCNE`` scene records (gcrip.formats.vc_scene).

Synthetic fixtures exercise the two vertex layouts the real discs use:

* the 16-byte layout - ``[u16 u][s16 xyz][s8 normal][pad][u16 0][u16 v]`` - drawn by a GX
  display list (indexed-XF matrix loads, then a ``0x9a`` triangle strip with degenerate
  stitching), positions dequantized by the record's diagonal scale + translation matrix;
* the 14-byte colored layout - ``[u16 misc][u16 u][u16 v][s16 xyz][u16 RGB565]`` - whose
  array address is solved back from the display list by the median-edge oracle.

The pyramid below is the shape ``GLOBAL.IFF`` really contains (4 faces of 3 vertices, each
face's vertices sharing its face normal); the numbers are chosen so every dequantized
coordinate is exact in float32 and the test can compare byte-for-byte.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import vc_scene

SCALE = (0.0078125, 0.001953125, 0.03125)  # exact powers of two
TRANS = (-1.0, 16.0, 0.25)


def _record_header(payload: bytes) -> bytes:
    """16 bytes of member header, tag, size twice, zeros to +64 - the generic frame."""
    head = bytearray(16)
    head += b"ENCS"
    head += struct.pack(">II", len(payload) + 48, len(payload) + 48)
    head += bytes(20)
    head += b"ENCS" + struct.pack(">II", 64, 13)
    return bytes(head) + payload


def _dequant_bytes() -> bytes:
    m = np.eye(4, dtype=">f4")
    m[0, 0], m[1, 1], m[2, 2] = SCALE
    m[0, 3], m[1, 3], m[2, 3] = TRANS
    return m.tobytes()


PYRAMID = [
    # (x, y, z) quantized; four faces, apex at (0, 16384, 0)
    (-16384, -16384, -16384),
    (-16384, -16384, 16384),
    (0, 16384, 0),
    (-16384, -16384, 16384),
    (16384, -16384, 16384),
    (0, 16384, 0),
    (16384, -16384, 16384),
    (16384, -16384, -16384),
    (0, 16384, 0),
    (16384, -16384, -16384),
    (-16384, -16384, -16384),
    (0, 16384, 0),
]


def _face_normals() -> list[tuple[int, int, int]]:
    """The stored normals are model-space - they match the *dequantized* geometry - so the
    fixture computes them from the same faces the display list will draw."""
    pos = np.array(PYRAMID, np.float64) * SCALE + TRANS
    out = []
    for f in range(4):
        a, b, c = pos[3 * f : 3 * f + 3]
        g = np.cross(b - a, c - a)
        g = g / np.linalg.norm(g) * 63.0
        out.append(tuple(int(round(v)) for v in g))
    return out


def _vertex_array() -> bytes:
    normals = _face_normals()
    out = bytearray()
    for i, (x, y, z) in enumerate(PYRAMID):
        nx, ny, nz = normals[i // 3]
        out += struct.pack(">Hhhh3bB2H", 256, x, y, z, nx, ny, nz, 0, 0, 128)
    return bytes(out)


def _display_list() -> bytes:
    # load position matrix 0 to XF row 0, normal matrix 0 to 0x400, then one strip whose
    # degenerate stitching reduces to exactly the four faces: 0 1 2 2 3 3 4 5 5 ... b
    order = [0, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6, 7, 8, 8, 9, 9, 10, 11]
    dl = bytearray(b"\x20\x00\x00\xb0\x00\x28\x00\x00\x84\x00")
    dl += b"\x9a" + struct.pack(">H", len(order))
    for i in order:
        dl += bytes([0, i, i, i])
    return bytes(dl)


def _member() -> bytes:
    payload = _dequant_bytes() + bytes(32) + _vertex_array() + bytes(16) + _display_list()
    payload += bytes(32)
    return _record_header(payload)


def test_records_walk():
    member = _member()
    recs = vc_scene.records(member)
    assert len(recs) == 1
    at, tag, span = recs[0]
    assert at == 0 and tag == b"ENCS"
    assert vc_scene.is_scne(member)


def test_pyramid_meshes():
    got = vc_scene.meshes(_member())
    assert len(got) == 1
    mesh = got[0]
    assert mesh.base == 0
    assert mesh.congruence > 0.99
    tris = mesh.indices.reshape(-1, 3)
    assert len(tris) == 4
    # the strip's degenerates vanish and the faces come out in order
    assert sorted(tuple(sorted(t)) for t in tris) == [(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11)]
    # dequantization is exact: quantized * diag(scale) + translation
    want = np.array(PYRAMID, dtype=np.float32) * np.array(SCALE, np.float32) + np.array(
        TRANS, np.float32
    )
    assert np.array_equal(mesh.positions, want)
    assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0, atol=0.05)
    assert np.allclose(mesh.uvs[:, 0], 1.0)
    assert np.allclose(mesh.uvs[:, 1], 0.5)


def _colored_member() -> bytes:
    # a drum of 64 segments in two rings, strip around it: fine enough that its strip
    # edges are small next to its bounding box, as real meshes are
    verts = bytearray()
    import math

    ring = []
    for k in range(96):
        a = 2 * math.pi * k / 96
        # an aperiodic radius wobble breaks the drum's shift symmetry: a plain cylinder
        # solves a few entries off just as well, which a real mesh never does
        r = 12000 + 900 * math.sin(2.399 * k)
        ring.append((int(r * math.cos(a)), int(r * math.sin(a))))
    for lo in (0, 1):
        for x, z in ring:
            # a shallow band: its strip edges (chords and rungs alike) stay small next to
            # the bounding box, the shape real meshes have
            verts += struct.pack(">HhhhhhH", 1, 128 * lo, 128, x, -400 + 800 * lo, z, 0xFFFF)
    order = []
    for k in range(97):
        order += [k % 96, 96 + k % 96]
    dl = bytearray(b"\x20\x00\x00\xb0\x00")
    dl += b"\x9a" + struct.pack(">H", len(order))
    for i in order:
        dl += bytes([0, i, i, i])
    payload = _dequant_bytes() + bytes(24) + bytes(verts) + bytes(8) + bytes(dl) + bytes(32)
    return _record_header(payload)


def test_colored_layout_solved_by_address():
    member = _colored_member()
    got = vc_scene.meshes(member)
    assert len(got) == 1
    mesh = got[0]
    assert mesh.normals is None
    assert mesh.colors is not None
    assert np.allclose(mesh.colors, 1.0)  # 0xFFFF is white
    tris = mesh.indices.reshape(-1, 3)
    assert len(tris) == 192
    # the solved address is the real array: re-quantized ring radii land in the band the
    # fixture generated, which a one-entry-off solution would not
    ring = mesh.positions[mesh.indices]
    r = np.sqrt(
        ((ring[:, 0] - TRANS[0]) / SCALE[0]) ** 2 + ((ring[:, 2] - TRANS[2]) / SCALE[2]) ** 2
    )
    assert float(r.min()) > 11050 and float(r.max()) < 12950


def test_congruence_gate_rejects_shuffled_normals():
    member = bytearray(_member())
    recs = vc_scene.records(bytes(member))
    at, _tag, _span = recs[0]
    # find the vertex array inside the member and invert its normals' meaning by writing
    # sideways garbage - the solver must then decline the mesh rather than emit it
    arr_at = bytes(member).find(struct.pack(">Hhhh", 256, *PYRAMID[0]))
    rng = np.random.default_rng(7)
    for i in range(len(PYRAMID)):
        nx, ny, nz = rng.integers(-63, 63, 3)
        n = np.array([nx, ny, nz], float)
        n = (n / (np.linalg.norm(n) + 1e-9) * 64).astype(int)
        member[arr_at + i * 16 + 8 : arr_at + i * 16 + 11] = struct.pack(
            ">3b", int(n[0]), int(n[1]), int(n[2])
        )
    got = vc_scene.meshes(bytes(member))
    assert not got or all(m.congruence < 0.9 for m in got)


def test_not_a_scene():
    assert vc_scene.meshes(b"\0" * 64) == []
    assert vc_scene.records(b"\0" * 8) == []
