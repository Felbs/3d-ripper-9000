"""RenderWare GameCube plugin on synthetic streams: ONE / HIP containers, native-data clumps,
GameCube skins, plain (RW 3.3) geometry, worlds and TXD rasters."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import hip, one, rwgc
from gcrip.formats import rwstream as rw
from gcrip.plugins import renderware as plugin

LIB35 = 0x1400FFFF
LIB33 = 0x0C02FFFF


def chunk(ctype: int, body: bytes, lib: int = LIB35) -> bytes:
    return struct.pack("<3I", ctype, len(body), lib) + body


def st(body: bytes, lib: int = LIB35) -> bytes:
    return chunk(rw.STRUCT, body, lib)


def string(s: str) -> bytes:
    b = s.encode() + b"\0"
    b += b"\0" * (-len(b) % 4)
    return chunk(rw.STRING, b)


def pad32(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 32)


def material(texture: str | None, color=(255, 255, 255, 255)) -> bytes:
    body = st(struct.pack("<I4BII3f", 0, *color, 0, 1 if texture else 0, 1.0, 1.0, 1.0))
    if texture:
        body += chunk(rw.TEXTURE, st(struct.pack("<I", 0x3102)) + string(texture) + string(""))
    body += chunk(rw.EXTENSION, b"")
    return chunk(rw.MATERIAL, body)


def matlist(mats: list[bytes]) -> bytes:
    return chunk(
        rw.MATLIST,
        st(struct.pack(f"<I{len(mats)}i", len(mats), *([-1] * len(mats)))) + b"".join(mats),
    )


def frame_list(
    frames: list[tuple[tuple[float, float, float], int]], hanim_ids: list[int] | None
) -> bytes:
    body = struct.pack("<I", len(frames))
    for pos, parent in frames:
        body += struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1) + struct.pack("<3f", *pos)
        body += struct.pack("<iI", parent, 0)
    exts = b""
    for i in range(len(frames)):
        ext = b""
        if hanim_ids is not None:
            if i == 0:
                bones = b"".join(struct.pack("<3I", bid, k, 0) for k, bid in enumerate(hanim_ids))
                ext = chunk(
                    rw.HANIM, struct.pack("<5I", 0x100, hanim_ids[0], len(hanim_ids), 0, 36) + bones
                )
            else:
                ext = chunk(rw.HANIM, struct.pack("<3I", 0x100, hanim_ids[i], 0))
        exts += chunk(rw.EXTENSION, ext)
    return chunk(rw.FRAMELIST, st(body) + exts)


def native_data(positions, uvs, strips, direct: bool) -> bytes:
    """GameCube Native Data PLG: display lists (u8 indices) then padded attribute arrays."""
    dl = b""
    for strip in strips:
        dl += b"\x98" + struct.pack(">H", len(strip))
        for mtx, pi, ti in strip:
            dl += (bytes([mtx]) if direct else b"") + bytes([pi, ti])
    dl = pad32(dl)
    pos = pad32(b"".join(struct.pack(">3f", *p) for p in positions))
    uv = pad32(b"".join(struct.pack(">2f", *t) for t in uvs))
    data = dl + pos + uv
    header = struct.pack(">3I", 0x0C4B0100, 0, 2)
    header += struct.pack(">IBBBB", len(dl), rwgc.GX_POS, 12, 2, 0)
    header += struct.pack(">IBBBB", len(dl) + len(pos), rwgc.GX_TEX0, 8, 2, 0)
    header += struct.pack(">II", 0, len(dl))
    body = struct.pack("<3I", 6, len(header), len(data)) + header + data
    return chunk(rw.NATIVEDATA, st(body))


def gc_skin(
    num_bones: int, used: list[int], per_vertex: tuple[np.ndarray, np.ndarray] | None
) -> bytes:
    mw = per_vertex[0].shape[1] if per_vertex else 1
    body = struct.pack("<I4B", 6, num_bones, len(used), mw, 0) + bytes(used)
    if per_vertex:
        idx, w = per_vertex
        body += idx.astype(np.uint8).tobytes() + np.round(w * 128).astype(np.uint8).tobytes()
    body += np.tile(np.eye(4, dtype=">f4"), (num_bones, 1, 1)).tobytes()
    body += struct.pack("<3I", 0, 0, 0)
    return chunk(rw.SKIN, st(body))


def native_clump(direct_skin: bool = False, per_vertex_skin: bool = False) -> bytes:
    positions = [(0, 0, 0), (1, 0, 0), (0, 0, 1)]
    uvs = [(0, 0), (1, 0), (0, 1)]
    strips = [[(0, 0, 0), (0, 1, 1), (0, 2, 2)]]
    ext = chunk(rw.BINMESH, struct.pack("<5I", 1, 1, 3, 3, 0))
    ext += native_data(positions, uvs, strips, direct_skin)
    if direct_skin:
        ext += gc_skin(2, [1], None)
    elif per_vertex_skin:
        idx = np.array([[0, 1], [1, 0], [1, 1]], np.uint8)
        w = np.array([[0.25, 0.75], [1.0, 0.0], [0.5, 0.5]], np.float32)
        ext += gc_skin(2, [0, 1], (idx, w))
    geom_body = st(struct.pack("<4I", 0x01000007, 1, 3, 1) + struct.pack("<4f2I", 0, 0, 0, 1, 1, 0))
    geom_body += matlist([material("tex")]) + chunk(rw.EXTENSION, ext)
    geometry = chunk(rw.GEOMETRY, geom_body)
    geomlist = chunk(rw.GEOMLIST, st(struct.pack("<I", 1)) + geometry)
    atomic = chunk(rw.ATOMIC, st(struct.pack("<4I", 1, 0, 5, 0)) + chunk(rw.EXTENSION, b""))
    frames = frame_list([((0, 0, 0), -1), ((0, 1, 0), 0)], [0, 1])
    body = st(struct.pack("<3I", 1, 0, 0)) + frames + geomlist + atomic + chunk(rw.EXTENSION, b"")
    return chunk(rw.CLUMP, body)


def rgb565_txd(name: str = "tex") -> bytes:
    """4x4 RGB565 texture: pixel (0,0) green, the rest red (one GX tile, row-major inside)."""
    px = [0x07E0] + [0xF800] * 15
    raster = struct.pack(">16H", *px)
    body = struct.pack(">6I", 6, 0x1101, 0, 1, 1, 0)
    body += name.encode().ljust(32, b"\0") + b"\0" * 32
    body += (
        struct.pack(">IHHBBBB", 0x204, 4, 4, 16, 1, 4, 0xFF)
        + struct.pack(">II", 0, len(raster))
        + raster
    )
    native = chunk(rw.TEXNATIVE, st(body) + chunk(rw.EXTENSION, b""))
    return chunk(rw.TEXDICT, st(struct.pack("<HH", 1, 0)) + native + chunk(rw.EXTENSION, b""))


# ---------------------------------------------------------------------------
# containers
# ---------------------------------------------------------------------------


def prs_store(data: bytes) -> bytes:
    """PRS stream of literals only: control bytes of 1-flags, then the 0,1 + 00 00 terminator."""
    out = bytearray()
    i = 0
    while i + 8 <= len(data):
        out.append(0xFF)
        out += data[i : i + 8]
        i += 8
    n = len(data) - i
    if n == 7:
        out.append(0x7F)
        out += data[i:]
        out.append(0x01)
    else:
        out.append(((1 << n) - 1) | (1 << (n + 1)))
        out += data[i:]
    out += b"\x00\x00"
    return bytes(out)


def one_archive(members: list[tuple[str, bytes]]) -> bytes:
    names = [b"", b""] + [n.encode() for n, _ in members]
    table = b"".join(n.ljust(64, b"\0") for n in names).ljust(256 * 64, b"\0")
    body = b""
    for i, (_, blob) in enumerate(members):
        comp = prs_store(blob)
        body += struct.pack("<3I", i + 2, len(comp), LIB35) + comp
    head = struct.pack("<3I", 0, 12 + 0x4000 + len(body), LIB35) + struct.pack(
        "<3I", 1, 0x4000, LIB35
    )
    return head + table + body


def hip_archive(assets: list[tuple[str, str, bytes]]) -> bytes:
    def block(tag: bytes, body: bytes) -> bytes:
        return tag + struct.pack(">I", len(body)) + body

    ahdrs = b""

    # layout: HIPA(0) PACK(4 bytes) DICT(...) STRM: compute DICT size first with placeholder offsets
    def build(offsets: list[int]) -> bytes:
        nonlocal ahdrs
        ahdrs = b""
        for (typ, name, blob), off in zip(assets, offsets, strict=True):
            dbg = block(
                b"ADBG", struct.pack(">I", 0) + name.encode() + b"\0" + struct.pack(">I", 0)
            )
            ahdrs += block(
                b"AHDR",
                struct.pack(">I4sIIII", 1, typ.encode().ljust(4), off, len(blob), 0, 0) + dbg,
            )
        dictb = block(b"DICT", block(b"ATOC", block(b"AINF", b"\0" * 4) + ahdrs))
        return block(b"HIPA", b"") + block(b"PACK", block(b"PVER", b"\0" * 4)) + dictb

    head = build([0] * len(assets))
    strm_head = len(head) + 8 + 8 + 4 + 8  # STRM + DHDR block + DPAK header
    offsets, blobs = [], b""
    for _, _, blob in assets:
        offsets.append(strm_head + len(blobs))
        blobs += blob
    head = build(offsets)
    return head + block(b"STRM", block(b"DHDR", b"\xff" * 4) + block(b"DPAK", blobs))


class FakeSrc:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path: str) -> bytes:
        return self.files[path]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_one_archive_roundtrip():
    members = [("A.DFF", native_clump()), ("B.TXD", rgb565_txd())]
    data = one_archive(members)
    assert one.is_one("x.one", data[:64])
    assert plugin.is_container("x.one", data[:64])
    out = plugin.expand(data)
    assert [n for n, _ in out] == ["A.DFF", "B.TXD"]
    assert out[0][1] == members[0][1] and out[1][1] == members[1][1]


def test_hip_archive_roundtrip():
    clump = native_clump()
    txd = rgb565_txd()
    data = hip_archive([("MODL", "thing.dff", clump), ("RWTX", "tex.RW3", txd)])
    assert hip.is_hip(data[:16])
    out = dict(plugin.expand(data))
    assert out == {"MODL/thing.dff": clump, "RWTX/tex.RW3": txd}


def test_detect_only_models():
    assert plugin.detect("m.dff", native_clump()[:64], len(native_clump()))
    assert not plugin.detect("t.txd", rgb565_txd()[:64], len(rgb565_txd()))
    assert not plugin.detect("x.bin", b"\x10\x00\x00\x00" + b"\0" * 60, 64)


def test_txd_rgb565():
    tex = rwgc.parse_txd(rgb565_txd())
    assert len(tex) == 1 and tex[0].name == "tex" and tex[0].error is None
    img = tex[0].image
    assert img.shape == (4, 4, 4)
    assert tuple(img[0, 0]) == (0, 255, 0, 255)
    assert tuple(img[3, 3]) == (255, 0, 0, 255)
    assert rwgc.texture_names(rgb565_txd()) == ["tex"]


def test_native_clump_scene_with_texture_lookup():
    src = FakeSrc({"files/a.one/M.DFF": native_clump(), "files/a.one/T.TXD": rgb565_txd()})
    scenes = plugin.extract(src.files["files/a.one/M.DFF"], "files/a.one/M.DFF", src)
    assert len(scenes) == 1
    sc = scenes[0]
    assert [j.name for j in sc.joints] == ["bone0", "bone1"]
    assert sc.joints[1].parent == 0 and sc.joints[1].translation == (0.0, 1.0, 0.0)
    assert len(sc.primitives) == 1
    p = sc.primitives[0]
    # atomic sits on frame 1 -> baked +1 in Y, bound rigidly to joint 1
    np.testing.assert_allclose(p.positions, [[0, 1, 0], [1, 1, 0], [0, 1, 1]])
    np.testing.assert_allclose(p.uvs, [[0, 0], [1, 0], [0, 1]])
    assert p.indices.tolist() == [0, 1, 2]
    assert p.joints[:, 0].tolist() == [1, 1, 1] and p.weights[:, 0].tolist() == [1.0, 1.0, 1.0]
    assert sc.materials[0].texture == "tex" and "tex" in sc.textures
    assert sc.extras["rw_version"] == "0x35000"


def test_direct_matrix_skin_binds_used_bone():
    src = FakeSrc({"m.dff": native_clump(direct_skin=True)})
    sc = plugin.extract(src.files["m.dff"], "m.dff", src)[0]
    p = sc.primitives[0]
    # PNMTXIDX 0 -> used_bones[0] = bone 1 -> HAnim id 1 -> frame 1
    assert p.joints[:, 0].tolist() == [1, 1, 1]
    assert sc.warnings == ["1 textures not found: tex"]


def test_per_vertex_gc_skin_weights():
    sc = plugin.clump_scene(native_clump(per_vertex_skin=True), "m")
    p = sc.primitives[0]

    # bone k -> HAnim id k -> frame k; (joint, weight) pairs are order independent
    def pairs(v):
        return sorted(zip(p.joints[v][:2].tolist(), p.weights[v][:2].tolist(), strict=True))

    assert pairs(0)[0][0] == 0 and pairs(0)[1][0] == 1
    np.testing.assert_allclose([w for _, w in pairs(0)], [0.25, 0.75], atol=1 / 128)
    np.testing.assert_allclose([w for _, w in pairs(1)], [0.0, 1.0])
    np.testing.assert_allclose([w for _, w in pairs(2)], [0.5, 0.5], atol=1 / 128)


def test_plain_geometry_rw33_has_lighting_floats():
    # flags: tristrip | positions | textured, 1 triangle, 3 vertices, 1 morph target
    body = struct.pack("<4I", 0x07, 1, 3, 1) + struct.pack("<3f", 1, 1, 1)
    body += struct.pack("<6f", 0, 0, 1, 0, 0, 1)  # uvs
    body += struct.pack("<4H", 1, 0, 0, 2)  # v2=1? layout is (v1, v0, material, v2) -> (0,1,2)
    body += struct.pack("<4f2I", 0, 0, 0, 1, 1, 0)
    body += struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 0, 2)
    geom = chunk(
        rw.GEOMETRY,
        st(body, LIB33) + matlist([material(None, (255, 0, 0, 255))]) + chunk(rw.EXTENSION, b""),
        LIB33,
    )
    geomlist = chunk(rw.GEOMLIST, st(struct.pack("<I", 1), LIB33) + geom, LIB33)
    atomic = chunk(rw.ATOMIC, st(struct.pack("<4I", 0, 0, 5, 0), LIB33), LIB33)
    frames = frame_list([((0, 0, 0), -1)], None)
    data = chunk(
        rw.CLUMP, st(struct.pack("<3I", 1, 0, 0), LIB33) + frames + geomlist + atomic, LIB33
    )
    sc = plugin.clump_scene(data, "old")
    p = sc.primitives[0]
    np.testing.assert_allclose(p.positions, [[0, 0, 0], [2, 0, 0], [0, 0, 2]])
    assert p.indices.tolist() == [0, 1, 2]
    assert sc.materials[0].base_color == (1.0, 0.0, 0.0, 1.0) and sc.materials[0].texture is None


def test_world_plain_sector():
    flags = 0x01 | 0x04 | 0x08 | 0x10000  # tristrip, textured, prelit, one uv set
    wst = struct.pack("<I3f6I6f", 1, 0, 0, 0, 1, 3, 0, 1, 0, flags, 1, 0, 1, 0, 0, 0)
    sector = struct.pack("<3I6f2I", 0, 1, 3, 1, 0, 1, 0, 0, 0, 0, 0)
    sector += struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 0, 1)
    sector += bytes([255, 0, 0, 255] * 3)
    sector += struct.pack("<6f", 0, 0, 1, 0, 0, 1)
    sector += struct.pack("<4H", 0, 0, 1, 2)  # material, v0, v1, v2
    atomic_sector = chunk(rw.ATOMIC_SECTOR, st(sector) + chunk(rw.EXTENSION, b""))
    data = chunk(
        rw.WORLD, st(wst) + matlist([material("ground")]) + atomic_sector + chunk(rw.EXTENSION, b"")
    )
    sc = plugin.world_scene(data, "w")
    assert len(sc.joints) == 1 and len(sc.primitives) == 1
    p = sc.primitives[0]
    np.testing.assert_allclose(p.positions, [[0, 0, 0], [1, 0, 0], [0, 0, 1]])
    np.testing.assert_allclose(p.colors[0], [1, 0, 0, 1])
    assert sc.materials[0].name == "ground"


def test_a_bare_version_stamp_is_accepted():
    """Older RenderWare writes the library id as a plain version number - 0x0310, 0x0304 -
    rather than a packed build stamp with 0xffff build bits.  NFL Blitz 20-03 ships 977 of its
    1,334 `.dff` that way, and every one parses; they were refused by the sniff, not by the
    reader, and fell through to the structure scanner instead."""
    import struct

    from gcrip.formats import rwstream as rw

    for lib in (0x0310, 0x0304):
        head = struct.pack("<3I", rw.CLUMP, 64, lib)
        assert rw.looks_like_stream(head, 12 + 64)


def test_a_packed_stamp_is_still_accepted():
    import struct

    from gcrip.formats import rwstream as rw

    head = struct.pack("<3I", rw.CLUMP, 64, 0x0800FFFF)
    assert rw.looks_like_stream(head, 12 + 64)


def test_a_nonsense_library_id_is_still_refused():
    import struct

    from gcrip.formats import rwstream as rw

    head = struct.pack("<3I", rw.CLUMP, 64, 0x12345678)
    assert not rw.looks_like_stream(head, 12 + 64)
