"""Billy Hatcher .prd packages and .arc Ginja models."""

import struct

import numpy as np

from gcrip.formats import billy, prd, prs
from gcrip.plugins import billy as plug


def make_arc() -> bytes:
    # one object at 0x60 with a triangle strip over four float positions + u8 uv indices
    verts = struct.pack(">12f", 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0)
    uvs = struct.pack(">8h", 0, 0, 256, 0, 256, 256, 0, 256)
    vsets = 0x60 + 0x5C
    verts_off = vsets + 48
    uvs_off = verts_off + len(verts)
    params_off = uvs_off + len(uvs)
    prims_off = params_off + 16
    prims = bytes([0x98, 0, 4, 0, 0, 1, 1, 2, 2, 3, 3]) + bytes(5)
    record_off = prims_off + len(prims)
    gvm_off = record_off + 16
    table = gvm_off + 32
    total = table + 8
    rel = lambda o: o - 0x20  # noqa: E731
    hdr = struct.pack(">3I", total, table, 0x38) + bytes(8) + b"0100" + bytes(8)
    hdr += struct.pack(">I", rel(0x40)).ljust(0x20, b"\0")
    hdr += struct.pack(">2I", rel(0x60), 0).ljust(0x20, b"\0")
    obj = struct.pack(">2I", 7, 0x78) + struct.pack(">3f", 1, 2, 3) + bytes(12)
    obj += struct.pack(">3f", 1, 1, 1) + struct.pack(">3I", 0, 0, 0xFDFDFDFD)
    obj += struct.pack(">5I", rel(vsets), 0, rel(record_off), 0, 1 << 16) + bytes(16)
    assert len(obj) == 0x5C
    vs = struct.pack(">BBHII", 1, 12, 4, 0x40, rel(verts_off)) + bytes(4)
    vs += struct.pack(">BBHII", 5, 4, 4, 0x30, rel(uvs_off)) + bytes(4)
    vs += bytes([0xFF]) + bytes(15)
    params = struct.pack(">BBHI", 1, 0, 0, 0x808) + struct.pack(">BBHI", 8, 0, 0, 3)
    record = struct.pack(">4I", rel(params_off), 2, rel(prims_off), len(prims))
    gvm = b"GVMH" + bytes(28)
    data = hdr + obj + vs + verts + uvs + params + prims + record + gvm + bytes(8)
    assert len(data) == total
    return data


def test_billy_arc():
    data = make_arc()
    assert billy.is_arc(data[:0x60], len(data))
    meshes, textures = billy.parse(data)
    assert len(meshes) == 1 and textures == []
    m = meshes[0]
    assert m.texture == 3
    assert m.indices.tolist() == [0, 1, 2, 1, 3, 2]
    np.testing.assert_allclose(m.positions[3], [1, 3, 3])
    np.testing.assert_allclose(m.uvs[2], [1, 1])
    assert plug.detect("x/item.arc", data[:64], len(data))
    scenes = plug.extract(data, "x/item.arc", None)
    assert scenes[0].triangles == 2 and scenes[0].materials[0].name == "tex3"


def prs_literals(raw: bytes) -> bytes:
    """PRS stream of literals only: a flag byte (LSB first) per 8 bytes, then the end marker."""
    out = bytearray()
    full, rest = divmod(len(raw), 8)
    for i in range(full):
        out.append(0xFF)
        out += raw[i * 8 : i * 8 + 8]
    tail = raw[full * 8 :]
    if rest <= 6:  # literal bits, then 0,1 (long copy) in the same flag byte
        out.append(((1 << rest) - 1) | (1 << (rest + 1)))
        out += tail
    else:  # 7 literals + the 0 bit; the 1 bit starts a new flag byte
        out.append(0x7F)
        out += tail
        out.append(1)
    out += bytes(2)  # long copy with v == 0 ends the stream
    return bytes(out)


def test_prd_package():
    names = b"a.arc\0b.bin\0"
    table = struct.pack(">3I", 1, 0, 3)
    table += struct.pack(">3I", 0, 0x60, 4) + struct.pack(">3I", 6, 0x64, 2)
    inner = (prd.MAGIC + struct.pack(">3I", 0x20, len(names), 0x60)).ljust(0x20, b"\0")
    inner = (inner + table + names).ljust(0x60, b"\0") + b"ARC!" + b"BB"
    packed = prs_literals(inner)
    assert prs.decompress(packed) == inner
    head = struct.pack(">5I", 1, len(inner), len(packed), 0, 0).ljust(0x20, b"\0")
    data = head + packed
    assert prd.is_prd(data[:0x20])
    assert plug.is_container("files/k_x.prd", data[:0x20])
    assert plug.expand(data) == [("a.arc", b"ARC!"), ("b.bin", b"BB")]
