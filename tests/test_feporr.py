"""Fire Emblem: Path of Radiance containers and .gs geometry on synthetic files: LZ10 stream,
pack archive, a static textured triangle, and a skinned triangle drawn from the skin block."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import feporr_gs as gs
from gcrip.formats import feporr_pack as fp
from gcrip.plugins import feporr

BASE = 0x20


def _tpl_rgb5a3() -> bytes:
    head = struct.pack(">III", 0x0020AF30, 1, 0x0C) + struct.pack(">II", 0x14, 0)
    img = struct.pack(">HHIIIIII", 4, 4, 5, 0x34, 0, 0, 1, 1) + struct.pack(">fBBBB", 0, 0, 0, 0, 0)
    return head + img + struct.pack(">16H", *([0x801F] * 16))  # opaque blue


def _pack(members: list[tuple[str, bytes]]) -> bytes:
    names = b""
    name_offs = []
    base = 8 + 16 * len(members)
    for n, _ in members:
        name_offs.append(base + len(names))
        names += n.encode() + b"\0"
    data_pos = base + len(names)
    data_pos += (-data_pos) % 0x20
    out = b"pack" + struct.pack(">HH", len(members), 0)
    blobs = b""
    for (_, b), no in zip(members, name_offs, strict=True):
        out += struct.pack(">4I", 0, no, data_pos + len(blobs), len(b))
        blobs += b + b"\0" * ((-len(b)) % 0x20)
    out += names
    out += b"\0" * (data_pos - len(out))
    return out + blobs


class _Builder:
    def __init__(self) -> None:
        self.body = bytearray(b"\0" * 0x64)  # main-data body, rel offsets from 0x20
        self.relocs: list[int] = []

    def add(self, blob: bytes, align: int = 4) -> int:
        self.body += b"\0" * ((-len(self.body)) % align)
        off = len(self.body)
        self.body += blob
        return off

    def ptr(self, at: int, rel: int) -> None:
        struct.pack_into(">I", self.body, at, rel)
        self.relocs.append(at)


def _gs(skinned: bool = False) -> bytes:
    b = _Builder()
    name = b.add(b"tri\0")
    mat_name = b.add(b"lambert1\0")
    shape_name = b.add(b"none\0")
    if skinned:
        pos = nrm = 0
        n_pos = n_nrm = 0
    else:
        pos = b.add(struct.pack(">9h", 0, 0, 0, 100, 0, 0, 0, 100, 0))
        nrm = b.add(struct.pack(">3b", 0, 0, 64))
        n_pos, n_nrm = 3, 1
    tex = b.add(struct.pack(">6h", 0, 0, 1, 0, 0, 1))
    sampler = b.add(struct.pack(">HHBBBB", 1, 0, 0, 0, 1, 1) + b"\0" * 8 + struct.pack(">ff", 1, 1))
    colours = (200, 200, 200, 255, 0, 0, 0, 255, 0, 0, 0, 0)
    mat = b.add(struct.pack(">II12BIII", 0, 0x100, *colours, 0, 0, 0))
    b.ptr(mat, mat_name)
    b.ptr(mat + 0x14, sampler)
    shape = b.add(struct.pack(">I6fHHI", 0, 0, 0, 0, 1, 1, 0, 1, 0, 0))
    b.ptr(shape, shape_name)
    vf = 0x4600 | (0x800000 if skinned else 0)
    dl = struct.pack(">BH", 0x90, 3) + struct.pack(">9H", 0, 0, 0, 1, 0, 1, 2, 0, 2)
    dl_off = b.add(dl + b"\0" * ((-len(dl)) % 0x20), 0x20)
    rec = b.add(struct.pack(">IIBBBBHHIIII", 0, 0, 0x30, 0, 0, 0, 0, 0, vf, 0, len(dl), 0))
    b.ptr(rec, shape)
    b.ptr(rec + 0x14, dl_off)
    skin = 0
    if skinned:
        env = struct.pack(">4H4BIHBBHH", 2, 5, 0xFFFF, 0xFFFF, 128, 128, 0, 0, 0, 36, 0, 2, 3, 0)
        head = struct.pack(">IIHHHH", 0x10, 0x10 + len(env), 1, 3, 0, 0)
        rows = struct.pack(">18h", 0, 0, 0, 0, 0, 256, 256, 0, 0, 0, 0, 256, 0, 256, 0, 0, 0, 256)
        skin = b.add(head + env + rows, 0x20)
    # header
    b.ptr(0x00, name)
    b.ptr(0x24, pos)
    b.ptr(0x28, nrm)
    b.ptr(0x2C, tex)
    b.ptr(0x34, mat)
    b.ptr(0x38, shape)
    b.ptr(0x3C, rec)
    if skinned:
        b.ptr(0x48, skin)
    struct.pack_into(">8H", b.body, 0x4C, n_pos, n_nrm, 3, 0, 1, 1, 1, 0)
    b.body[0x5C:0x5F] = bytes([0, 6, 0])
    reloc = b.add(struct.pack(f">{len(b.relocs)}I", *b.relocs), 4)
    total = BASE + len(b.body)
    return struct.pack(">III", total, reloc, len(b.relocs)) + b"\0" * 0x14 + bytes(b.body)


def test_lz10_and_pack():
    stream = b"\x10" + (16).to_bytes(3, "little") + b"\x00" + b"abcdefgh" + b"\x80\x50\x07"
    assert fp.is_lz10(stream)
    assert fp.lz10_decompress(stream) == b"abcdefghabcdefgh"
    pack = _pack([("a.gs", b"AAAA"), ("texpack.tpl", _tpl_rgb5a3())])
    assert fp.is_pack(pack)
    members = fp.pack_members(pack)
    assert [n for n, _ in members] == ["a.gs", "texpack.tpl"]
    assert members[0][1] == b"AAAA"
    assert members[1][1][:4] == b"\x00\x20\xaf\x30"
    assert feporr.is_container("map.cmp", stream[:64])
    assert not feporr.is_container("map.bin", stream[:64])
    assert feporr.is_container("x.pak", pack[:64])
    assert feporr.expand(pack)[0][0] == "a.gs"
    compressed_tpl = b"\x10" + len(_tpl_rgb5a3()).to_bytes(3, "little")
    raw = _tpl_rgb5a3()
    body = b""
    for i in range(0, len(raw), 8):
        chunk = raw[i : i + 8]
        body += b"\x00" + chunk
    assert feporr.expand(compressed_tpl + body) == [("image.tpl", raw)]


class _Src:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.by_path = files

    def get(self, path: str) -> bytes:
        return self.by_path[path]


def test_static_triangle():
    data = _gs()
    assert gs.looks_like_gs(data[:64], len(data))
    assert feporr.detect("xwp/sword/sword.cmp/sword.gs", data[:64], len(data))
    model = gs.parse(data)
    assert model.name == "tri" and len(model.records) == 1 and model.skinned == 0
    rec = model.records[0]
    assert rec.positions.shape == (3, 3) and np.allclose(rec.positions.max(), 100.0)
    assert rec.normals is not None and np.allclose(rec.normals[0], [0, 0, 1])
    assert rec.uvs is not None and rec.uvs.max() == 1.0
    src = _Src({"xwp/sword/sword.cmp/texpack.tpl": _tpl_rgb5a3()})
    scenes = feporr.extract(data, "xwp/sword/sword.cmp/sword.gs", src)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.triangles == 1
    assert scene.materials[0].texture == "image0" and "image0" in scene.textures
    assert scene.textures["image0"].shape == (4, 4, 4)
    assert scene.materials[0].name == "lambert1"


def test_skinned_triangle_from_skin_block():
    data = _gs(skinned=True)
    model = gs.parse(data)
    assert model.skinned == 1 and len(model.records) == 1
    rec = model.records[0]
    assert np.allclose(sorted(rec.positions[:, 0].tolist()), [0.0, 0.0, 1.0])
    assert rec.bones is not None and rec.weights is not None
    assert rec.bones[0].tolist() == [2, 5, 0, 0]
    assert np.allclose(rec.weights[0], [0.5, 0.5, 0, 0])
    assert model.bone_count == 6
    scenes = feporr.extract(data, "zu/amr1/amr1_ja.pak/amr1.gs", _Src({}))
    assert scenes and scenes[0].triangles == 1
