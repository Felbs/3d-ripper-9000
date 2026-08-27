"""HSD / DAT plugin on a synthetic archive: header + relocation parsing, the JOBJ tree,
one textured envelope-skinned POBJ display list, and a Scene export."""

from __future__ import annotations

import json
import math
import struct

import numpy as np

from gcrip.formats import hsd, hsd_eval
from gcrip.plugins import hsd as plugin
from ripcore import gltf


class _Builder:
    """Builds a DAT data block with pointer fields tracked for the relocation table."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.relocs: list[int] = []

    def align(self, n: int = 4) -> None:
        while len(self.buf) % n:
            self.buf.append(0)

    def add(self, blob: bytes, align: int = 4) -> int:
        self.align(align)
        off = len(self.buf)
        self.buf += blob
        return off

    def struct(self, fields: list[tuple[str, int | float]]) -> int:
        """fields: (kind, value) with kind 'p' pointer / 'I' u32 / 'H' u16 / 'B' u8 / 'f'."""
        self.align(4)
        off = len(self.buf)
        for kind, v in fields:
            if kind == "p":
                if v:
                    self.relocs.append(len(self.buf))
                self.buf += struct.pack(">I", v)
            else:
                self.buf += struct.pack(">" + kind, v)
        return off

    def finish(self, roots: list[tuple[str, int]]) -> bytes:
        self.align(32)
        strings = bytearray()
        root_entries = bytearray()
        for name, off in roots:
            root_entries += struct.pack(">II", off, len(strings))
            strings += name.encode() + b"\0"
        body = bytes(self.buf)
        reloc = b"".join(struct.pack(">I", r) for r in sorted(self.relocs))
        total = 0x20 + len(body) + len(reloc) + len(root_entries) + len(strings)
        header = struct.pack(">IIIII", total, len(body), len(self.relocs), len(roots), 0)
        header += b"001B" + b"\0" * 8
        return header + body + reloc + root_entries + bytes(strings)


def _vtx_attr(b: _Builder, attr, atype, cnt, ctype, frac, stride, ptr) -> list:
    return [("I", attr), ("I", atype), ("I", cnt), ("I", ctype), ("B", frac), ("B", 0),
            ("H", stride), ("p", ptr)]


def build_dat() -> tuple[bytes, dict]:
    """Two joints (root -> child at y=2), one envelope POBJ: a quad (2 strips) whose left
    edge is bound to the root and right edge to the child, textured with a 4x4 RGB565."""
    b = _Builder()
    # vertex data: positions s16 frac 8 (1.0 = 256), uvs s16 frac 15 (u8 style)
    pos = [(-1, 0, 0), (-1, 1, 0), (1, 0, 0), (1, 1, 0)]
    pos_off = b.add(b"".join(struct.pack(">hhh", *(int(c * 256) for c in p)) for p in pos), 32)
    uvs = [(0, 1), (0, 0), (1, 1), (1, 0)]
    uv_raw = b"".join(struct.pack(">hh", int(u * 0x4000), int(v * 0x4000)) for u, v in uvs)
    uv_off = b.add(uv_raw, 32)
    # texture: 4x4 RGB565, one tile, solid orange (r=31,g=31,b=0 -> 0xFFE0)
    tex_off = b.add(struct.pack(">16H", *([0xFFE0] * 16)), 32)
    # display list: two strips (0x98), corners: PNMTXIDX (direct u8), POS idx16, TEX0 idx16
    dl = bytearray()
    dl += struct.pack(">BH", 0x98, 4)
    for mtx, vi in ((0, 0), (0, 1), (3, 2), (3, 3)):
        dl += struct.pack(">BHH", mtx, vi, vi)
    dl += struct.pack(">BH", 0x90, 3)
    for mtx, vi in ((0, 0), (3, 2), (0, 1)):
        dl += struct.pack(">BHH", mtx, vi, vi)
    dl += b"\0" * (-len(dl) % 32)
    dl_off = b.add(bytes(dl), 32)
    n_disp = len(dl) // 32
    # attribute list
    attrs = b.struct(
        _vtx_attr(b, hsd.VA_PNMTXIDX, hsd.GX_DIRECT, 0, 4, 0, 0, 0)
        + _vtx_attr(b, hsd.VA_POS, hsd.GX_INDEX16, 1, 3, 8, 6, pos_off)
        + _vtx_attr(b, hsd.VA_TEX0, hsd.GX_INDEX16, 1, 3, 14, 4, uv_off)
        + _vtx_attr(b, hsd.VA_NULL, 0, 0, 0, 0, 0, 0)
    )
    # image desc + tobj + material + mobj
    img = b.struct([("p", tex_off), ("H", 4), ("H", 4), ("I", 4), ("I", 0), ("f", 0.0), ("f", 0.0)])
    tobj = b.struct(
        [("p", 0), ("p", 0), ("I", 0), ("I", 4)]
        + [("f", 0.0)] * 3 + [("f", 1.0)] * 3 + [("f", 0.0)] * 3
        + [("I", 1), ("I", 1), ("B", 1), ("B", 1), ("H", 0), ("I", 0x50010), ("f", 1.0), ("I", 1),
           ("p", img), ("p", 0), ("p", 0), ("p", 0)]
    )
    mat = b.struct(
        [("I", 0x7F7F7FFF), ("I", 0xFFFFFFFF), ("I", 0xFFFFFFFF), ("f", 1.0), ("f", 50.0)]
    )
    mobj = b.struct(
        [("p", 0), ("I", hsd.RENDER_DIFFUSE | hsd.RENDER_TEX0), ("p", tobj), ("p", mat),
         ("p", 0), ("p", 0)]
    )
    # joints: child first (it has no children), then root; envelopes need both offsets
    ident = struct.pack(">12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
    child_ibm = struct.pack(">12f", 1, 0, 0, 0, 0, 1, 0, -2, 0, 0, 1, 0)
    root_ibm_off = b.add(ident)
    child_ibm_off = b.add(child_ibm)
    child = b.struct(
        [("p", 0), ("I", hsd.JOBJ_SKELETON), ("p", 0), ("p", 0), ("p", 0)]
        + [("f", 0.0), ("f", 0.0), ("f", math.pi / 2)] + [("f", 1.0)] * 3
        + [("f", 0.0), ("f", 2.0), ("f", 0.0)] + [("p", child_ibm_off), ("p", 0)]
    )
    # placeholders for the envelope list: env0 = root only, env1 = child only
    # (jobj offsets known only after the root is written, so write root now with dobj later)
    root = b.struct(
        [("p", 0), ("I", hsd.JOBJ_SKELETON_ROOT | hsd.JOBJ_ENVELOPE_MODEL),
         ("p", child), ("p", 0), ("p", 0)]
        + [("f", 0.0)] * 3 + [("f", 1.0)] * 3 + [("f", 0.0)] * 3 + [("p", root_ibm_off), ("p", 0)]
    )
    env0 = b.struct([("p", root), ("f", 1.0), ("p", 0), ("f", 0.0)])
    env1 = b.struct([("p", child), ("f", 1.0), ("p", 0), ("f", 0.0)])
    env_list = b.struct([("p", env0), ("p", env1), ("p", 0)])
    pobj = b.struct(
        [("p", 0), ("p", 0), ("p", attrs), ("H", hsd.POBJ_ENVELOPE | (1 << 15)), ("H", n_disp),
         ("p", dl_off), ("p", env_list)]
    )
    dobj = b.struct([("p", 0), ("p", 0), ("p", mobj), ("p", pobj)])
    # patch the root's dobj pointer
    struct.pack_into(">I", b.buf, root + 0x10, dobj)
    b.relocs.append(root + 0x10)
    data = b.finish([("TestModel_joint", root), ("Orange_RGB565_image", img)])
    return data, {"root": root, "child": child, "pobj": pobj, "img": img, "tex": tex_off}


def test_header_and_relocations():
    data, offs = build_dat()
    assert plugin.detect("Test.dat", data[:0x40], len(data))
    assert not plugin.detect("Test.dat", data[:0x40], len(data) + 1)
    dat = hsd.DatFile(data)
    assert dat.version == "001B"
    assert [r.name for r in dat.roots] == ["TestModel_joint", "Orange_RGB565_image"]
    assert dat.roots[0].offset == offs["root"]
    assert dat.is_ptr_field(offs["root"] + 8)  # child pointer
    assert not dat.is_ptr_field(offs["root"] + 4)  # flags
    assert offs["child"] in dat.pointers


def test_jobj_tree_and_pobj():
    data, offs = build_dat()
    dat = hsd.DatFile(data)
    p = hsd.Parser(dat)
    models = hsd.models(dat, p)
    assert [m.name for m in models] == ["TestModel"]
    root = models[0].roots[0]
    assert root.offset == offs["root"] and len(root.children) == 1
    child = root.children[0]
    assert child.position == (0.0, 2.0, 0.0)
    assert child.inv_bind is not None and child.inv_bind[1, 3] == -2.0
    (pobj,) = root.dobjs[0].pobjs
    assert pobj.ptype == hsd.POBJ_ENVELOPE
    assert [e.entries for e in pobj.envelopes] == [[(offs["root"], 1.0)], [(offs["child"], 1.0)]]
    assert [a.attr for a in pobj.attrs] == [hsd.VA_PNMTXIDX, hsd.VA_POS, hsd.VA_TEX0]
    calls = hsd.parse_display_list(pobj.display, pobj.attrs)
    assert [(c.opcode, c.count) for c in calls] == [(0x98, 4), (0x90, 3)]
    assert calls[0].fields[hsd.VA_POS].tolist() == [0, 1, 2, 3]
    mobj = root.dobjs[0].mobj
    assert mobj.tobjs[0].image.fmt == 4 and mobj.tobjs[0].image.width == 4
    order, world = hsd.world_matrices(models[0].roots)
    assert [j.index for j in order] == [0, 1] and order[1].parent == 0
    assert np.allclose(world[1][:3, 3], (0, 2, 0))
    assert np.allclose(world[1][:3, :3], [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-6)


def test_scene_and_export(tmp_path):
    data, offs = build_dat()
    scenes = plugin.extract(data, "Test.dat", None)
    assert len(scenes) == 1
    s = scenes[0]
    assert len(s.joints) == 2 and s.joints[1].parent == 0
    assert s.triangles == 3
    (prim,) = s.primitives
    # right edge (vertices 2, 3) is bound to the child: rotated 90 degrees about Z at y=2
    pos = {tuple(np.round(p, 4)) for p in prim.positions}
    assert (-1.0, 0.0, 0.0) in pos and (-1.0, 1.0, 0.0) in pos
    assert (0.0, 3.0, 0.0) in pos and (-1.0, 3.0, 0.0) in pos
    assert prim.uvs is not None and prim.uvs.max() <= 1.0
    assert prim.joints is not None and set(prim.joints[:, 0].tolist()) == {0, 1}
    assert s.materials[0].texture == "Orange"
    tex = s.textures["Orange"]
    assert tex.shape == (4, 4, 4) and tuple(tex[0, 0]) == (255, 255, 0, 255)
    assert not s.materials[0].double_sided and not s.materials[0].unlit
    st = gltf.export(s, tmp_path / "test")
    assert st.triangles == 3 and st.joints == 2 and st.textures == 1
    g = json.loads((tmp_path / "test.gltf").read_text())
    assert g["skins"][0]["joints"] == [0, 1]
    assert (tmp_path / "test_tex" / "Orange.png").exists()
    assert gltf.thumbnail(st, tmp_path / "test") is not None


def test_texture_cache_names():
    data, offs = build_dat()
    dat = hsd.DatFile(data)
    names = plugin._image_names(dat)
    assert names == {offs["img"]: "Orange"}
    cache = hsd_eval.TextureCache(dat, names, "Test")
    tobj = hsd.Parser(dat).jobj(offs["root"]).dobjs[0].mobj.tobjs[0]
    assert cache.get(tobj)[0] == "Orange"
    assert cache.get(tobj) is cache.get(tobj)


def _figatree_archive(joint_count: int) -> bytes:
    """One-figatree archive: joint 1 gets a ROTZ track (CON 0 -> LIN to pi/2 at frame 10
    -> SPL back to 0 at frame 20) and a TRAX track (CON 1.0)."""
    b = _Builder()
    rotz = bytes([0x02, 0x00, 0x00, 0x00])  # LIN x1: value f32 0.0, wait 0 ... (see below)
    # stream, little endian: LIN(op 2, 1 key): value=0.0 f32, wait 10;
    # SPL(op 4, 1 key): value=pi/2 f32, slope 0.0 f32, wait 10; CON(op 1): value 0, wait 0
    rotz = (
        bytes([0x02]) + struct.pack("<f", 0.0) + bytes([10])
        + bytes([0x04]) + struct.pack("<f", math.pi / 2) + struct.pack("<f", 0.0) + bytes([10])
        + bytes([0x01]) + struct.pack("<f", 0.0) + bytes([0])
    )
    trax = bytes([0x01]) + struct.pack("<h", 0x0100) + bytes([0])  # s16 frac 8 -> 1.0
    rotz_off = b.add(rotz, 32)
    trax_off = b.add(trax, 4)
    counts = b.add(bytes([0] * 1 + [2] + [0] * (joint_count - 2) + [0xFF]), 4)
    tracks = b.struct(
        [("H", len(rotz)), ("H", 0), ("B", 3), ("B", 0), ("B", 0), ("B", 0), ("I", rotz_off)]
        + [("H", len(trax)), ("H", 0), ("B", 5), ("B", 0x28), ("B", 0), ("B", 0), ("I", trax_off)]
    )
    tree = b.struct([("I", 1), ("I", 0), ("f", 20.0), ("p", counts), ("p", tracks)])
    one = b.finish([("Test_ACTION_Wave_figatree", tree)])
    return one + b"\0" * (-len(one) % 32) + one


def test_figatree_clip():
    from gcrip.formats import hsd_anim

    data, offs = build_dat()
    archive = _figatree_archive(2)
    assert hsd_anim.is_archive(archive) and len(hsd_anim.split_archive(archive)) == 2
    sub = hsd.DatFile(archive[: hsd_anim.split_archive(archive)[0][1]])
    tree = hsd_anim.parse_figatree(sub, sub.roots[0].offset, "Wave")
    assert tree is not None and tree.frames == 20.0 and len(tree.joints) == 2
    (rz, tx) = tree.joints[1]
    assert rz.kind == 3
    assert [k[3] for k in rz.keys] == [hsd_anim.OP_LIN, hsd_anim.OP_SPL, hsd_anim.OP_CON]
    assert [k[0] for k in rz.keys] == [0.0, 10.0, 20.0]
    assert tx.kind == 5 and tx.keys[0][1] == 1.0
    vals = hsd_anim.sample(rz.keys, 21, 0.0)
    assert abs(vals[5] - math.pi / 4) < 1e-5  # linear half way
    assert abs(vals[10] - math.pi / 2) < 1e-5
    assert abs(vals[15] - math.pi / 4) < 1e-5  # hermite with zero slopes: symmetric midpoint
    assert abs(vals[20]) < 1e-6

    class Src:
        by_path = {"Test.dat": 1, "PlFxAJ.dat": 1}

        def get(self, p):
            assert p == "PlFxAJ.dat"
            return archive

    scenes = plugin.extract(data, "PlFxNr.dat", Src())
    (s,) = scenes
    assert len(s.clips) == 2 and s.clips[0].name == "Test_ACTION_Wave"
    clip = s.clips[0]
    assert clip.frames == 21 and clip.fps == 60.0
    assert set(clip.rotation) == {1} and set(clip.translation) == {1} and not clip.scale
    q = clip.rotation[1]
    assert np.allclose(q[0], (0, 0, 0, 1), atol=1e-6)
    assert np.allclose(q[10], (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4)), atol=1e-5)
    assert np.allclose(clip.translation[1][:, 0], 1.0)
    assert np.allclose(clip.translation[1][:, 1], 2.0)
    # not a costume file: no archive lookup
    assert not plugin.extract(data, "Test.dat", Src())[0].clips


def test_detect_rejects_other_files():
    assert not plugin.detect("foo.bmd", b"J3D2bmd3" + b"\0" * 56, 4096)
    assert not plugin.detect("foo.dat", b"\0" * 64, 64)
    assert not plugin.detect("foo.dat", struct.pack(">IIIII", 100, 50, 0, 1, 0) + b"\0" * 44, 200)
