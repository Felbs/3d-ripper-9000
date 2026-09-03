"""RoadKill's CModel version 6 (gcrip.formats.tr_cmodel): headers first, payloads after,
each payload an SGCPacketHeader + 13-byte vertices + a big-endian index list at the offset
the header's second word gives."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import tr_cmodel, tr_smf
from gcrip.plugins import tr_smb as plugin

QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]


def payload(points, tris, pos_frac=13, nrm_frac=7, uv_frac=8) -> bytes:
    verts = b""
    for x, y, z in points:
        verts += struct.pack(
            ">3h", round(x * 2**pos_frac), round(y * 2**pos_frac), round(z * 2**pos_frac)
        )
        verts += struct.pack(">3b", 0, 0, 2**nrm_frac - 1)
        verts += struct.pack(">2h", round(x * 2**uv_frac), round(y * 2**uv_frac))
    index_at = 32 + len(verts)
    head = struct.pack(">8I", 0xCDCDCDCD, index_at, 0xCDCDCDCD, 0, pos_frac, nrm_frac, uv_frac, 1)
    body = head + verts + b"".join(struct.pack(">3H", *t) for t in tris)
    return body + bytes(-len(body) % 32)


def cmodel(objects, collision=0, frames=1) -> bytes:
    """``objects``: (name, points, triangles); one material ``car11.tif``; ``collision``
    meshes of one triangle each; ``frames`` > 1 adds the animation tables."""
    out = bytearray(struct.pack("<5I", 6, len(objects), collision, 1, frames))
    mat = bytearray(b"\0" * tr_cmodel.MATERIAL)
    mat[12:21] = b"car11.tif"
    out += struct.pack("<I", 6) + bytes(mat)
    for i in range(collision):
        out += f"LegacyCollisionPart{i}".encode().ljust(32, b"\xcd") + struct.pack("<3I", 1, 3, 1)
        out += struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0) + struct.pack("<3H", 0, 1, 2)
    out += struct.pack("<6f", -1, -1, -1, 1, 1, 1)
    bodies = []
    for name, points, tris in objects:
        body = payload(points, tris)
        bodies.append(body)
        out += name.encode().ljust(32, b"\0") + struct.pack("<H", 0) + struct.pack("<I", 2)
        out += struct.pack("<6f", -1, -1, -1, 1, 1, 1)
        out += struct.pack("<6I", 2, len(body), 1, len(points), len(tris), 0xCDCDCDCD)
    if frames > 1:
        n = len(objects) + collision
        out += bytes(2 * n) + bytes(28 * n * frames)
    for body in bodies:
        out += body
    return bytes(out)


def test_headers_first_then_payloads_in_object_order():
    data = cmodel(
        [("body", QUAD, [(0, 1, 2), (0, 2, 3)]), ("wheel", QUAD[:3], [(0, 1, 2)])], collision=1
    )
    assert tr_cmodel.is_cmodel(data[:24], len(data))
    m = tr_cmodel.parse(data)
    assert m.warnings == [] and m.materials == ["car11.tif"]
    assert [o.name for o in m.objects] == ["body", "wheel"]
    body, wheel = m.objects
    assert len(body.indices) == 6 and len(wheel.indices) == 3
    assert np.allclose(body.positions[2], [1, 1, 0], atol=1e-3)
    assert np.allclose(body.normals[0], [0, 0, 127 / 128], atol=1e-3)
    assert np.allclose(wheel.uvs[1], [1, 0], atol=1e-2)


def test_keyframe_tables_are_skipped_before_the_payloads():
    data = cmodel([("body", QUAD, [(0, 1, 2), (0, 2, 3)])], frames=3)
    m = tr_cmodel.parse(data)
    assert m.frames == 3 and m.warnings == [] and len(m.objects[0].indices) == 6


def test_the_smf_reader_and_the_smb_plugin_take_the_version_six_path():
    data = cmodel([("body", QUAD, [(0, 1, 2), (0, 2, 3)]), ("wheel", QUAD, [(0, 1, 2)])])
    smf = tr_smf.parse(data)
    assert smf is not None and [len(mm.indices) for mm in smf.meshes] == [6, 3]
    assert smf.meshes[0].material == "car11.tif"
    assert plugin.detect("files/GCMODEL.POD/MODELS/CAR11.SMB", data[:64], len(data))

    class Src:
        by_path = {}

        def get(self, p):
            raise KeyError(p)

    (scene,) = plugin.extract(data, "files/GCMODEL.POD/MODELS/CAR11.SMB", Src())
    assert scene.extras["format"] == "tr_cmodel" and scene.extras["parts"] == ["body", "wheel"]
    assert scene.materials[0].name == "car11"
