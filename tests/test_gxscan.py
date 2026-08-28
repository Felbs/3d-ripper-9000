"""The engine-agnostic display-list scanner: a synthetic GX list over a float array is
found with the right stride/field, and noise yields nothing."""
import struct

import numpy as np

from gcrip import gxscan


def _grid(n: int = 12) -> np.ndarray:
    xs, ys = np.meshgrid(np.arange(n, dtype=np.float32), np.arange(n, dtype=np.float32))
    return np.stack([xs.ravel(), ys.ravel(), np.zeros(n * n, np.float32)], 1)


def _strips(n: int = 12) -> list[list[int]]:
    """One triangle strip per grid row pair."""
    out = []
    for r in range(n - 1):
        s = []
        for c in range(n):
            s += [r * n + c, (r + 1) * n + c]
        out.append(s)
    return out


def build_blob(*, stride_extra: int = 2, header: bytes = b"HDR\0" * 8, pad: bool = True) -> tuple[bytes, int]:
    """[header][positions f32 BE][display list: 0x98 count (pos u16, junk u8*extra)...]"""
    pos = _grid()
    dl = bytearray()
    for s in _strips():
        dl += bytes([0x98]) + struct.pack(">H", len(s))
        for i in s:
            dl += struct.pack(">H", i) + bytes([(i * 7) & 0xFF] * stride_extra)
        if pad:
            dl += b"\0" * (-len(dl) % 32)
    data = header + pos.astype(">f4").tobytes() + bytes(dl)
    expected = sum(len(s) - 2 for s in _strips())
    return data, expected


def test_finds_synthetic_list_and_recovers_triangles():
    data, expected = build_blob()
    meshes = gxscan.scan_blob(data)
    assert len(meshes) == 1
    m = meshes[0]
    assert m.dl.stride == 4 and m.field_size == 2 and m.pos_kind == "f32"
    assert m.triangles == expected
    assert m.pos_offset == 32  # right after the header
    assert m.compactness < 2.0


def test_inline_vertices_without_index_arrays():
    pos = _grid()
    dl = bytearray()
    for s in _strips():
        dl += bytes([0x98]) + struct.pack(">H", len(s))
        for i in s:
            dl += struct.pack(">fff", *pos[i]) + struct.pack(">HH", 1, 2)  # pos + fake uv
    meshes = gxscan.scan_blob(bytes(dl))
    assert len(meshes) == 1 and meshes[0].pos_kind == "inline-f32"
    assert meshes[0].triangles == sum(len(s) - 2 for s in _strips())


def test_noise_yields_nothing():
    rnd = np.random.default_rng(3).integers(0, 256, 1 << 20, dtype=np.uint8).tobytes()
    assert gxscan.scan_blob(rnd) == []
    assert gxscan.scan_blob(bytes(1 << 20)) == []
    assert gxscan.scan_blob(b"lorem ipsum dolor sit amet " * 20000) == []
