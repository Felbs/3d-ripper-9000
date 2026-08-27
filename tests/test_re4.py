"""Resident Evil 4 GC plugin: DAS/DAT expansion, the YZ2 codec, the BIN model
and the SMD scenario on synthetic data."""

from __future__ import annotations

import os
import struct

import numpy as np

from gcrip.formats import re4, yz2
from gcrip.plugins import re4 as plug


def build_dat(members: list[tuple[str, bytes]]) -> bytes:
    count = len(members)
    table = 0x10 + count * 8
    offs = []
    body = b""
    cur = (table + 0x1F) & ~0x1F
    for _ext, blob in members:
        offs.append(cur)
        body += blob
        cur += len(blob)
    out = struct.pack(">IIII", count, 0, 0, 0)
    out += struct.pack(f">{count}I", *offs)
    out += b"".join(ext.encode().ljust(4, b"\0") for ext, _ in members)
    return out.ljust(offs[0], b"\0") + body


def build_das(dat: bytes) -> bytes:
    hdr = re4.FILLER * 8
    hdr += struct.pack(">IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack(">IIII", 0xFFFFFFFF, 0, 0, 0) + b"\0" * 16
    return hdr.ljust(0x400, b"\0") + dat


def build_bin(texture: int = 0) -> bytes:
    """One material, one triangle, one bone, old-style (0x40) header."""
    bone_off = 0x40
    pos_off = bone_off + 16
    nrm_off = pos_off + 3 * 8
    uv_off = nrm_off + 3 * 8
    mat_off = uv_off + 3 * 4
    faces = bytes([0x90]) + struct.pack(">H", 3)
    for i in range(3):
        faces += struct.pack(">HHH", i, i, i)
    hdr = struct.pack(
        ">IIIIIIBBHIIIBBHIIIHHI",
        bone_off, 0, 0, 0, uv_off, 0, 0, 1, 1, mat_off, 0, 1, 0, 0, 0, 0, pos_off, nrm_off, 3, 3, 0,
    )
    assert len(hdr) == 0x40
    out = hdr
    out += bytes([0, 0xFF, 0, 0]) + struct.pack(">3f", 0.0, 0.0, 0.0)
    for i in range(3):
        out += struct.pack(">3h", i * 100, 0, (i % 2) * 100) + b"\0\0"
    for _ in range(3):
        out += struct.pack(">3h", 0, 32767, 0) + b"\0\0"
    for i in range(3):
        out += struct.pack(">2h", i * 10000, 32767)
    params = bytearray(24)
    params[12] = texture  # diffuse map = TPL image index
    params[13] = params[14] = params[15] = 0xFF
    out += bytes(params) + struct.pack(">II", len(faces), 0) + faces
    return out


def test_das_dat_expand():
    dat = build_dat([("BIN", b"model-bytes"), ("TPL", b"texture"), ("", b"unused")])
    das = build_das(dat)
    assert re4.is_das(das) and not re4.is_yz2(das)
    assert plug.is_container("r100.das", das[:64])
    names = [n for n, _ in plug.expand(das)]
    assert names == ["das_000.BIN", "das_001.TPL"]
    assert dict(plug.expand(das))["das_000.BIN"] == b"model-bytes"
    assert re4.is_dat(dat)
    assert [n for n, _ in re4.dat_entries(dat, "r100")] == ["r100_000.BIN", "r100_001.TPL"]


def test_member_is_fetched_through_its_container():
    """The manifest walker hands plugin-container members the container's head:
    detect goes by path and extract re-expands the container."""
    das = build_das(build_dat([("BIN", build_bin()), ("TPL", b"not-a-tpl")]))

    class Entry:
        def __init__(self, container):
            self.container = container

    class Src:
        by_path = {"St1/r100.das/das_000.BIN": Entry("St1/r100.das"), "St1/r100.das": Entry(None)}

        def get(self, path):
            assert path == "St1/r100.das"
            return das

    path = "St1/r100.das/das_000.BIN"
    assert plug.detect(path, das[:64], len(build_bin()))
    scenes = plug.extract(das[:64], path, Src())
    assert len(scenes) == 1 and scenes[0].triangles == 1


# ---------------------------------------------------------------------------
# YZ2
# ---------------------------------------------------------------------------


def _sample(n: int = 6000) -> bytes:
    rng = np.random.default_rng(7)
    words = [b"ROOM", b"\0\0\0\x10", b"BIN\0", b"TPL\0", bytes(range(32)), b"x" * 40]
    parts = [words[i] for i in rng.integers(0, len(words), n // 8)]
    parts.append(os.urandom(300))
    parts.append(bytes(rng.integers(0, 4, n // 2, dtype=np.uint8)))
    return b"".join(parts)[:n]


def test_yz2_round_trip_uses_every_symbol_kind():
    data = _sample()
    packed = yz2.encode(data)
    assert yz2.is_yz2(packed) and yz2.header_sizes(packed) == (len(packed) - 32, len(data))
    assert len(packed) < len(data)  # the dictionary found the repeats
    assert yz2.decode(packed) == data
    # literal-only inputs and tiny inputs
    for blob in (b"", b"A", b"AB", os.urandom(64)):
        assert yz2.decode(yz2.encode(blob)) == blob


def test_yz2_long_match_lengths():
    data = b"\x55" * 70000 + b"tail" + b"\x55" * 300
    packed = yz2.encode(data)
    assert len(packed) < 200
    assert yz2.decode(packed) == data


def test_yz2_rejects_garbage():
    try:
        yz2.decode(b"zz\tzz\n" + b"\0" * 40)
    except yz2.Yz2Error:
        pass
    else:
        raise AssertionError("expected Yz2Error")


def test_yz2_slot_is_decoded_on_expand():
    dat = build_dat([("BIN", build_bin()), ("TPL", b"texture-bytes")])
    packed = yz2.encode(dat)
    das = build_das(packed)
    names = dict(re4.expand_das(das, "r100", unpack=True))
    assert "r100_000.BIN" in names and names["r100_001.TPL"] == b"texture-bytes"
    assert names["r100_000.BIN"] == build_bin()
    left = dict(re4.expand_das(das, "r100", unpack=False))
    assert list(left) == ["r100.yz2"] and left["r100.yz2"] == packed
    assert dict(plug.expand(das))["das_001.TPL"] == b"texture-bytes"


# ---------------------------------------------------------------------------
# BIN + SMD
# ---------------------------------------------------------------------------


def test_bin_model_and_scene():
    data = build_bin()
    assert re4.is_bin(data) and plug.detect("etc/pl010a.bin", data[:64], len(data))
    # EA TERF tables are *.dat too; their NNNN.bin members are not ours
    assert not plug.detect("files/UIS_MODL.dat/0089.bin", b"\0" * 64, 4096)
    assert plug.detect("St1/r100_00.dat/dat_003.BIN", b"\0" * 64, 4096)
    m = re4.parse(data)
    assert m.triangle_count == 1 and len(m.bones) == 1 and len(m.positions) == 3
    # i16 / 2^0 / 100
    assert np.allclose(m.positions[1], (1.0, 0.0, 1.0))
    assert np.allclose(m.normals[0], (0.0, 1.0, 0.0))

    class Src:
        by_path = {}

        def get(self, path):
            raise KeyError(path)

    scenes = plug.extract(data, "etc/pl010a.bin", Src())
    assert len(scenes) == 1
    s = scenes[0]
    assert s.triangles == 1 and s.vertices == 3 and len(s.joints) == 1
    p = s.primitives[0]
    assert np.allclose(p.positions[1], (1.0, 0.0, -1.0))  # Z flipped
    assert np.allclose(p.uvs[:, 1], 0.0)  # v = 1 - 32767/32767
    assert s.materials[0].texture is None  # no TPL next to it


def build_smd(entries: list[tuple], bins: list[bytes], magic: int = 0x0040) -> bytes:
    """entries: (position cm, angles, scale, bin id, tpl id, status)."""
    hdr_len = 0x10 + (8 if magic == 0x0140 else 0)
    table = (hdr_len + len(entries) * 72 + 0x1F) & ~0x1F
    bin_table = struct.pack(f">{len(bins)}I", *[0] * len(bins))
    blobs = b""
    rel = (len(bin_table) + 0x1F) & ~0x1F
    offs = []
    for b in bins:
        offs.append(rel)
        blobs += b
        rel += len(b)
    bin_table = struct.pack(f">{len(bins)}I", *offs).ljust(offs[0] if offs else 0, b"\0")
    tpl_off = table + len(bin_table) + len(blobs)
    tpl_off = (tpl_off + 0x1F) & ~0x1F
    tpl_section = struct.pack(">I", 0x20).ljust(0x20, b"\0") + b"not-a-tpl"
    total = tpl_off + len(tpl_section)
    out = struct.pack("<H", magic) + struct.pack(">HIII", len(entries), table, tpl_off, total)
    if magic == 0x0140:
        out += struct.pack(">II", 1, 5)
    for pos, ang, scale, bin_id, tpl_id, status in entries:
        out += struct.pack(">9f", *pos, *ang, *scale)
        out += bytes([bin_id, tpl_id, 0xFF, 0]) + b"\0" * 28 + struct.pack(">I", status)
    out = out.ljust(table, b"\0") + bin_table + blobs
    return out.ljust(tpl_off, b"\0") + tpl_section


def test_smd_scenario_places_objects():
    b0, b1 = build_bin(0), build_bin(1)
    entries = [
        ((100.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0, 0, 0x8),
        ((0.0, 0.0, 0.0), (0.0, np.pi / 2, 0.0), (2.0, 2.0, 2.0), 1, 0, 0x8),
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 7, 0, 0x18),  # shared: skipped
    ]
    smd = build_smd(entries, [b0, b1])
    assert re4.is_smd(smd) and plug.detect("St1/r100.das/das_004.SMD", smd[:64], len(smd))
    s = re4.parse_smd(smd)
    assert len(s.entries) == 3 and len(s.bins) == 2 and s.bins[0] == b0
    assert s.bins[1].startswith(b1)  # the last BIN runs to the TPL table (padding)
    assert s.entries[2].shared and s.entries[0].position == (1.0, 0.0, 0.0)
    scene = plug.smd_to_scene(s, "r100")
    assert scene.extras["objects"] == 2 and scene.triangles == 2 and len(scene.materials) == 2
    # object 0: vertex (1, 0, 1) + (1, 0, 0), Z flipped
    assert np.allclose(scene.primitives[0].positions[1], (2.0, 0.0, -1.0), atol=1e-5)
    # object 1: rotated 90 degrees about Y (x -> -z... z -> x) then scaled by 2
    assert np.allclose(scene.primitives[1].positions[1], (2.0, 0.0, 2.0), atol=1e-5)
    # a 0x0140 header carries an extra parameter list before the entries
    s2 = re4.parse_smd(build_smd(entries[:1], [b0], magic=0x0140))
    assert len(s2.entries) == 1 and s2.entries[0].bin_id == 0


def test_smd_member_extracts_through_its_container():
    smd = build_smd([((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0, 0, 0)], [build_bin()])
    das = build_das(build_dat([("SMD", smd)]))

    class Src:
        by_path = {}

        def get(self, path):
            return das

    scenes = plug.extract(das[:64], "St1/r102.das/das_000.SMD", Src())
    assert len(scenes) == 1 and scenes[0].triangles == 1
