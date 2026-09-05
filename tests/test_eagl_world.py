"""EAGL world packets: the EA ball-sports garbage cluster of the 2026-09-04 quality audit.

FIFA 04-07 / UEFA pitch, sky, track and shadow meshes, NHL 2003 arena bowls and NBA Street
V2 courts store positions as big-endian f32 xyz (12-byte elements), not s16/256 - nothing in
the packet says so, but the streams are packed back to back and the element size follows
from the gap to the next pointer.  Read as s16 they came out as +-128 saturation clouds:
~900 garbage-scored models across ten discs, all from this one wrong branch.

Two facts anchor the synthetic fixture, both measured on FIFA Soccer 2004 (GXFE69):

* ``pitchdetail`` positions at ``0x20`` with the next stream at ``0x4a60``:
  ``0x4a40 == 1584 * 12`` exactly, and decoded as f32 the pitch is a flat plane
  (``|y| <= 7.6e-4``) spanning +-5862 x +-7467 - equal to its ``__BBOX`` to the bit.
* the Old Trafford bowl mixes both forms, and its s16 packets are quantized at **1**
  fraction bit, not 8: ``__BBOX`` span / raw s16 span = 0.50002 / 0.50011 / 0.50002.
  Player bodies measure 0.00391 (= 1/256) on every axis, which is why the shipped
  ``POS_SCALE`` was right for them and 128x too small for stadium stands.
"""

import struct

import numpy as np
import pytest

from gcrip.formats import eagl

SHADER = "ClipTextureModulateNodepthwrite"
TAR = "__EAGL::TAR:::RUNTIME_ALLOC::UID=1;SHAPENAME=detl,1;;"


def build_world_object() -> tuple[bytes, bytes]:
    """Two packets, no skeleton, a __BBOX:

    * packet A - a world packet: f32 positions (gap == 4*12), RGBA4 colours (gap == 4*2),
      f32 UVs (gap fits 8 first), display list of u16 triples with no matrix bytes;
    * packet B - a legacy s16 packet whose raw span is twice the __BBOX span, so the
      bbox rescale must read it at 1/2 instead of 1/256.
    """
    data = bytearray(0x400)
    relocs: list[tuple[int, int]] = []
    names = [
        "",
        "",
        SHADER,
        TAR,
        "__const MATRIX4:::EAGL::ViewPort::gpModelViewMatrix",
        "__EAGL::GeoPrimState:::RUNTIME_ALLOC::UID=2;;",
        "__Model:::Stadium__model1__.o_temp",
        "__BBOX:::Stadium__model1__.o_temp",
    ]
    # ---- packet A streams (world): pos f32 @0x20, RGBA4 @0x50, uv f32 @0x58, DL @0x78
    A_POS, A_CLR, A_UV, A_DL = 0x20, 0x50, 0x58, 0x78
    pos_a = np.array(
        [[-3000, 0, -3000], [3000, 0, -3000], [-3000, 0, 3000], [3000, 0, 3000]], ">f4"
    )
    data[A_POS : A_POS + 48] = pos_a.tobytes()
    data[A_CLR : A_CLR + 8] = np.array([0x777F, 0x123F, 0xFFFF, 0x000F], ">u2").tobytes()
    uv_a = np.array([[0, 0], [1, 0], [0, 1], [1.5, 1.5]], ">f4")
    data[A_UV : A_UV + 32] = uv_a.tobytes()
    dl_a = bytearray(b"\x98\x00\x04")
    for i in range(4):
        dl_a += struct.pack(">HHH", i, i, i)
    data[A_DL : A_DL + len(dl_a)] = dl_a  # 27 bytes: chains at stride 6 only
    # ---- packet B streams (legacy s16, coarse quantization): raw span 12000 vs bbox 6000
    B_POS, B_NRM, B_UV, B_DL = 0xC0, 0xE0, 0xF0, 0x100
    pos_b = np.array(
        [[-6000, 0, -6000], [6000, 0, -6000], [-6000, 0, 6000], [6000, 0, 6000]], ">i2"
    )
    data[B_POS : B_POS + 24] = pos_b.tobytes()
    data[B_NRM : B_NRM + 12] = np.array([[0, 127, 0]] * 4, np.int8).tobytes()
    data[B_UV : B_UV + 16] = np.array([[0, 0], [256, 0], [0, 256], [256, 256]], ">i2").tobytes()
    dl_b = bytearray(b"\x98\x00\x04")
    for i in range(4):
        dl_b += bytes([3, 33]) + struct.pack(">HHH", i, i, i)
    data[B_DL : B_DL + len(dl_b)] = dl_b
    # ---- __BBOX: min/max xyz + runtime scratch
    BBOX = 0x210
    data[BBOX : BBOX + 32] = struct.pack(">8f", -3000, 0, -3000, 3000, 0, 3000, 0, 0)

    def put_ptr(off, value, sym):
        struct.pack_into("<I", data, off, value)
        relocs.append((off, sym))

    def packet(at, header, streams, dl_size, dl_ptr):
        o = at + 0x1C
        put_ptr(o, 0, 2)  # shader
        put_ptr(o + 4, at, 1)
        o += 8
        pairs = [(1, header, 1), (1, 0, 4)]  # P0 header, const MATRIX4
        pairs += [(4, p, 1) for p in streams]
        pairs += [(dl_size, dl_ptr, 1), (1, 0, 3), (1, 0, 5), (1, at, 1), (0, 0, 1)]
        for count, value, sym in pairs:
            struct.pack_into(">I", data, o, count)
            put_ptr(o + 4, value, sym)
            o += 8

    packet(0x260, 0x00, [A_POS, A_CLR, A_UV], len(dl_a), A_DL)
    packet(0x300, 0xA0, [B_POS, B_NRM, B_UV], len(dl_b), B_DL)
    # ---- ELF envelope (same shape as tests/test_eagl.py's build_object)
    strtab = bytearray(b"\0")
    name_off = []
    for n in names:
        name_off.append(len(strtab) if n else 0)
        if n:
            strtab += n.encode() + b"\0"
    symtab = bytearray()
    values = [0, 0, 0, 0, 0, 0, 0x200, BBOX]
    shndx = [0, 1, 0, 0, 0, 0, 1, 1]
    for i in range(len(names)):
        symtab += struct.pack("<IIIBBH", name_off[i], values[i], 4, 0, 0, shndx[i])
    rel = b"".join(struct.pack("<II", off, (sym << 8) | 2) for off, sym in relocs)
    shstr = b"\0.data\0.shstrtab\0.strtab\0.symtab\0.rel.data\0"
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
    split = off_shstr
    return bytes(body[:split]), struct.pack(">I", split) + bytes(body[split:])


def test_world_packet_reads_f32_positions_by_stream_gap():
    """The pitchdetail shape: the position stream's gap fits 12-byte elements, so the packet
    is read as f32 - the +-128 s16 saturation cloud must not come back."""
    obj = eagl.parse(eagl.join(*build_world_object()))
    assert len(obj.models) == 1
    a = obj.models[0].packets[0]
    assert a.world
    assert a.positions.dtype == np.float32
    assert a.positions[:, 0].tolist() == [-3000.0, 3000.0, -3000.0, 3000.0]
    assert (np.abs(a.positions[:, 1]) == 0).all()  # flat, like the real pitch plane


def test_world_packet_uvs_are_f32_pairs():
    obj = eagl.parse(eagl.join(*build_world_object()))
    a = obj.models[0].packets[0]
    assert a.uvs is not None
    assert a.uvs[3].tolist() == [1.5, 1.5]  # tiling f32 st, not s16/256


def test_world_packet_two_byte_stream_is_rgba4_colour_not_normals():
    """The '2 B/vertex constant 0x77 0x7f' of the 2026-08-28 note: RGBA4, mid-gray at full
    alpha (the FIFA track / shadow overlays), decoded x17 - and NOT fed to the s8 normal
    reader, which produced junk normals from it."""
    obj = eagl.parse(eagl.join(*build_world_object()))
    a = obj.models[0].packets[0]
    assert a.normals is None
    assert a.colors is not None
    assert a.colors[0].tolist() == [7 * 17, 7 * 17, 7 * 17, 15 * 17]  # 0x777f
    assert a.colors[3].tolist() == [0, 0, 0, 255]  # 0x000f


def test_bbox_rescales_coarse_s16_packets():
    """The Old Trafford bowl: s16 stands quantized at 1 fraction bit sat 128x too small
    inside their own stadium.  __BBOX span / raw span = 0.5 -> the packet is scaled to
    world units; the f32 packets are untouched."""
    obj = eagl.parse(eagl.join(*build_world_object()))
    b = obj.models[0].packets[1]
    assert not b.world
    # raw -6000 at 1/256 was -23.4375; the bbox identity reads it at 1/2 -> -3000
    assert b.positions[:, 0].tolist() == [-3000.0, 3000.0, -3000.0, 3000.0]
    assert b.normals is not None and b.normals[0, 1] == pytest.approx(1.0)
    assert b.uvs is not None and b.uvs[3].tolist() == [1.0, 1.0]


def test_player_scale_is_a_no_op():
    """Player bodies measure bbox/raw = 1/256 exactly - the shipped POS_SCALE - and must
    stay byte-for-byte identical, so the rescale skips when the snap lands on 1/256."""

    class Elf:
        data = struct.pack(">8f", -61.0, 0.0, -6.0, 61.0, 103.0, 36.0, 0, 0)
        syms = [("__BBOX:::player", 0, 0, 1)]

    raw = np.array([[-15616, 0, -1536], [15616, 26368, 9216]], ">i2").astype(np.float32)
    pos = raw * eagl.POS_SCALE  # spans exactly 256x the bbox
    pk = eagl.Packet(SHADER, 8, pos.copy(), np.zeros(0, np.uint32), None, None, None, None, [])
    eagl._rescale_s16([pk], Elf())
    assert pk.positions.tobytes() == pos.tobytes()


def test_rescale_declines_disagreeing_axes():
    """A bbox whose axes imply different scales is no identity - leave the packet alone."""

    class Elf:
        data = struct.pack(">8f", -100.0, 0.0, -100.0, 100.0, 0.0, 800.0, 0, 0)
        syms = [("__BBOX:::x", 0, 0, 1)]

    raw = np.array([[-25600, 0, -25600], [25600, 0, 25600]], ">i2").astype(np.float32)
    pos = raw * eagl.POS_SCALE
    pk = eagl.Packet(SHADER, 8, pos.copy(), np.zeros(0, np.uint32), None, None, None, None, [])
    eagl._rescale_s16([pk], Elf())
    assert pk.positions.tobytes() == pos.tobytes()


def test_s16_streams_do_not_fit_the_world_element_size():
    """An s16 stream's gap fits 6-byte elements; 12 only fits when the count is tiny, and
    the float plausibility gate holds there.  This is what keeps every player packet on the
    byte-identical legacy path (verified 197 + 87 packets on FIFA 2004's player bodies)."""
    # s16 words of a real-looking limb read as f32: exponents land far outside 1e-3..1e6
    quad = np.array([[300, -80, 12], [17, 25000, -3], [-1, 2, 3], [900, 900, 900]], ">i2")
    d = bytes(32) + quad.tobytes() + bytes(8) + bytes(64)
    ents = [(1, 0, None), (4, 32, None), (4, 64, None)]
    assert eagl._world_positions(d, ents, 4, 32) is None
