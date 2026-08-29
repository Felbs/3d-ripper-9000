"""Ninja chunk models, motions and PVR textures on synthetic data."""

from __future__ import annotations

import struct

import numpy as np

from dcrip import ninja_eval
from dcrip.formats import ninja, pvr
from ripcore import gltf


def _obj(flags, model_ptr, pos, rot, scale, child, sib) -> bytes:
    return struct.pack("<II3f3i3fII", flags, model_ptr, *pos, *rot, *scale, child, sib)


def _vchunk_vn(index_offset: int, verts: list[tuple], status: int = 0) -> bytes:
    """0x29 NJD_CV_VN: xyz + normal, 24 bytes per vertex."""
    body = struct.pack("<HH", index_offset, len(verts))
    for p, n in verts:
        body += struct.pack("<3f3f", *p, *n)
    size_words = len(body) // 4
    return struct.pack("<BBH", 0x29, status, size_words) + body + b"\xff\x00\x00\x00"


def _vchunk_vn_nf(index_offset: int, verts: list[tuple], status: int) -> bytes:
    """0x2C NJD_CV_VN_NF: xyz + normal + (slot | weight << 16), 28 bytes per vertex."""
    body = struct.pack("<HH", index_offset, len(verts))
    for p, n, slot, weight in verts:
        body += struct.pack("<3f3fI", *p, *n, slot | (weight << 16))
    return struct.pack("<BBH", 0x2C, status, len(body) // 4) + body


def _strip_uvn(strips: list[list[tuple[int, int, int]]], flags: int = 0) -> bytes:
    body = struct.pack("<H", len(strips))
    for s in strips:
        body += struct.pack("<h", len(s))
        for vi, u, v in s:
            body += struct.pack("<Hhh", vi, u, v)
    if len(body) % 2:
        body += b"\x00"
    return struct.pack("<BBH", 0x41, flags, len(body) // 2) + body


def build_chunk_model() -> bytes:
    """Two objects: a root drawing a textured quad, and a child (bone) that writes weighted
    vertices into the cache and draws a triangle from them."""
    n = (0, 0, 1)
    quad = [((0, 0, 0), n), ((1, 0, 0), n), ((1, 1, 0), n), ((0, 1, 0), n)]
    vlist0 = _vchunk_vn(0, quad)
    plist0 = (
        struct.pack("<BBH", 0x08, 0x00, 3)  # texture id 3
        + struct.pack("<BBHI", 0x11, 0, 2, 0xFF80FF40)  # diffuse ARGB
        + _strip_uvn([[(0, 0, 0), (1, 256, 0), (3, 0, 256), (2, 256, 256)]])
        + b"\xff\x00"
    )
    # bone: two weighted writes into slots 10..11 (status 0 = start, then 2 = end)
    v1 = _vchunk_vn_nf(10, [((0, 0, 0), (0, 1, 0), 0, 128), ((2, 0, 0), (0, 1, 0), 1, 128)], 0)
    v1 += _vchunk_vn_nf(10, [((0, 0, 0), (0, 1, 0), 0, 127), ((2, 0, 0), (0, 1, 0), 1, 127)], 2)
    v1 += b"\xff\x00\x00\x00"
    plist1 = _strip_uvn([[(10, 0, 0), (11, 256, 0), (0, 0, 256)]], flags=0x10) + b"\xff\x00"
    # layout: obj0 @0, obj1 @52, model0 @104, model1 @128, then the lists
    off = 152
    vl0, off = off, off + len(vlist0)
    pl0, off = off, off + len(plist0)
    vl1, off = off, off + len(v1)
    pl1 = off
    model0 = struct.pack("<II4f", vl0, pl0, 0, 0, 0, 1)
    model1 = struct.pack("<II4f", vl1, pl1, 0, 0, 0, 1)
    obj0 = _obj(0, 104, (0, 0, 0), (0, 0, 0), (1, 1, 1), 52, 0)
    obj1 = _obj(0x01, 128, (5, 5, 5), (0, 0x4000, 0), (1, 1, 1), 0, 0)  # unit-pos flag: ignore pos
    payload = obj0 + obj1 + model0 + model1 + vlist0 + plist0 + v1 + plist1
    names = b"texa\x00texb\x00texc\x00texd\x00"
    tl_entries = b""
    p = 8 + 4 * 12
    for n in (b"texa", b"texb", b"texc", b"texd"):
        tl_entries += struct.pack("<III", p, 0, 0)
        p += len(n) + 1
    texlist = struct.pack("<II", 8, 4) + tl_entries + names
    return (
        b"NJTL"
        + struct.pack("<I", len(texlist))
        + texlist
        + b"NJCM"
        + struct.pack("<I", len(payload))
        + payload
    )


def test_parse_chunk_model_and_eval(tmp_path):
    nj = ninja.parse(build_chunk_model())
    assert nj.kind == "chunk"
    assert nj.texlist.names == ["texa", "texb", "texc", "texd"]
    assert len(nj.objects) == 2 and nj.objects[1].parent == 0
    m0, m1 = nj.objects[0].model, nj.objects[1].model
    assert len(m0.vertices) == 4 and len(m0.strips) == 1
    assert m0.strips[0].material.texture == 3
    assert m0.strips[0].material.diffuse == (128 / 255, 1.0, 64 / 255, 1.0)
    assert len(m0.strips[0].indices) == 6  # one strip of 4 -> 2 triangles
    assert [v.cache_index for v in m1.vertices] == [10, 11, 10, 11]
    assert [v.status for v in m1.vertices] == [0, 0, 2, 2]
    assert m1.strips[0].material.double_sided
    assert not nj.warnings and not m0.warnings and not m1.warnings

    scene = ninja_eval.evaluate(nj, "synthetic")
    assert len(scene.joints) == 2
    # unit-pos flag: the bone's translation is dropped, its 90-degree Y rotation kept
    assert scene.joints[1].translation == (0.0, 0.0, 0.0)
    assert abs(scene.joints[1].rotation[1] - 0.7071) < 1e-3
    assert len(scene.materials) == 2
    assert scene.materials[0].texture == "texd"
    tris = sum(len(p.indices) // 3 for p in scene.primitives)
    assert tris == 3
    # the weighted vertex accumulates two writes of ~0.5 each at the same place
    prim1 = next(p for p in scene.primitives if p.material == 1)
    slot11 = prim1.positions[np.argmax(np.abs(prim1.positions).sum(axis=1))]
    assert np.allclose(np.abs(slot11), [0, 0, 2], atol=0.05)  # (2,0,0) rotated 90 deg about Y
    w = prim1.weights
    assert np.allclose(w.sum(axis=1), 1.0)

    scene.textures["texd"] = np.zeros((4, 4, 4), np.uint8)
    st = gltf.export(scene, tmp_path / "synthetic")
    assert (tmp_path / "synthetic.gltf").exists() and (tmp_path / "synthetic.bin").exists()
    assert (tmp_path / "synthetic_tex" / "texd.png").exists()
    assert st.triangles == 3 and st.joints == 2 and st.textures == 1
    assert gltf.thumbnail(st, tmp_path / "synthetic") is not None


def test_motion_sampling():
    nj = ninja.parse(build_chunk_model())
    # NMDM: mdata for 2 objects with pos+rot (type 3): ptrs then counts; keys 16 bytes
    keys_pos = struct.pack("<I3f", 0, 0, 0, 0) + struct.pack("<I3f", 10, 10, 0, 0)
    keys_rot = struct.pack("<I3i", 0, 0, 0, 0) + struct.pack("<I3i", 10, 0, 0x4000, 0)
    mdata_off = 12
    kp = mdata_off + 2 * 16
    kr = kp + len(keys_pos)
    mdata = struct.pack("<IIII", 0, 0, 0, 0) + struct.pack("<IIII", kp, kr, 2, 2)
    payload = struct.pack("<IIHH", mdata_off, 11, 3, 0) + mdata + keys_pos + keys_rot
    m = ninja.parse_motion(payload, 2)
    assert m.frames == 11 and m.tracks[1]["pos"][1] == (10, (10.0, 0.0, 0.0))
    clip = ninja_eval.sample_motion(m, nj, "walk", 30.0)
    assert clip.translation[1].shape == (11, 3)
    assert np.allclose(clip.translation[1][5], [5, 0, 0])
    assert abs(clip.rotation[1][10][1] - 0.7071) < 1e-3  # 90 degrees about Y at the end


def test_pvr_twiddled_roundtrip():
    w = h = 8
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[..., 0] = np.arange(w) * 32
    rgb[..., 1] = np.arange(h)[:, None] * 32
    r5 = (rgb[..., 0] >> 3).astype(np.uint16)
    g6 = (rgb[..., 1] >> 2).astype(np.uint16)
    words = (r5 << 11) | (g6 << 5)
    idx = pvr.twiddle_index(w, h)
    storage = np.zeros(w * h, np.uint16)
    storage[idx.reshape(-1)] = words.reshape(-1)
    data = b"PVRT" + struct.pack("<IBBHHH", 8 + w * h * 2, 1, 0x01, 0, w, h) + storage.tobytes()
    t = pvr.parse(b"GBIX" + struct.pack("<II", 8, 42) + b"\x00" * 4 + data)
    assert t.gbix == 42 and t.fmt_name == "RGB565/twiddled"
    out = t.decode()
    assert out.shape == (8, 8, 4)
    assert np.array_equal(out[..., 0] >> 3, r5) and np.array_equal(out[..., 1] >> 2, g6)
    assert out[..., 3].min() == 255


def test_pvm_pack():
    tex = b"PVRT" + struct.pack("<IBBHHH", 8 + 8, 2, 0x09, 0, 2, 2) + bytes(8)
    header = struct.pack("<HH", 0x3, 2)
    for i, name in enumerate((b"alpha", b"beta")):
        header += struct.pack("<H", i) + name.ljust(28, b"\x00") + struct.pack("<I", 100 + i)
    data = b"PVMH" + struct.pack("<I", len(header)) + header + tex + tex
    ents = pvr.parse_pvm(data)
    assert [e.name for e in ents] == ["alpha", "beta"]
    assert [e.gbix for e in ents] == [100, 101]
    assert ents[1].offset == 8 + len(header) + len(tex)
    assert pvr.parse(data[ents[1].offset : ents[1].offset + ents[1].size]).width == 2
