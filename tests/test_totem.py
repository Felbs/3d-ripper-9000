"""Kalisto TotemTech .dgc geometry primitives."""

import struct

import numpy as np

from gcrip.formats import totem


def build() -> bytes:
    banner = totem.BANNER + b" v1.75 (c) 1999-2002 Kalisto Entertainment"
    head = banner + b"" * (0x104 - len(banner))  # 4-byte aligned, padding is not float-like
    verts = [(x * 0.5, (x % 3) * 0.25, -x * 0.125) for x in range(1, 41)]
    body = b"".join(struct.pack(">3f", *v) for v in verts)
    faces = b""
    for i in range(12):
        faces += totem.COUNT3 + struct.pack(">3H", i, i + 1, i + 2) + b"\x00\x00\x00\x01\x02\x00"
    return head + body + faces + bytes(64)


def test_detects_banner():
    d = build()
    assert totem.is_dgc(d[:0x60])
    assert not totem.is_dgc(b"nope" * 8)


def test_finds_vertices_and_faces():
    d = build()
    found = totem.meshes(d)
    assert len(found) == 1
    m = found[0]
    assert 38 <= len(m.positions) <= 41  # a scan, so the run edges are approximate
    assert len(m.indices) % 3 == 0 and len(m.indices) >= 30
    assert np.isfinite(m.positions).all() and int(m.indices.max()) < len(m.positions)
    assert int(m.indices.max()) < len(m.positions)


def test_ignores_a_run_without_faces():
    banner = totem.BANNER + b" v1.75"
    head = banner + b"" * (0x104 - len(banner))
    body = b"".join(struct.pack(">3f", i, i, i) for i in range(1, 41))
    assert totem.meshes(head + body + bytes(128)) == []
