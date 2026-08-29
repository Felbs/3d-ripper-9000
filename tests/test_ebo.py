"""EA Sports EBO objects: a synthetic geometry file with one display list."""

import struct

import numpy as np

from gcrip.formats import ebo
from gcrip.plugins import ebo as plug

TYPES = ["Geometry", "GcDisplayList", "GCVertexStream", "Float3", "Short2", "i8"]


def build_ebo() -> bytes:
    """Header | records + payload | type table | (no imports) | export | strings.
    Payload: command buffer (32-byte struct then a 4-vertex strip at stride 5), then
    positions (Float3, header {size, 12, off}) and UVs (Short2, header {size, 4, off})."""
    strtab = bytearray(b"\0")
    offs = {}
    for s in TYPES + ["quad"]:
        offs[s] = len(strtab)
        strtab += s.encode() + b"\0"
    body = bytearray(0x60)  # header placeholder
    # records: 16 bytes each; the i8 stream records point at their bytes (record + off)
    rec_dl, rec_pos, rec_uv = 0x60, 0x70, 0x80
    body += bytes(0x30)  # three records, filled below
    body += bytes(0x10)  # gap
    dl_struct = len(body)
    body += struct.pack(">I", 3 + 16 * 2) + bytes(28)
    dl_start = len(body)
    dl = bytearray(b"\x98\x00\x10")
    for i in range(16):  # 16-entry streams -> u8 indices: [pos][uv]
        dl += struct.pack(">BB", i, i)
    body += dl
    body += bytes(-len(body) % 16)
    # positions with header
    pos = np.array([[i % 2, i // 2, 0] for i in range(16)], ">f4")
    pos_hdr = len(body)
    body += struct.pack(">III", 16 * 12, 12, pos_hdr + 12)
    body += pos.tobytes()
    uv = np.array([[1024 * (i % 2), 64 * i] for i in range(16)], ">i2")
    uv_hdr = len(body)
    body += struct.pack(">III", 16 * 4, 4, uv_hdr + 12)
    body += uv.tobytes()
    body += bytes(-len(body) % 16)
    i8 = TYPES.index("i8")
    struct.pack_into("<IHHII", body, rec_dl, dl_struct - rec_dl, 1, i8, 32 + 3 + 32, 0)
    struct.pack_into("<IHHII", body, rec_pos, pos_hdr + 12 - rec_pos, 1, i8, 16 * 12, 0)
    struct.pack_into("<IHHII", body, rec_uv, uv_hdr + 12 - rec_uv, 1, i8, 16 * 4, 0)
    t_types = len(body)
    body += b"".join(struct.pack("<I", offs[s]) for s in TYPES)
    t_imp = len(body)
    t_exp = len(body)
    body += struct.pack("<III", offs["Geometry"], offs["quad"], 0xFFFF0000 | dl_struct)
    t_str = len(body)
    body += strtab
    struct.pack_into("<4sIIHHIIIII", body, 0, b"EBO\0", 0x11, len(body), 1, 1, 0x60,
                     t_types, t_imp, t_exp, t_str)
    assert dl_start > 0
    return bytes(body)


def test_parse_and_geometry():
    data = build_ebo()
    assert ebo.is_ebo(data[:64])
    obj = ebo.parse(data)
    assert obj.types == TYPES
    assert [(e.type, e.name) for e in obj.exports] == [("Geometry", "quad")]
    streams = ebo._streams(obj)
    assert [s.stride for s in streams] == [0, 12, 4]
    meshes = ebo.geometry(obj)
    assert len(meshes) == 1
    m = meshes[0]
    assert m.name == "quad" and m.positions.shape == (16, 3) and len(m.indices) == 14 * 3
    assert m.uvs is not None and m.uvs[15].tolist() == [1.0, 15 * 64 / 1024]


def test_plugin():
    data = build_ebo()
    assert plug.detect("gamedata/players.viv/player2.ebo", data[:64], len(data))
    assert not plug.detect("gamedata/x.bin", data[:64], len(data))
    scenes = plug.extract(data, "players.viv/player2.ebo", None)
    assert len(scenes) == 1 and len(scenes[0].primitives) == 1
    assert scenes[0].extras["format"] == "ebo"
