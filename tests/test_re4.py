"""Resident Evil 4 GC plugin: DAS/DAT expansion and the BIN model on synthetic data."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import re4
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


def build_bin() -> bytes:
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
    params[12] = 0  # diffuse map = TPL image 0
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


def test_yz2_slot_is_reported_not_decoded():
    blob = b"1234\t5678\n".ljust(0x20, b"\0") + re4.YZ2_TAG + b"\0" * 32
    das = build_das(blob)
    assert plug.expand(das) == [("das.yz2", blob)]


def test_bin_model_and_scene():
    data = build_bin()
    assert re4.is_bin(data) and plug.detect("etc/pl010a.bin", data[:64], len(data))
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
