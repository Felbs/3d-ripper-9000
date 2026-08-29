"""Traveller's Tales GameCube DISP programs (.csc / .chg) and .fpk packs."""

import struct

import numpy as np

from gcrip.formats import ttdisp
from gcrip.plugins import ttdisp as plug


def chunk(tag: bytes, payload: bytes) -> bytes:
    return tag[::-1] + struct.pack(">I", len(payload) + 8) + payload


def make_csc() -> bytes:
    """One textured quad: NU20 (BE, reversed tags) with NTBL, TST0, MS00 and DISP."""
    ntbl = chunk(b"NTBL", struct.pack(">I", 6) + b"quad\0\0")
    # TST0: count, 4 pad, one 0x3c entry (u32 0 | w h | fmt mips | pixel offset from the
    # offset field), then 8x8 I8 pixels (64 bytes)
    pixels = bytes(range(64))
    entry = struct.pack(">IHHHHI", 0, 8, 8, 1, 1, 0x3C - 0xC) + bytes(0x3C - 0x10)
    tst0 = chunk(b"TST0", struct.pack(">II", 1, 0) + entry + pixels)
    # MS00: count then one 0x124-byte record (LEGO Star Wars II layout, fields relative to
    # the record start + 8 that the 0x80 command points at): texture 0 at word 62, diffuse
    # (1, 0.5, 0.25) at words 53-55
    rec = bytearray(0x124)
    struct.pack_into(">I", rec, 8 + 62 * 4, 0)
    struct.pack_into(">3f", rec, 8 + 53 * 4, 1.0, 0.5, 0.25)
    ms00 = chunk(b"MS00", struct.pack(">I", 1) + bytes(rec))
    # DISP payload, offsets relative to payload start P (chunk data = P + 8 in the file)
    hdr = bytearray(0x40)
    stream_off = 0x40
    matrix_off = 0xC0
    desc_off = 0x100
    entry_off = 0x180
    pos_off = 0x1A0
    uv_off = 0x1C0
    dl_off = 0x1E0
    body = bytearray(0x200)
    # stream: 85 (block link) | 80 material (pointer into MS00, patched below) | 8b |
    # 83 matrix | 82 mesh | 8e end
    cmds = [
        bytes([0x85, 1, 0, 0]) + struct.pack(">I", 0x18),
        bytes([0x80, 3, 0, 0]) + bytes(4),  # patched: self-relative to the MS00 record
        bytes([0x8B, 1, 0, 0]) + bytes(4),
        bytes([0x83, 0, 0, 0]) + struct.pack(">I", matrix_off - (stream_off + 3 * 8 + 4)),
        bytes([0x82, 0, 0, 0]) + struct.pack(">I", desc_off - (stream_off + 4 * 8 + 4)),
        bytes([0x8E, 0, 0, 0]) + bytes(4),
    ]
    body[stream_off : stream_off + 48] = b"".join(cmds)
    struct.pack_into(">I", hdr, 8, stream_off - 8)  # word 2 -> stream (self-relative)
    struct.pack_into(">I", hdr, 16, 1)  # one draw-table entry
    struct.pack_into(">I", hdr, 20, entry_off - 20)  # word 5 -> table
    # 3x4 matrix: translate by (1, 2, 3)
    m = np.eye(4, dtype=">f4")
    m[0, 3], m[1, 3], m[2, 3] = 1, 2, 3
    body[matrix_off : matrix_off + 64] = m.tobytes()
    # draw-table entry: count 1, A -> (material 0, 0), B -> command index 4 (the 0x82)
    a_off, b_off = entry_off + 12, entry_off + 20
    body[entry_off : entry_off + 12] = struct.pack(
        ">3I", 1, a_off - (entry_off + 4), b_off - (entry_off + 8)
    )
    body[a_off : a_off + 8] = struct.pack(">2I", 0, 0)
    body[b_off : b_off + 4] = struct.pack(">I", 4)
    # descriptor: fmt = pos u8 + uv u8 (0x3003), 4 vertices, uv array at [5], DL at [8]
    desc = bytearray(0x60)
    struct.pack_into(">HH", desc, 2, 0x3003, 4)
    struct.pack_into(">I", desc, 0x14, uv_off - (desc_off + 0x14))
    struct.pack_into(">I", desc, 0x20, dl_off - (desc_off + 0x20))
    struct.pack_into(">I", desc, 0x24, 16)
    struct.pack_into(">I", desc, 0x4C, pos_off - (desc_off + 0x4C))
    body[desc_off : desc_off + 0x60] = desc
    body[pos_off : pos_off + 24] = struct.pack(
        ">12h", 0, 0, 0, 1024, 0, 0, 1024, 1024, 0, 0, 1024, 0
    )
    body[uv_off : uv_off + 8] = bytes([0, 0, 255, 0, 255, 255, 0, 255])
    body[dl_off : dl_off + 11] = bytes([0x98, 0, 4, 0, 0, 1, 1, 2, 2, 3, 3])
    disp_payload = bytes(hdr) + bytes(body[0x40:])
    head = b"02UN" + struct.pack(">I", 0) + struct.pack(">II", 2, 0)
    pre = head + ntbl + tst0 + ms00
    disp_start = len(pre)
    # patch the 0x80 pointer: field at disp_start + 8 + stream_off + 8 + 4 -> MS00 record
    ms_record = len(head) + len(ntbl) + len(tst0) + 8 + 4 + 8  # 0x80 targets start + 8
    field_pos = disp_start + 8 + stream_off + 8 + 4
    data = bytearray(pre + chunk(b"DISP", disp_payload))
    struct.pack_into(">I", data, field_pos, (ms_record - field_pos) & 0xFFFFFFFF)
    return bytes(data)


def test_ttdisp_csc():
    data = make_csc()
    assert ttdisp.is_csc(data[:0x14])
    model = ttdisp.parse(data)
    assert len(model.textures) == 1 and model.textures[0].rgba is not None
    assert len(model.materials) == 1 and model.materials[0].texture == 0
    assert model.materials[0].diffuse == (1.0, 0.5, 0.25)
    assert len(model.meshes) == 1
    m = model.meshes[0]
    assert m.material == 0 and len(m.indices) == 6
    np.testing.assert_allclose(m.positions[2], [2.0, 3.0, 3.0])  # (1,1,0) + (1,2,3)
    np.testing.assert_allclose(m.uvs[2], [1.0, 1.0])
    assert plug.detect("Chars/quad.csc", data[:64], len(data))
    scene = plug.extract(data, "Chars/quad.csc", None)[0]
    assert scene.triangles == 2 and scene.materials[0].texture == "tex000"


def test_ttdisp_pack():
    names = b"chars\\a\\WALK.CA3\0chars\\b\\IDLE.CA3\0"
    entries = struct.pack("<7I", 0x18 + 56, 0x80, 4, 0x10, 0, 0, 0)
    entries += struct.pack("<7I", 0x18 + 56 + 17, 0x84, 3, 0x10, 0, 0, 0)
    head = b"zV4\x12" + struct.pack("<I", 2) + bytes(16)
    data = (head + entries + names).ljust(0x80, b"\0") + b"ANI4" + b"ABC"
    assert plug.is_container("Chars/x.fpk", data[:16])
    assert plug.expand(data) == [("WALK.CA3", b"ANI4"), ("IDLE.CA3", b"ABC")]
