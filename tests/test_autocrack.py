"""Synthetic fixtures for the autocrack hypothesis battery - one per probe family."""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from gcrip import autocrack as ac

RNG = np.random.default_rng(42)


# -- container probes ----------------------------------------------------------------------


def test_chunk_stream_tiles():
    body = bytearray()
    for tag, payload in ((b"HEAD", 24), (b"DATA", 300), (b"DATA", 128), (b"TAIL", 40)):
        body += tag + struct.pack(">I", payload + 8) + bytes(payload)
    r = ac.probe_chunk_stream(bytes(body))
    assert r.fired
    assert r.params["chunks"] == 4
    assert r.params["coverage"] == pytest.approx(1.0)


def test_chunk_stream_rejects_noise():
    data = RNG.integers(0, 256, 4096, dtype=np.uint8).tobytes()
    assert not ac.probe_chunk_stream(data).fired


def test_tiling_table():
    header = bytes(16)
    sizes = [96, 40, 200, 64, 32, 128, 80, 48, 112, 72]
    table = bytearray()
    base = 16 + len(sizes) * 8
    off = base
    for s in sizes:
        table += struct.pack(">II", off, s)
        off += s
    data = header + bytes(table) + bytes(sum(sizes))
    r = ac.probe_tiling_table(data)
    assert r.fired
    assert r.params["entries"] >= 8
    assert r.params["exact"]


def test_ascending_table_hashes():
    hashes = np.sort(RNG.integers(1, 1 << 32, 64, dtype=np.uint64).astype(np.uint32))
    hashes = np.unique(hashes)
    data = struct.pack(">I", len(hashes)) + hashes.astype(">u4").tobytes() + bytes(64)
    r = ac.probe_ascending_table(data)
    assert r.fired
    assert r.params["entries"] >= 16


def test_name_table_fixed_stride():
    names = [b"jersey", b"pants", b"ROOT_BONE", b"L_UP_LEG", b"R_UP_LEG", b"HEAD_TOP"]
    blob = bytes(64) + b"".join(n.ljust(32, b"\0") for n in names) + bytes(64)
    r = ac.probe_name_tables(blob)
    assert r.fired
    assert any(t["kind"] == "stride 32" for t in r.params["tables"])


def test_name_table_dense_run():
    names = [f"textures\\file{i:02d}.bmp".encode() for i in range(12)]
    blob = bytes(32) + b"\0".join(names) + b"\0" + bytes(32)
    r = ac.probe_name_tables(blob)
    assert r.fired
    assert any(t["kind"] == "back-to-back" for t in r.params["tables"])


# -- GX display-list probes ----------------------------------------------------------------


def _gx_fixture(prims: int = 8, setup: bool = True, stride: int = 8) -> bytes:
    out = bytearray(bytes(16))
    for p in range(prims):
        if setup:  # CP VCD_LO loads interleaved between primitives, as Blitz writes them
            out += b"\x08\x50" + struct.pack(">I", 0x7E00)
        count = 12 + p
        out += bytes([0x98]) + struct.pack(">H", count)
        idx = RNG.integers(0, 200, count * (stride // 2), dtype=np.uint16)
        out += idx.astype(">u2").tobytes()
    out += b"\xde\xad"  # walk stops here
    return bytes(out)


def test_gx_display_list_with_setup():
    r = ac.probe_gx_display_lists(_gx_fixture())
    assert r.fired
    assert r.params["has_cp"]
    assert not r.params["naked"]
    assert r.params["best"]["prims"] == 8
    assert r.params["best"]["stride"] == 8


def test_gx_display_list_naked():
    r = ac.probe_gx_display_lists(_gx_fixture(setup=False))
    assert r.fired
    assert r.params["naked"]


def test_gx_display_list_rejects_noise():
    data = RNG.integers(0, 256, 1 << 16, dtype=np.uint8).tobytes()
    assert not ac.probe_gx_display_lists(data).fired


# -- vertex-array probes -------------------------------------------------------------------


def test_f32_positions():
    v = RNG.normal(0, 25.0, (300, 3))
    data = bytes(32) + v.astype(">f4").tobytes() + bytes(32)
    r = ac.probe_f32_positions(data)
    assert r.fired
    assert r.params["triples"] >= 250


def test_s16_fixed_point():
    v = RNG.integers(-12000, 12000, 4096, dtype=np.int16)
    v[np.abs(v) < 16] = 900  # keep every value mid-range
    r = ac.probe_s16_fixed(bytes(8) + v.astype(">i2").tobytes())
    assert r.fired
    assert set(r.params["extents"]) == {256, 1024, 4096, 16384}


def test_normal_runs_packed_s16():
    n = RNG.normal(size=(200, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    data = bytes(16) + np.round(n * 16384).astype(">i2").tobytes()
    r = ac.probe_normal_runs(data)
    assert r.fired
    assert any(x["kind"] == "s16 /16384" and x["triples"] >= 48 for x in r.params["runs"])


def test_normal_runs_record_interleaved():
    n = RNG.normal(size=(150, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    rows = bytearray()
    for i in range(len(n)):
        rows += RNG.integers(-30000, 30000, 3, dtype=np.int16).astype(">i2").tobytes()
        rows += np.round(n[i] * 16384).astype(">i2").tobytes()  # 12-byte {pos, nrm} rows
    r = ac.probe_normal_runs(bytes(rows))
    assert r.fired
    assert any(x["stride"] == 12 for x in r.params["runs"])


def test_uv_runs_f32():
    uv = RNG.random((200, 2))
    r = ac.probe_uv_runs(bytes(16) + uv.astype(">f4").tobytes())
    assert r.fired


def test_quaternion_runs_skg_keys():
    q = RNG.normal(size=(60, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    recs = bytearray()
    for i in range(len(q)):  # the 20-byte skg animation key: f32 frame + unit quat
        recs += struct.pack(">f", float(i)) + q[i].astype(">f4").tobytes()
    r = ac.probe_quaternion_runs(bytes(recs))
    assert r.fired
    assert r.params["framing"] == "frame+q4 (skg key)"
    assert r.params["records"] >= 40


def test_matrix_runs_at_record_stride():
    recs = bytearray()
    for _ in range(8):  # 128-byte rows opening with a rotation, like the SKX joint table
        m = np.linalg.qr(RNG.normal(size=(3, 3)))[0]
        recs += m.astype(">f4").tobytes() + bytes(128 - 36)
    r = ac.probe_matrix_runs(bytes(recs))
    assert r.fired
    hit = r.params["hits"][0]
    assert hit["count"] >= 6
    assert hit["stride"] == 128


def test_matrix_runs_not_fooled_by_unit_normals():
    n = RNG.normal(size=(400, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    r = ac.probe_matrix_runs(n.astype(">f4").tobytes())
    assert not r.fired  # unit rows, but consecutive normals are not orthogonal


# -- skeleton probes -----------------------------------------------------------------------

PARENTS = [-1, 0, 1, 1, 3, 4, 4, 6, 2, 8, 9, 9, 11, 3, 2, 5]


def test_parent_table_packed():
    data = np.array(PARENTS, dtype=">i4").tobytes() + bytes(64)
    r = ac.probe_parent_table(data)
    assert r.fired
    assert r.params["entries"] >= len(PARENTS)
    assert r.params["roots"] == 1


def test_parent_table_record_stride():
    recs = bytearray()
    for p in PARENTS:  # 16-byte records with the parent at +0, like a joint table
        recs += struct.pack(">i", p) + bytes(12)
    r = ac.probe_parent_table(bytes(recs))
    assert r.fired
    assert r.params["stride"] == 16
    assert r.params["dtype"] == ">i4"


def test_bone_names():
    blob = b"\0".join(
        [b"ROOT", b"L_UP_LEG", b"R_HAND", b"SPINE1", b"NECK", b"lclavicle", b"mesh01"]
    ) + b"\0"
    r = ac.probe_bone_names(bytes(16) + blob)
    assert r.fired
    assert r.params["count"] >= 5


# -- codec probes --------------------------------------------------------------------------


def test_zlib_streams():
    payload = zlib.compress(b"the member decodes to this, repeated " * 64)
    r = ac.probe_zlib(bytes(37) + payload + bytes(11))
    assert r.fired
    assert r.params["streams"][0]["complete"]


def test_entropy_map_and_fill():
    data = RNG.integers(0, 256, 32 * ac.PAGE, dtype=np.uint8).tobytes() + b"\xab" * (
        4 * ac.PAGE
    )
    r = ac.probe_entropy(data)
    assert r.fired  # a contiguous high-entropy region
    assert 0xAB in r.params["fills"]


# -- oracle utilities ----------------------------------------------------------------------


def _grid_mesh() -> tuple[np.ndarray, np.ndarray]:
    xx, yy = np.meshgrid(np.arange(10.0), np.arange(10.0))
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(100)], axis=1)
    tris = []
    for r in range(9):
        for c in range(9):
            a = r * 10 + c
            tris += [[a, a + 1, a + 10], [a + 1, a + 11, a + 10]]
    return pos, np.array(tris)


def test_edge_coherence_ranks_a_real_mesh():
    pos, tris = _grid_mesh()
    good = ac.edge_coherence(pos, tris)
    assert not good["gamed"]
    assert good["score"] < 0.2


def test_edge_coherence_flags_collapse():
    pos, tris = _grid_mesh()
    collapsed = ac.edge_coherence(np.zeros_like(pos), tris)
    assert collapsed["gamed"]
    assert collapsed["score"] == float("inf")


def test_edge_coherence_flags_degenerate():
    pos, _ = _grid_mesh()
    degen = np.array([[1, 1, 2], [3, 3, 3]])
    assert ac.edge_coherence(pos, degen)["gamed"]


def test_connected_components():
    tris = np.array([[0, 1, 2], [1, 2, 3], [10, 11, 12]])
    assert ac.connected_components(tris) == [4, 3]


def test_bbox_containment():
    pos = np.array([[0.5, 0.5, 0.5], [2.0, 0.0, 0.0]])
    assert ac.bbox_containment(pos, (0, 0, 0), (1, 1, 1)) == pytest.approx(0.5)


def test_triangle_identity():
    ok, _ = ac.triangle_identity(44, 44)
    assert ok
    bad, msg = ac.triangle_identity(44, 43)
    assert not bad
    assert "off by -1" in msg


def test_render_wireframe(tmp_path):
    pos, tris = _grid_mesh()
    out = tmp_path / "wire.png"
    ac.render_wireframe(pos, tris, out)
    assert out.stat().st_size > 1000


# -- the battery ---------------------------------------------------------------------------


def test_probe_end_to_end_indexed_gx():
    v = RNG.normal(0, 25.0, (300, 3)).astype(">f4")
    fx = _gx_fixture(prims=10)
    data = fx + bytes(16 + (-len(fx) % 4)) + v.tobytes()  # arrays are 4-aligned on disc
    report = ac.probe(data)
    assert report.size == len(data)
    fired = report.fired()
    assert "gx-display-list" in fired
    assert "f32-positions" in fired
    assert any(a == "indexed-GX-arrays" for a, _ in report.archetypes)
    text = report.summary()
    assert "gx-display-list" in text
    assert "archetype" in text


def test_probe_on_noise_is_quiet():
    data = RNG.integers(0, 256, 1 << 17, dtype=np.uint8).tobytes()
    report = ac.probe(data)
    quiet = {"chunk-stream", "container-tiling", "gx-display-list", "f32-positions",
             "name-table", "parent-table", "quaternion-runs", "matrix-runs"}
    assert not quiet & set(report.fired())


def test_probe_result_lookup():
    report = ac.probe(bytes(4096))
    assert report.probe("entropy-map") is not None
    assert report.probe("nope") is None
