"""EA Canada EAGL objects: a synthetic .ord/.orp pair with one skinned render packet."""

import struct

import pytest
import numpy as np

from gcrip.formats import eagl
from gcrip.plugins import eagl as plug

SHADER = "LitTextureEnvIrrad2x_Skin"
TAR = "__EAGL::TAR:::RUNTIME_ALLOC::UID=1;SHAPENAME=Body,25;;"


def build_object() -> tuple[bytes, bytes, int]:
    """One packet: 4 vertices (a quad as a strip), positions s16, normals s8, UVs s16,
    stride-10 display list with matrix bytes; symbols for the model, a bone and a TAR."""
    data = bytearray(0x480)
    relocs: list[tuple[int, int]] = []  # (.data offset, symbol index)
    # symbol table: 0 null, 1 = .data section, 2 shader, 3 TAR, 4 anim buffer, 5 const matrix,
    # 6 GeoPrimState, 7 __Model, 8 __Bone
    names = [
        "",
        "",
        SHADER,
        TAR,
        "__MATRIX4 *:::EAGLAnimationBuffer",
        "__const MATRIX4:::EAGL::ViewPort::gpModelViewMatrix",
        "__EAGL::GeoPrimState:::RUNTIME_ALLOC::UID=2;;",
        "__Model:::Test__model1__.o_temp.variation1",
        "__Bone:::Test__model1__.Hips",
        "__Bone:::Test__model1__.Spine",
        "__Skeleton:::Test__model1__",
    ]
    # streams
    pos = np.array([[0, 0, 0], [256, 0, 0], [0, 256, 0], [256, 256, 0]], ">i2")
    nrm = np.array([[0, 0, 127]] * 4, np.int8)
    uv = np.array([[0, 0], [256, 0], [0, 256], [256, 256]], ">i2")
    P_POS, P_NRM, P_UV, P_DL, P_PAL = 0x40, 0x60, 0x80, 0xA0, 0x100
    data[P_POS : P_POS + 24] = pos.tobytes()
    data[P_NRM : P_NRM + 12] = nrm.tobytes()
    data[P_UV : P_UV + 16] = uv.tobytes()
    dl = bytearray(b"\x98\x00\x04")
    for i in range(4):
        dl += bytes([3, 33]) + struct.pack(">HHH", i, i, i)
    dl += b"\0" * (-len(dl) % 32)
    data[P_DL : P_DL + len(dl)] = dl
    # skin table: two GX matrix slots; slot 1 = bone 1 at weight 1.0 (bone index lives in
    # the low mantissa byte of each weight float)
    w1 = struct.unpack(">I", struct.pack(">f", 1.0))[0]
    data[P_PAL : P_PAL + 32] = struct.pack(">8I", w1 | 0, 0, 0, 0, w1 | 1, 0, 0, 0)
    # skeleton @0x380: header + two 112-byte records (Hips root, Spine child at +10 y)
    SK = 0x380
    data[SK : SK + 16] = bytes.fromhex("c0da01fec0da0000") + struct.pack(">II", 2, 0)
    inv0 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    inv1 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -10, 0, 1]
    for k, (parent, ty, inv) in enumerate([(-1, 0.0, inv0), (0, 10.0, inv1)]):
        rec = struct.pack(">3fi4f3fi", 1, 1, 1, parent, 0, 0, 0, 1, 0, ty, 0, k)
        rec += struct.pack(">16f", *inv)
        data[SK + 16 + k * 112 : SK + 16 + (k + 1) * 112] = rec
    struct.pack_into(">I", data, 0x360, 0)  # __Bone Hips -> record 0
    struct.pack_into(">I", data, 0x364, 1)  # __Bone Spine -> record 1
    # packet at 0x200: 0x1c bytes of header floats/flags, then shader ptr, palette ptr,
    # then (count, ptr) pairs
    PK = 0x200
    o = PK + 0x1C

    def put_ptr(off, value, sym):
        struct.pack_into("<I", data, off, value)
        relocs.append((off, sym))

    put_ptr(o, 0, 2)  # shader
    put_ptr(o + 4, P_PAL, 1)  # matrix palette (uncounted)
    pairs = [
        (1, (0, 1)),
        (1, (0, 4)),
        (2, (P_PAL, 1)),
        (1, (0, 5)),
        (4, (P_POS, 1)),
        (4, (P_NRM, 1)),
        (4, (P_UV, 1)),
        (len(dl), (P_DL, 1)),
        (1, (0, 3)),
        (1, (0, 6)),
        (1, (PK, 1)),
        (0, (0, 1)),
    ]
    o += 8
    for count, (value, sym) in pairs:
        struct.pack_into(">I", data, o, count)
        put_ptr(o + 4, value, sym)
        o += 8
    # __Model struct at 0x300 -> render list at 0x340 -> packet
    put_ptr(0x300, 0x340, 1)
    put_ptr(0x340, 0x360, 1)
    struct.pack_into(">II", data, 0x344, 0x100002, 1)
    put_ptr(0x34C, PK, 1)
    # symbols
    strtab = bytearray(b"\0")
    name_off = []
    for n in names:
        name_off.append(len(strtab) if n else 0)
        if n:
            strtab += n.encode() + b"\0"
    symtab = bytearray()
    values = [0, 0, 0, 0, 0, 0, 0, 0x300, 0x360, 0x364, 0x380]
    shndx = [0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1]
    for i in range(len(names)):
        symtab += struct.pack("<IIIBBH", name_off[i], values[i], 4, 0, 0, shndx[i])
    rel = b"".join(struct.pack("<II", off, (sym << 8) | 2) for off, sym in relocs)
    shstr = b"\0.data\0.shstrtab\0.strtab\0.symtab\0.rel.data\0"
    # layout: ELF header (0x34) | .data @0x40 | shstrtab | strtab | symtab | rel | section headers
    body = bytearray(b"\0" * 0x40)
    off_data = len(body)
    body += data
    off_shstr = len(body)
    body += shstr
    off_str = len(body)
    body += strtab
    body += b"\0" * (-len(body) % 4)
    off_sym = len(body)
    body += symtab
    off_rel = len(body)
    body += rel
    body += b"\0" * (-len(body) % 4)
    e_shoff = len(body)
    sections = [
        (0, 0, 0, 0),
        (1, off_data, len(data), 1),
        (7, off_shstr, len(shstr), 3),
        (17, off_str, len(strtab), 3),
        (25, off_sym, len(symtab), 2),
        (33, off_rel, len(rel), 9),
    ]
    for name, off, size, typ in sections:
        link = 4 if typ == 9 else (3 if typ == 2 else 0)
        info = 1 if typ in (2, 9) else 0
        entsize = 16 if typ == 2 else (8 if typ == 9 else 0)
        body += struct.pack("<IIIIIIIIII", name, typ, 0, 0, off, size, link, info, 4, entsize)
    hdr = bytearray(b"\x7fELF\x01\x01\x01" + b"\0" * 9)
    hdr += struct.pack(
        "<HHIIIIIHHHHHH", 1, 8, 1, 0, 0, e_shoff, 0, 0x34, 0, 0, 40, len(sections), 2
    )
    body[: len(hdr)] = hdr
    split = off_shstr  # .ord = header + .data ; .orp = size + rest
    ord_ = bytes(body[:split])
    orp = struct.pack(">I", len(ord_)) + bytes(body[split:])
    return ord_, orp, 2  # two triangles


def test_parse_synthetic_object():
    ord_, orp, tris = build_object()
    assert eagl.is_ord(ord_[:64])
    obj = eagl.parse(eagl.join(ord_, orp))
    assert obj.bones == ["Hips", "Spine"]
    assert obj.skeleton[1].parent == 0 and obj.skeleton[1].translation == (0.0, 10.0, 0.0)
    assert obj.skeleton[0].parent is None and obj.skeleton[0].rotation == (0.0, 0.0, 0.0, 1.0)
    assert len(obj.models) == 1
    assert obj.models[0].variations == ["Test__model1__.o_temp.variation1"]
    pk = obj.models[0].packets[0]
    assert pk.shader == SHADER and pk.stride == 8 and len(pk.indices) // 3 == tris  # 2 + 3 u16
    assert pk.positions.shape == (4, 3) and pk.positions[1, 0] == 1.0  # 256 / 256
    assert pk.uvs is not None and pk.uvs[3].tolist() == [1.0, 1.0]
    assert pk.normals is not None and abs(pk.normals[0, 2] - 1.0) < 0.01
    assert pk.textures == ["Body"]
    assert pk.joints is not None and pk.joints[:, 0].tolist() == [1, 1, 1, 1]
    assert pk.weights is not None and pk.weights[:, 0].tolist() == [1.0, 1.0, 1.0, 1.0]


def test_plugin_detect_and_extract_without_textures():
    ord_, orp, _ = build_object()

    class Src:
        by_path = {}

        def get(self, path):
            if path.endswith(".orp"):
                return orp
            raise KeyError(path)

    assert plug.detect("data/x.ord", ord_[:64], len(ord_))
    assert not plug.detect("data/x.bin", ord_[:64], len(ord_))
    scenes = plug.extract(ord_, "data/x.ord", Src())
    assert len(scenes) == 1
    s = scenes[0]
    assert len(s.primitives) == 1 and len(s.joints) == 2 and s.materials[0].texture is None
    assert s.joints[1].parent == 0 and s.primitives[0].joints is not None
    assert s.extras["format"] == "eagl"


def test_the_tail_may_come_without_a_size_prefix():
    """`.orp` carries a u32 with the .ord size; `.orl` is the same remainder with no prefix.

    Nine discs use `.orl` - MVP Baseball 2004/2005, NHL 2003/2004, FIFA Street 1/2, Def Jam
    Fight For NY, Fight Night Round 2 and G3VE69 - and reading only `.orp` raised "section table
    outside the file" on **every one of their 9,732 .ord**.  The two forms must decode alike.
    """
    ord_, orp, _ = build_object()
    orl = orp[4:]  # the same bytes without the size word
    assert eagl.join(ord_, orp) == eagl.join(ord_, orl)
    assert eagl.parse(eagl.join(ord_, orl)).bones == ["Hips", "Spine"]


def test_the_join_is_checked_by_the_elf_s_own_arithmetic():
    """What proves a pairing is right: the section table has to land inside the joined bytes.

    On the real NHL 2003 pair it ends at exactly len(.ord) + len(.orl).  A tail that does not
    complete the object is rejected here rather than parsing to an empty object.
    """
    ord_, orp, _ = build_object()
    with pytest.raises(eagl.EaglError):
        eagl.join(ord_, b"\0" * 12)


def test_a_missing_tail_is_still_tolerated():
    ord_, _, _ = build_object()
    assert eagl.join(ord_, None) == ord_
