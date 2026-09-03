"""4x4 Evo 2 ``.SMB`` models (gcrip.formats.tr_smb): C3DModel parts holding a GX packet
(16-byte big-endian vertices behind the SGCPacketHeader) or keyframed SVertex arrays."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import tr_smb, tr_smf
from gcrip.plugins import tr_smb as plugin


def gx_packet(quad, pos_frac=10, nrm_frac=15, uv_frac=8) -> bytes:
    """A triangle list of the quad's two triangles: SGCPacketHeader, preamble, 0x94 list."""
    verts = b""
    for i in (0, 1, 2, 0, 2, 3):
        x, y, z = quad[i]
        verts += struct.pack(
            ">3h", round(x * 2**pos_frac), round(y * 2**pos_frac), round(z * 2**pos_frac)
        )
        verts += struct.pack(">3h", 0, 0, 2**nrm_frac - 1)
        verts += struct.pack(">2h", round(x * 2**uv_frac), round(y * 2**uv_frac))
    body = b"\x00\x94" + struct.pack(">H", 6) + verts
    body += bytes(-len(body) % 32)
    head = struct.pack(">8I", len(body) + 8, len(body) + 12, 32, 0, pos_frac, nrm_frac, uv_frac, 1)
    return head + body  # the "preamble" of tr_smf is the last two header words


def part(
    name: bytes, texture: bytes, nv: int, nf: int, nt: int, body: bytes, packet: bool
) -> bytes:
    out = (name + b"\0").ljust(32, b"\xcd") + struct.pack("<I", 1) + struct.pack("<3I", nv, nf, nt)
    mat = bytearray(b"\xcd" * tr_smb.MATERIAL)
    struct.pack_into("<3f", mat, 0, 1.0, 1.0, 32.0)
    mat[32 : 32 + len(texture) + 1] = texture + b"\0"
    out += bytes(mat)
    if packet:
        out += struct.pack("<7I", 2, len(body), 1, nv, nt, 0xCDCDCDCD, 0) + body
        out += struct.pack("<6f", -1, -1, 0, 1, 1, 0)
    else:
        out += body
    return out


QUAD = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]


def make_smb() -> bytes:
    packet = gx_packet(QUAD)
    frames = b""
    for f in range(3):  # three keyframes; frame 0 is the rest pose
        for x, y, z in QUAD:
            frames += struct.pack("<8f", x, y + f, z, 0, 0, 1, x, y)
    frames += struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    head = struct.pack("<3If", 1, 2, 1, 50.0)
    return (
        head
        + part(b"OPAQUE", b"GSTATUE.TIF", 6, 1, 2, packet, True)
        + part(b"opaque", b"CR4BFOOT.TIF", 4, 3, 2, frames, False)
    )


def test_detects_and_reads_both_part_kinds():
    data = make_smb()
    assert tr_smb.is_smb(data[:64], len(data))
    assert plugin.detect("files/GCMODEL.POD/MODELS/!STATUE.SMB", data[:64], len(data))
    model = tr_smb.parse(data)
    assert model.warnings == []
    assert [p.name for p in model.parts] == ["OPAQUE", "opaque"]
    assert [p.material for p in model.parts] == ["GSTATUE.TIF", "CR4BFOOT.TIF"]
    gx, kf = model.parts
    assert len(gx.indices) == 6 and np.allclose(gx.positions[1], [1, 0, 0], atol=1e-3)
    assert np.allclose(gx.normals[0], [0, 0, 1], atol=1e-3)
    assert np.allclose(gx.uvs[2], [1, 1], atol=1e-2)
    assert kf.frames == 3 and kf.positions.tolist() == [list(q) for q in QUAD]
    assert kf.indices.tolist() == [0, 1, 2, 0, 2, 3]


def test_the_packet_header_fraction_bits_scale_the_vertices():
    """4x4 writes positions with 10 fraction bits where BloodRayne's SMF used 15."""
    data = gx_packet(QUAD, pos_frac=12)
    q = data.find(tr_smf.SIGNATURE)
    p = tr_smf.packet_header(data, q)
    assert p is not None and (p.pos_frac, p.nrm_frac, p.uv_frac, p.kind) == (12, 15, 8, 1)
    smb = struct.pack("<3If", 1, 1, 1, 50.0) + part(b"OPAQUE", b"A.TIF", 6, 1, 2, data, True)
    (gx,) = tr_smb.parse(smb).parts
    assert np.allclose(gx.positions[2], [1, 1, 0], atol=1e-3)


def test_the_plugin_binds_textures_by_stem_from_tif_raw_or_tex():
    from tests.test_tr_tex import build_cmpr

    files = {
        "files/GCMODEL.POD/MODELS/!STATUE.SMB": make_smb(),
        "files/ART.POD/ART/GSTATUE.RAW": build_cmpr(),
    }

    class Src:
        by_path = dict.fromkeys(files)

        def get(self, p):
            return files[p]

    (scene,) = plugin.extract(
        files["files/GCMODEL.POD/MODELS/!STATUE.SMB"], "files/GCMODEL.POD/MODELS/!STATUE.SMB", Src()
    )
    assert scene.materials[0].texture == "GSTATUE" and "GSTATUE" in scene.textures
    assert scene.materials[1].texture is None  # CR4BFOOT.TIF is not on this disc
    assert scene.extras["frames"] == 3
