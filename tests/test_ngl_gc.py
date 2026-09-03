"""Treyarch NGL (Ultimate Spider-Man / Spider-Man 2): the amalgapak directory, a pack's
mashed resource directory, GCNM mesh files (static display lists with per-list VCDs and
index rebasing, CPU-skinned sections), GCNT textures and the plugin chain."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ngl_gc
from gcrip.plugins import ngl_mesh, treyarch_pak

USM_VERSIONS = (0xE, 0x24D, 0x12D, 0x249, 0x115)
SM2_VERSIONS = (0xB, 0x3D6, 0x333, 0x197)


def al(b: bytes, n: int) -> bytes:
    return b + b"\0" * (-len(b) % n)


# ---------------------------------------------------------------------------
# GCNM builder
# ---------------------------------------------------------------------------


class Gcnm:
    """Lays a mesh file out the way the exporter does: header, directory, objects, names."""

    def __init__(self, entries: int, version: int = 0x1F):
        self.version = version
        # the header and the directory (12 bytes an entry) come first, the objects after
        self.body = bytearray(0x20 + 12 * entries)
        self.entries: list[tuple[int, int, int, int]] = []
        self.names: dict[str, int] = {}

    def put(self, blob: bytes, align: int = 4) -> int:
        while len(self.body) % align:
            self.body.append(0)
        at = len(self.body)
        self.body += blob
        return at

    def name(self, text: str) -> int:
        if text not in self.names:
            self.names[text] = self.put(
                struct.pack(">I", ngl_gc.name_hash(text)) + text.encode().ljust(28, b"\0")
            )
        return self.names[text]

    def material(self, name: str, shader: str, textures: list[str]) -> None:
        words = [self.name(name), self.name(shader), 0, 0, 2, 0] + [self.name(t) for t in textures]
        obj = self.put(struct.pack(f">{len(words)}I", *words))
        self.entries.append((1, 4 * len(words), obj, self.name(name)))

    def section(
        self,
        material: str,
        nverts: int,
        attrs: list[tuple[int, int, int]],
        vat: int,
        lists: list[tuple[int, int, bytes]],
        rebase: list[list[int]],
        skin: int = 0,
    ) -> int:
        """attrs: (GX attribute, stride, array offset); lists: (vcd lo, vcd hi, bytes);
        rebase: per extra list the (slot << 24 | base) records."""
        attr_table = self.put(
            b"".join(struct.pack(">II", a << 24 | st, off) for a, st, off in attrs)
        )
        dl_offs, dl_sizes = [], []
        for _, _, blob in lists:
            dl_offs.append(self.put(al(blob, 32), 32))
            dl_sizes.append(len(al(blob, 32)))
        offs = self.put(struct.pack(f">{len(lists)}I", *dl_offs))
        sizes = self.put(struct.pack(f">{len(lists)}I", *dl_sizes))
        vcds = self.put(b"".join(struct.pack(">II", lo, hi) for lo, hi, _ in lists))
        rb = 0
        if rebase:
            recs = [self.put(struct.pack(f">{len(r)}I", *r)) if r else 0 for r in rebase]
            rb = self.put(
                b"".join(struct.pack(">II", len(r), p) for r, p in zip(rebase, recs, strict=True))
            )
        X = self.put(
            struct.pack(">I6I", 0, vat, 0x80000000, 0, 0x7FE1E1FF, 0x80000000, 0)
            + struct.pack(">HHI", len(lists) - 1, len(attrs), 0x11)
            + struct.pack(">5I", attr_table, rb, offs, sizes, vcds)
        )
        sec = struct.pack(">5f", 1.0, 0, 0, 0, 1.0) + struct.pack(">4I", nverts, 1, 0, 1)
        sec += struct.pack(">4I", X, skin, 0, 0) + struct.pack(">I", self.name(material))
        sec += b"\0" * 0x30
        return self.put(sec)

    def mesh(self, name: str, sections: list[int], bones: np.ndarray | None = None) -> None:
        table = self.put(b"".join(struct.pack(">II", 0, s) for s in sections))
        bone_at = self.put(bones.astype(">f4").tobytes(), 32) if bones is not None else 0
        m = struct.pack(">4I", self.name(name), 0, len(sections), table)
        m += struct.pack(">4I", 0 if bones is None else len(bones), bone_at, 0, 0)
        m += struct.pack(">4f", 0, 0, 0, 1) + struct.pack(">f", 10.0) + b"\0" * 12
        obj = self.put(m)
        self.entries.append((2, len(m), obj, self.name(name)))

    def build(self) -> bytes:
        body = bytearray(self.body)
        head = b"GCNM" + struct.pack(">4I", self.version, len(self.entries), 0x20, 0)
        body[:0x20] = head.ljust(0x20, b"\0")
        for i, (k, sz, obj, nm) in enumerate(self.entries):
            body[0x20 + 12 * i : 0x2C + 12 * i] = struct.pack(">III", k << 24 | sz, obj, nm)
        return bytes(body)


def static_file() -> bytes:
    """One mesh, two display lists: a quad (index8) and, after a rebase to array entry 2, a
    triangle whose position indices are index16 and read 0..2 relative to that base."""
    g = Gcnm(2)
    g.material("crate", "smsimple", ["crate_tex", "crate_spheremap"])
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1], [2, 0, 2]], ">f4")
    uv = (np.array([[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]]) * 4096).astype(">i2")
    col = np.array([0xF00F, 0x0F0F, 0x00FF, 0xFFFF, 0x8888], ">u2")  # RGBA4
    p_at = g.put(pos.tobytes(), 32)
    c_at = g.put(col.tobytes(), 32)
    t_at = g.put(uv.tobytes(), 32)
    vat = 1 | (4 << 1) | (1 << 13) | (3 << 14) | (1 << 21) | (3 << 22) | (12 << 25)
    dl0 = b"\x98" + struct.pack(">H", 4) + bytes([0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3])
    dl1 = (
        b"\x90" + struct.pack(">H", 3) + struct.pack(">HBB", 0, 2, 2) + struct.pack(">HBB", 1, 3, 3)
    )
    dl1 += struct.pack(">HBB", 2, 4, 4)
    sec = g.section(
        "crate",
        5,
        [(9, 12, p_at), (11, 2, c_at), (13, 4, t_at)],
        vat,
        [(0x4400, 2, dl0), (0x4600, 2, dl1)],
        [[0 << 24 | 2]],
    )
    g.mesh("crate000", [sec])
    return g.build()


def skinned_file() -> bytes:
    """A triangle skinned on the CPU: vertex 0 by bone 1, vertices 1-2 blended between bones
    1 and 2, and bone 3 adding a third weight to vertex 2 through an op-7 record."""
    g = Gcnm(2)
    g.material("skin", "usperson", ["skin_tex"])
    recs = np.array(
        [
            [8192, 0, 0, 0, 16384, 0],
            [0, 8192, 0, 0, 16384, 0],
            [0, 0, 8192, 0, 16384, 0],
            [0, 0, 8192, 16384, 0, 0],
        ],
        ">i2",
    )
    src = g.put(recs.tobytes(), 32)
    weights = g.put(struct.pack(">HH", 0xC03F, 0x8040) + struct.pack(">HH", 0x4000, 2), 32)
    program = struct.pack(">11H", 1, 0x0102, 4, 1, 6, 2, 2, 3, 7, 1, 0xA)
    prog = g.put(program, 32)
    desc = struct.pack(">HH4I", 6, 3, src, weights, prog, 13 << 24) + b"\0" * 12
    descs = g.put(desc + struct.pack(">HH4I", 1, 3, 0x401, 0, 0, 0) + b"\0" * 12, 32)
    skin = g.put(struct.pack(">HHI", 2, 0, descs))
    uv = (np.array([[0, 0], [1, 0], [0, 1]]) * 512).astype(">i2")
    t_at = g.put(uv.tobytes(), 32)
    vat = 1 | (3 << 1) | (13 << 4) | (3 << 10) | (1 << 21) | (3 << 22) | (9 << 25)
    dl = (
        b"\x90" + struct.pack(">H", 3) + struct.pack(">HHH", 0, 0, 0) + struct.pack(">HHH", 1, 1, 1)
    )
    dl += struct.pack(">HHH", 2, 2, 2)
    sec = g.section(
        "skin", 3, [(9, 12, 0), (10, 12, 0), (13, 4, t_at)], vat, [(0x1E00, 3, dl)], [], skin
    )
    bones = np.tile(np.eye(4, dtype=np.float32), (4, 1, 1))
    bones[1, 3, :3] = (0, 1, 0)
    g.mesh("hero000", [sec], bones)
    return g.build()


def gct(
    fmt: int = 4, pixels: bytes | None = None, w: int = 4, h: int = 4, pal: bytes = b""
) -> bytes:
    """A GCNT v3: 4x4 RGB565 by default, pixel (0,0) green and the rest red."""
    if pixels is None:
        pixels = struct.pack(">16H", 0x07E0, *([0xF800] * 15))
    hdr = b"GCNT" + struct.pack(">I", 3) + struct.pack(">HHI", 0x40, 0, len(pixels))
    hdr += struct.pack(">HHBBBB", w, h, fmt, 2, 1, 0) + b"\0" * 8
    return hdr.ljust(0x40, b"\0") + pixels + pal


# ---------------------------------------------------------------------------
# pack / amalgapak builders
# ---------------------------------------------------------------------------


def pack(resources: list[tuple[int, str, bytes]], layout: ngl_gc.Layout = ngl_gc.USM) -> bytes:
    """A resource pack: header, mashed directory (only the tlresource vectors filled), data."""
    lay = layout
    versions = USM_VERSIONS if lay is ngl_gc.USM else SM2_VERSIONS
    data = b""
    placed = []
    for kind, name, blob in resources:
        placed.append((kind, name, len(data), len(blob)))
        data += al(blob, 32)
    by_kind: dict[int, list] = {}
    for kind, name, off, size in placed:
        by_kind.setdefault(kind, []).append((name, off, size))
    obj = bytearray(lay.obj_size)
    tail = b""
    at = 0x30 + 16 + lay.obj_size  # absolute position of the vector contents
    for i in range(lay.vectors):
        rows = by_kind.get(i - 1, []) if i >= 2 else []
        struct.pack_into(">IHBB", obj, 8 * i, 0, len(rows), 0, 1)
        pad = -(at + len(tail)) % 8
        tail += b"\0" * pad
        for name, off, size in rows:
            kind = i - 1
            if lay.name_len:
                tail += struct.pack(">I", ngl_gc.name_hash(name))
                tail += name.encode().ljust(lay.name_len, b"\0")
                tail += struct.pack(">II", size << 8 | kind, off)
            else:
                tail += struct.pack(">III", ngl_gc.name_hash(name), size << 8 | kind, off)
        tail += b"\0" * (-(at + len(tail)) % 4)
    mash_body = bytes(obj) + tail
    mash = struct.pack(">IIIHH", 0x7BAEC21C, 0, 16 + len(mash_body), 0xFFFF, 0) + mash_body
    base = al(b"\0" * (0x30 + len(mash)), 32)
    header = struct.pack(f">{len(versions)}I", *versions) + struct.pack(
        ">IIIII", 0, 0x30, len(base), len(base) + len(data), 0
    )
    header = header.ljust(0x30, b"\0")
    return header + mash + b"\0" * (len(base) - 0x30 - len(mash)) + data


def amalgapak(packs: list[tuple[str, bytes]], layout: ngl_gc.Layout = ngl_gc.USM) -> bytes:
    lay = layout
    versions = USM_VERSIONS if lay is ngl_gc.USM else SM2_VERSIONS
    hsz = 4 * (lay.versions + lay.pak_extra + 8)
    dirsz = lay.entry * len(packs)
    delta = al(b"\0" * (hsz + dirsz), 0x800)
    entries = b""
    data = b""
    for i, (name, blob) in enumerate(packs):
        e = bytearray(lay.entry)
        e[lay.entry_name : lay.entry_name + len(name)] = name.encode()
        struct.pack_into(">III", e, lay.entry_fields, 0x19, len(data), len(blob))
        struct.pack_into(">II", e, lay.entry_fields + 20, i, 1)
        entries += bytes(e)
        data += al(blob, 0x800)
    head = struct.pack(f">{len(versions)}I", *versions)
    if lay.pak_extra:
        head += struct.pack(">I", 0x1E190000)
    head += struct.pack(">III", len(delta), hsz, dirsz) + struct.pack(">III", hsz + dirsz, 0, 0)
    head = head.ljust(hsz, b"\0")
    return (head + entries).ljust(len(delta), b"\0") + data


class FakeSrc:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path: str) -> bytes:
        return self.files[path]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_name_hash_and_ifl():
    assert ngl_gc.name_hash("venom_eye_01") == 0x8983B1A7
    assert ngl_gc.name_hash("DMG_DEBRIS_TRSHCAN") == 0x3AABE462
    assert ngl_gc.ifl_frames(b"venom_eye_01.tga\r\nvenom_eye_02.tga\r\n") == [
        "venom_eye_01",
        "venom_eye_02",
    ]
    assert ngl_gc.is_ifl(b"venom_eye_01.tga\r\nvenom_eye_02.tga\r\n")
    assert not ngl_gc.is_ifl(gct()[:64])


def test_static_mesh_lists_rebase_and_go_index16():
    f = static_file()
    assert ngl_gc.is_gcnm(f[:20], len(f))
    mf = ngl_gc.parse_gcnm(f)
    assert mf.warnings == []
    assert [m.name for m in mf.meshes] == ["crate000"]
    assert mf.materials["crate"].textures == [
        (ngl_gc.name_hash("crate_tex"), "crate_tex"),
        (ngl_gc.name_hash("crate_spheremap"), "crate_spheremap"),
    ]
    sec = mf.meshes[0].sections[0]
    # list 0: a 4-vertex strip = 2 triangles; list 1: a triangle on entries 2, 3, 4
    assert len(sec.triangles) == 3
    np.testing.assert_allclose(sec.positions[:4], [[0, 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1]])
    np.testing.assert_allclose(sec.positions[4:], [[0, 0, 1], [1, 0, 1], [2, 0, 2]])
    np.testing.assert_allclose(sec.uvs[6], [0.5, 0.5])
    assert sec.colors[0].tolist() == [255, 0, 0, 255]
    assert sec.joints is None


def test_skinned_section_runs_the_program():
    mf = ngl_gc.parse_gcnm(skinned_file())
    assert mf.warnings == []
    mesh = mf.meshes[0]
    assert mesh.bones.shape == (4, 4, 4)
    sec = mesh.sections[0]
    np.testing.assert_allclose(sec.positions, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    np.testing.assert_allclose(sec.normals, [[0, 1, 0], [0, 1, 0], [0, 1, 0]])
    assert sec.joints[0].tolist() == [1, 0, 0, 0] and sec.weights[0].tolist() == [1, 0, 0, 0]
    # 0xC03F: 0xC0/255 on bone 1, 0x3F/255 on bone 2
    np.testing.assert_allclose(sec.weights[1][:2], [0xC0 / 255, 0x3F / 255])
    assert sec.joints[1][:2].tolist() == [1, 2]
    # vertex 2: blended 0x80/0x40 then bone 3 adds 0x40 through the op-7 record
    pairs = sorted(zip(sec.joints[2].tolist(), sec.weights[2].tolist(), strict=True))[1:]
    assert [b for b, _ in pairs] == [1, 2, 3]
    np.testing.assert_allclose(
        [w for _, w in pairs], [0x80 / 255, 0x40 / 255, 0x40 / 255], rtol=1e-5
    )


def test_gct_decodes_and_palette_follows_the_tiles():
    img = ngl_gc.decode_gct(gct())
    assert img.shape == (4, 4, 4)
    assert tuple(img[0, 0]) == (0, 255, 0, 255) and tuple(img[3, 3]) == (255, 0, 0, 255)
    # C4: 8x8 tile of index 1 except the first pixel, palette RGB5A3 entry 0 green, 1 red
    tile = bytes([0x01] + [0x11] * 31)
    pal = struct.pack(">16H", 0x83E0, 0xFC00, *([0] * 14))
    img = ngl_gc.decode_gct(gct(8, tile, 8, 8, pal))
    assert tuple(img[0, 0]) == (0, 255, 0, 255) and tuple(img[0, 1]) == (255, 0, 0, 255)


def test_pack_directory_both_layouts():
    tex = gct()
    for layout in (ngl_gc.USM, ngl_gc.SM2):
        blob = pack(
            [(1, "crate_tex", tex), (2, "crate", static_file()), (6, "mats", static_file())], layout
        )
        assert ngl_gc.is_pack(blob[:64])
        pk = ngl_gc.parse_pack(blob)
        assert [r.hash for r in pk.textures] == [ngl_gc.name_hash("crate_tex")]
        assert ngl_gc.resource_bytes(blob, pk.textures[0]) == tex
        assert len(pk.mesh_files) == 1 and len(pk.material_files) == 1
        assert pk.mesh_files[0].name == ("" if layout is ngl_gc.USM else "crate")
        assert ngl_gc.resource_bytes(blob, pk.mesh_files[0]) == static_file()


def test_amalgapak_container_and_mesh_plugin():
    for layout in (ngl_gc.USM, ngl_gc.SM2):
        p1 = pack([(1, "crate_tex", gct()), (2, "crate", static_file())], layout)
        p2 = pack(
            [(1, "skin_tex", gct()), (1, "anim", b"skin_tex.tga\r\n"), (2, "hero", skinned_file())],
            layout,
        )
        data = amalgapak([("AB", p1), ("HERO", p2)], layout)
        assert ngl_gc.is_amalgapak(data[:64], len(data))
        assert treyarch_pak.is_container("amalga_gc.pak", data[:64])
        members = dict(treyarch_pak.expand(data))
        exts = sorted(n.rsplit(".", 1)[1] for n in members)
        assert exts == ["gcmesh", "gcmesh", "gct", "gct", "ifl"]
        assert all(n.split("/")[0] in ("AB", "HERO") for n in members)
        files = {f"files/packs/amalga_gc.pak/{n}": b for n, b in members.items()}
        src = FakeSrc(files)
        scenes = {}
        for path, blob in files.items():
            if ngl_mesh.detect(path, blob[:64], len(blob)):
                for sc in ngl_mesh.extract(blob, path, src):
                    scenes[path.split("/")[3]] = sc
        crate = scenes["AB"]
        assert crate.materials[0].texture == "crate_tex" and "crate_tex" in crate.textures
        assert crate.warnings == [] and crate.joints == []
        hero = scenes["HERO"]
        assert len(hero.joints) == 4 and hero.joints[1].translation == (0.0, 1.0, 0.0)
        assert hero.primitives[0].joints[0].tolist() == [1, 0, 0, 0]
        assert hero.materials[0].texture == "skin_tex"
