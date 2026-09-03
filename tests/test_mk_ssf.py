"""Midway SEC archives (Mortal Kombat: Deception / Deadly Alliance): the directory, the
texture members with their alignment filler, and RenderWare clumps written "in place"
(material list + native STRUCT inside the geometry struct) with PAD32 text in the data."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import mk_ssf, rwgc
from gcrip.formats import rwstream as rw
from gcrip.plugins import mk_ssf as container
from gcrip.plugins import renderware as plugin
from tests.test_renderware import (
    LIB35,
    FakeSrc,
    chunk,
    frame_list,
    material,
    matlist,
    pad32,
    st,
)

LIB36 = 0x1803FFFF
LIB32 = 0x0800FFFF
PAD = b"PAD32PAD32PA"


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def sec_block(entries: list[tuple[int, str, bytes]], named: bool = True) -> bytes:
    """A SEC block: (kind, name, payload) entries; Deadly Alliance blocks carry no names."""
    names = b""
    noffs = []
    for _, name, _ in entries:
        noffs.append(len(names))
        names += name.encode() + b"\0"
    if not named:
        names = b""
    head = mk_ssf.HEADER if named else mk_ssf.HEADER_UNNAMED
    entry = mk_ssf.ENTRY if named else mk_ssf.ENTRY_UNNAMED
    data_at = head + entry * len(entries) + len(names)
    data_at += -data_at % 32
    table = b""
    blobs = b""
    for (kind, _, blob), noff in zip(entries, noffs, strict=True):
        off = data_at + len(blobs)
        table += struct.pack(">III", kind, off, len(blob))
        if named:
            table += struct.pack(">I", noff)
        blobs += blob + b"\0" * (-len(blob) % 32)
    if named:
        header = struct.pack(">4sIIIIII", b"SEC ", 4, 0, 0, len(entries), len(names), len(blobs))
    else:
        header = struct.pack(">4sIIIII", b"SEC ", 4, 0, 0, len(entries), len(blobs))
    body = header + table + names
    body += b"\0" * (data_at - len(body))
    return body + blobs


def sec_archive(entries: list[tuple[int, str, bytes]], named: bool = True) -> bytes:
    """The root block holds one nested block at 0x800."""
    inner = sec_block(entries, named)
    kind = mk_ssf.NESTED if named else mk_ssf.NESTED_DA
    root = sec_block([(kind, "", inner)], named)
    # the real root places its child at 0x800; the reader follows the offset either way
    return root


def mk_native(positions, uvs, strips, direct: bool) -> bytes:
    """A bare GameCube native STRUCT the way Midway writes it: S16 texcoords with no fraction
    bits in the table (the game sets 11 in code), the data behind PAD32 filler that the data
    size counts."""
    dl = b""
    for strip in strips:
        dl += b"\x98" + struct.pack(">H", len(strip))
        for mtx, pi, ti in strip:
            dl += (bytes([mtx]) if direct else b"") + bytes([pi, ti])
    dl = pad32(dl)
    pos = pad32(b"".join(struct.pack(">3f", *p) for p in positions))
    uv = pad32(b"".join(struct.pack(">2h", *t) for t in uvs))
    data = dl + pos + uv
    header = struct.pack(">3I", 0x0C4B0100, 0, 2)
    header += struct.pack(">IBBBB", len(dl), rwgc.GX_POS, 12, 2, 0)
    header += struct.pack(">IBBBB", len(dl) + len(pos), rwgc.GX_TEX0, 4, 2, 0)
    header += struct.pack(">II", 0, len(dl))
    payload = PAD + data
    body = struct.pack("<3I", 6, len(header), len(payload)) + header + payload
    return chunk(rw.STRUCT, body, LIB36)


def mk_skin(num_bones: int, used: list[int]) -> bytes:
    """The skin's own native STRUCT (maxWeights 1: the display list carries PNMTXIDX)."""
    body = struct.pack("<I4B", 6, num_bones, len(used), 1, 0) + bytes(used)
    body += np.tile(np.eye(4, dtype=">f4"), (num_bones, 1, 1)).tobytes()
    return chunk(rw.STRUCT, body, LIB36)


def mk_clump(skinned: bool = False, texture: str = "KAMIDOGU_EARTH_000") -> bytes:
    positions = [(0, 0, 0), (2, 0, 0), (0, 0, 2)]
    uvs = [(0, 0), (2048, 0), (0, 1024)]  # S16 / 2**11 -> (1, 0), (0, 0.5)
    strips = [[(0, 0, 0), (0, 1, 1), (0, 2, 2)]]
    native = mk_native(positions, uvs, strips, skinned)
    inner = matlist([material(texture)]) + chunk(rw.EXTENSION, b"", LIB36) + native
    if skinned:
        inner += mk_skin(2, [1])
    # the geometry STRUCT is declared as the whole geometry: header, morph target, then the
    # material list, the extension and the native structs sit inside it
    head = struct.pack("<4I", 0x01000007, 1, 3, 1) + struct.pack("<4f2I", 0, 0, 0, 1, 1, 0)
    geometry = chunk(rw.GEOMETRY, chunk(rw.STRUCT, head + inner, LIB36), LIB36)
    geomlist = chunk(rw.GEOMLIST, st(struct.pack("<I", 1), LIB36) + geometry, LIB36)
    atomic = chunk(
        rw.ATOMIC, st(struct.pack("<4I", 1, 0, 5, 0), LIB36) + chunk(rw.EXTENSION, b"", LIB36)
    )
    frames = frame_list([((0, 0, 0), -1), ((0, 1, 0), 0)], [0, 1] if skinned else None)
    body = st(struct.pack("<3I", 1, 0, 0), LIB36) + frames + geomlist + atomic
    body += chunk(rw.EXTENSION, b"", LIB36)
    return chunk(rw.CLUMP, body, LIB36)


def mk_texture(name: str = "KAMIDOGU_EARTH_000", old: bool = False) -> bytes:
    """A type-3 member: u8 n, name, NUL, seven bytes, then the Texture Native STRUCT with
    PAD128 filler counted in the raster size.  4x4 RGB565, pixel (0,0) green, the rest red."""
    px = [0x07E0] + [0xF800] * 15
    raster = struct.pack(">16H", *px)
    filler = b"PAD128PAD128PAD1"
    if old:
        # RW 3.2 layout: 72 bytes of platform / filter / addressing / names, then
        # raster format, 0, w, h, depth, mips, type, compressed, size
        body = struct.pack(">II", 6, 0x1101) + b"\0" * 64
        body += struct.pack(">IIHHBBBB", 0x200, 0, 4, 4, 16, 1, 4, 0)
        body += struct.pack(">I", len(filler) + len(raster)) + filler + raster
        lib = LIB32
    else:
        body = struct.pack(">6I", 6, 0x1101, 0, 1, 1, 0) + b"\0" * 64
        body += struct.pack(">IHHBBBB", 0x204, 4, 4, 16, 1, 4, 0xFF)
        body += struct.pack(">II", 0, len(filler) + len(raster)) + filler + raster
        lib = LIB36
    prefix = bytes([len(name)]) + name.encode() + b"\0" + b"\0" * 7
    return prefix + chunk(rw.STRUCT, body, lib)


def deception_archive(skinned: bool = False) -> bytes:
    return sec_archive(
        [
            (mk_ssf.CLUMP, "KAMIDOGU_EARTH", b"\0" * mk_ssf.CLUMP_PREFIX + mk_clump(skinned)),
            (mk_ssf.TEXTURE, "KAMIDOGU_EARTH_000", mk_texture()),
            (7, "KAMIDOGU_EARTH", b"\x01\x02\x03\x04"),
        ]
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_deception_directory():
    data = deception_archive()
    assert mk_ssf.is_ssf(data[:64])
    ms = mk_ssf.members(data)
    assert [(m.name, m.kind) for m in ms] == [
        ("KAMIDOGU_EARTH", mk_ssf.CLUMP),
        ("KAMIDOGU_EARTH_000", mk_ssf.TEXTURE),
        ("KAMIDOGU_EARTH", 7),
    ]
    assert ms[0].data[mk_ssf.CLUMP_PREFIX :] == mk_clump()
    assert ms[2].data == b"\x01\x02\x03\x04"


def test_deadly_alliance_directory_has_no_names():
    tex = mk_texture("GRASS", old=True)
    data = sec_archive([(mk_ssf.TEXTURE, "", tex), (mk_ssf.TEXTURE, "", tex)], named=False)
    ms = mk_ssf.members(data)
    assert [(m.name, m.kind) for m in ms] == [("", mk_ssf.TEXTURE), ("", mk_ssf.TEXTURE)]
    assert ms[0].data == tex
    out = container.expand(data)
    assert [n for n, _ in out] == ["member.mktex", "member_1.mktex"]


def test_container_names_members():
    data = deception_archive()
    assert container.is_container("kamidogu.ssf", data[:64])
    assert not container.is_container("kamidogu.bin", data[:64])
    out = container.expand(data)
    assert [n for n, _ in out] == [
        "KAMIDOGU_EARTH.mkdff",
        "KAMIDOGU_EARTH_000.mktex",
        "KAMIDOGU_EARTH_1.bin",
    ]
    assert out[0][1] == mk_clump()


def test_texture_member_skips_prefix_and_filler():
    blob = mk_texture()
    assert mk_ssf.texture_name(blob) == "KAMIDOGU_EARTH_000"
    t = mk_ssf.parse_texture(blob)
    assert t.error is None and (t.width, t.height) == (4, 4)
    assert tuple(t.image[0, 0]) == (0, 255, 0, 255)
    assert tuple(t.image[3, 3]) == (255, 0, 0, 255)


def test_deadly_alliance_texture_uses_old_raster_layout():
    t = mk_ssf.parse_texture(mk_texture("GRASS", old=True))
    assert t.error is None and t.name == "GRASS"
    assert tuple(t.image[0, 0]) == (0, 255, 0, 255)
    assert tuple(t.image[1, 1]) == (255, 0, 0, 255)


def test_skip_pad_stops_at_the_boundary():
    assert rwgc.skip_pad(b"PAD32PAD32PA\x98\x00", 0) == 12
    assert rwgc.skip_pad(b"\x98\x00\x03", 0) == 0


def test_inplace_geometry_reads_materials_and_native_data():
    g = rw.parse_clump(mk_clump()).geometries[0]
    assert [m.texture for m in g.materials] == ["KAMIDOGU_EARTH_000"]
    assert g.native is not None and g.skin is None
    meshes = rwgc.decode_native(g.native, False, plugin.MK_FRACS)
    assert len(meshes) == 1
    m = meshes[0]
    np.testing.assert_allclose(m.positions, [[0, 0, 0], [2, 0, 0], [0, 0, 2]])
    np.testing.assert_allclose(m.uvs, [[0, 0], [1, 0], [0, 0.5]])


def test_inplace_skin_struct_is_not_mistaken_for_native_data():
    g = rw.parse_clump(mk_clump(skinned=True)).geometries[0]
    assert g.native is not None
    assert g.skin is not None and g.skin.max_weights == 1 and g.skin.used_bones == [1]
    assert g.skin.indices is None


def test_scene_from_archive_binds_texture_and_bone():
    data = deception_archive(skinned=True)
    files = {f"kamidogu.ssf/{n}": b for n, b in container.expand(data)}
    src = FakeSrc(files)
    path = "kamidogu.ssf/KAMIDOGU_EARTH.mkdff"
    scenes = plugin.extract(files[path], path, src)
    assert len(scenes) == 1
    sc = scenes[0]
    p = sc.primitives[0]
    assert p.indices.tolist() == [0, 1, 2]
    np.testing.assert_allclose(p.uvs, [[0, 0], [1, 0], [0, 0.5]])
    # PNMTXIDX 0 -> used_bones[0] = bone 1 -> HAnim id 1 -> frame 1
    assert p.joints[:, 0].tolist() == [1, 1, 1]
    assert sc.materials[0].texture == "KAMIDOGU_EARTH_000"
    assert "kamidogu_earth_000" in {k.lower() for k in sc.textures}
    assert sc.warnings == []


def test_big_endian_rw32_geometry():
    """Deadly Alliance's RW 3.2 clumps write the vertex payload big-endian with
    (v0, v1, v2, material) triangles; little-endian streams keep the usual order."""
    ntri, nvert = 1, 3
    uvs = np.array([[0, 0], [1, 0], [0, 1]], ">f4")
    tris = np.array([[0, 1, 2, 0]], ">u2")
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], ">f4")
    body = struct.pack("<4I", 0x4, ntri, nvert, 1) + struct.pack("<3I", 0, 0, 0)
    body += uvs.tobytes() + tris.tobytes()
    body += struct.pack(">4f2I", 0, 0, 0, 1, 1, 0) + pos.tobytes()
    geometry = chunk(
        rw.GEOMETRY,
        chunk(rw.STRUCT, body, LIB32) + matlist([material(None)]) + chunk(rw.EXTENSION, b""),
        LIB32,
    )
    g = rw._parse_geometry(geometry, rw.top(geometry))
    assert g.triangles.tolist() == [[0, 1, 2, 0]]
    np.testing.assert_allclose(g.positions, pos.astype(np.float32))
    np.testing.assert_allclose(g.uvs[0], uvs.astype(np.float32))
    assert LIB35  # the RW 3.5 builders stay importable for the mixed archives
