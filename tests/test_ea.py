"""EA formats on synthetic data: RefPack, BIG archives, shape textures, TERF/MMAP,
Need for Speed chunk streams (pack scanning, JDLZ, texture packs, geometry)."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ea_big, ea_nfs, ea_shape, ea_terf, gx_texture, refpack
from gcrip.plugins import ea

# ---------------------------------------------------------------- RefPack


def test_refpack_literal_roundtrip():
    payload = bytes(range(256)) * 3 + b"tail"
    packed = refpack.compress_literal(payload)
    assert refpack.is_refpack(packed)
    assert refpack.decompress(packed) == payload


def test_refpack_back_references():
    stream = b"\x10\xfb" + (10).to_bytes(3, "big")
    stream += b"\xe0abcd"  # 1-byte command: 4 literals
    # 2-byte command: copy ((b0 & 0x1C) >> 2) + 3 = 6 bytes from b1 + 1 = 4 back (overlapping)
    stream += b"\x0c\x03"
    stream += b"\xfc"  # stop
    assert refpack.decompress(stream) == b"abcdabcdab"


def test_refpack_rejects_garbage():
    assert not refpack.is_refpack(b"\x00\x00\x00\x00\x00")


# ---------------------------------------------------------------- BIG


def _build_big(members: dict[str, bytes], magic: bytes = b"BIGF") -> bytes:
    index = bytearray()
    entries = []
    header_len = 16 + sum(8 + len(n) + 1 for n in members)
    pos = (header_len + 15) // 16 * 16
    for _name, blob in members.items():
        entries.append((pos, len(blob)))
        pos += len(blob)
    for (off, size), name in zip(entries, members, strict=True):
        index += struct.pack(">II", off, size) + name.encode() + b"\0"
    body = b"".join(members.values())
    head = magic + struct.pack("<I", pos) + struct.pack(">II", len(members), header_len)
    out = head + bytes(index)
    out += b"\0" * ((header_len + 15) // 16 * 16 - len(out))
    return out + body


def test_big_expand_decompresses_refpack_members():
    plain = b"hello world" * 4
    packed = refpack.compress_literal(b"packed data " * 8)
    big = _build_big({"data\\a.txt": plain, "data\\b.bin": packed})
    assert ea_big.is_big(big)
    assert ea.is_container("x.big", big[:64])
    got = dict(ea.expand(big))
    assert got == {"data/a.txt": plain, "data/b.bin": b"packed data " * 8}


def test_big4_and_c0fb_variants():
    big4 = _build_big({"m.viv": b"xyz"}, magic=b"BIG4")
    assert ea_big.parse(big4)[0].name == "m.viv"
    body = b"payload!"
    entry = (32).to_bytes(3, "big") + len(body).to_bytes(3, "big") + b"f.bin\0"
    arc = b"\xc0\xfb" + struct.pack(">HH", 6 + len(entry), 1) + entry
    arc += b"\0" * (32 - len(arc)) + body
    assert ea_big.expand(arc) == [("f.bin", body)]


# ---------------------------------------------------------------- shapes


def _shape(entries: list[tuple[bytes, bytes]], magic: bytes = b"SHPI") -> bytes:
    head = magic + struct.pack("<II", 0, len(entries)) + b"G264"
    dir_size = 16 + 8 * len(entries)
    blobs = b"".join(b for _, b in entries)
    out = bytearray(head)
    pos = dir_size
    for name, blob in entries:
        out += name + struct.pack("<I", pos)
        pos += len(blob)
    out += blobs
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def _block(code: int, w: int, h: int, body: bytes, nxt: int) -> bytes:
    return bytes([code]) + nxt.to_bytes(3, "little") + struct.pack("<6H", w, h, 0, 0, 0, 0) + body


def test_shape_32bit_and_paletted():
    # 2x2 32-bit BGRA (0x7D): red, green / blue, half-alpha white
    px = bytes([0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 255, 255, 255, 128])
    e32 = _block(0x7D, 2, 2, px, 0)
    # 2x1 8-bit paletted (0x7B) followed by a 32-bit palette (0x2A) of 2 colours
    img = _block(0x7B, 2, 1, bytes([1, 0]), 16 + 2)
    pal = _block(0x2A, 2, 1, bytes([0, 0, 255, 255, 255, 0, 0, 255]), 0)
    data = _shape([(b"rgba", e32), (b"pal8", img + pal)])
    assert ea_shape.is_shape(data)
    imgs = ea_shape.parse(data)
    assert [i.name for i in imgs] == ["rgba", "pal8"]
    a = imgs[0].rgba
    assert a.shape == (2, 2, 4)
    assert tuple(a[0, 0]) == (255, 0, 0, 255)
    assert tuple(a[1, 1]) == (255, 255, 255, 128)
    b = imgs[1].rgba
    assert tuple(b[0, 0]) == (0, 0, 255, 255)  # index 1 -> BGRA ff 00 00 ff -> blue
    assert tuple(b[0, 1]) == (255, 0, 0, 255)  # index 0 -> BGRA 00 00 ff ff -> red


def test_shape_refpack_compressed_body_and_plugin():
    px = bytes([10, 20, 30, 255] * 4)
    body = refpack.compress_literal(px)
    data = _shape([(b"comp", _block(0x7D | 0x80, 2, 2, body, 0))])
    assert ea.detect("tex.fsh", data[:64], len(data))
    scenes = ea.extract(data, "art/tex.fsh", None)
    assert len(scenes) == 1 and scenes[0].extras["textures_only"]
    rgba = scenes[0].textures["comp"]
    assert tuple(rgba[1, 1]) == (30, 20, 10, 255)
    assert scenes[0].materials[0].texture == "comp"


def test_shape_dxt1():
    # one DXT1 block: c0 = pure red (0xF800), c1 = black, all indices 0 -> red
    block = struct.pack("<HH", 0xF800, 0x0000) + b"\0\0\0\0"
    rgba = ea_shape.decode_dxt(block, 4, 4)
    assert rgba.shape == (4, 4, 4)
    assert tuple(rgba[3, 3]) == (255, 0, 0, 255)


# ---------------------------------------------------------------- TERF / MMAP


def _mmap_c8(w: int, h: int) -> bytes:
    """A C8 MMAP whose palette is two RGB5A3 colours and whose pixels alternate 0/1."""
    tiles = gx_texture.encoded_size(9, w, h)
    hdr_size = 0x28
    level_off = hdr_size + 16
    pal_block = level_off + tiles
    pal_entries = pal_block + 16
    total = pal_entries + 256 * 2
    out = bytearray(b"MMAP" + struct.pack(">HH", 2, 0) + bytes([0, 1, 2, 3]))
    out += struct.pack(">HHHH", 1, 1, 1, 0)
    out += struct.pack(">IIIII", total, hdr_size, pal_block, 0, 0)
    out += struct.pack(">HHHHII", w, h, 9, 0, tiles, level_off)
    out += bytes((i % 2) for i in range(tiles))
    out += struct.pack(">HHIII", 1, 2, 256 * 2, pal_entries, 0)
    pal = bytearray(256 * 2)
    struct.pack_into(">H", pal, 0, 0x801F)  # RGB555 opaque blue
    struct.pack_into(">H", pal, 2, 0xFC00)  # RGB555 opaque red
    out += pal
    return bytes(out)


def _terf(members: list[bytes], align: int = 64) -> bytes:
    def pad(b: bytes) -> bytes:
        return b + b"\0" * (-len(b) % align)

    dir_body = bytearray()
    data = bytearray(b"DATA" + b"\0\0\0\0")
    data += b"\0" * (-len(data) % align)
    for m in members:
        dir_body += struct.pack(">II", len(data), len(m))
        data += m
        data += b"\0" * (-len(data) % align)
    struct.pack_into(">I", data, 4, len(data))
    dir1 = pad(b"DIR1" + struct.pack(">I", 8 + len(dir_body)) + dir_body)
    comp = pad(b"COMP" + struct.pack(">I", 8 + 8 * len(members)) + b"\0" * (8 * len(members)))
    head = b"TERF" + struct.pack(">I", align) + bytes([2, 2, 1, 6])
    head += struct.pack(">HH", align, len(members))
    head += b"\0" * (align - len(head))
    return head + dir1 + comp + bytes(data)


def test_terf_expand_and_mmap_decode():
    tex = _mmap_c8(8, 4)
    arc = _terf([tex, b"<Text>hello</Text>", b"\x01\x02\x03\x04"])
    assert ea.is_container("X.DAT", arc[:64])
    members = ea.expand(arc)
    assert [n for n, _ in members] == ["0000.mmap", "0001.txt", "0002.bin"]
    assert members[0][1] == tex
    assert ea.detect("X.DAT/0000.mmap", tex[:64], len(tex))
    (scene,) = ea.extract(tex, "X.DAT/0000.mmap", None)
    rgba = scene.textures["0000"]
    assert rgba.shape == (4, 8, 4)
    assert tuple(rgba[0, 0]) == (0, 0, 255, 255)
    assert tuple(rgba[0, 1]) == (255, 0, 0, 255)


def test_terf_nested_in_plugin_listing():
    inner = _terf([b"\x01\x02\x03\x04"])
    outer = _terf([inner])
    members = ea.expand(outer)
    assert members[0][0] == "0000.terf"
    assert ea_terf.parse(members[0][1]).members[0].size == 4


# ---------------------------------------------------------------- Need for Speed


def _chunk(cid: int, body: bytes) -> bytes:
    return struct.pack("<II", cid, len(body)) + body


def _jdlz_literal(data: bytes) -> bytes:
    """JDLZ stream of literals only: a match-kind flag byte, then per 8 bytes a zero
    literal flag byte followed by the bytes."""
    out = bytearray(b"JDLZ" + bytes([2, 0x10, 0, 0]) + struct.pack("<II", len(data), 0))
    out += b"\0"
    for i in range(0, len(data), 8):
        out += b"\0" + data[i : i + 8]
    struct.pack_into("<I", out, 12, len(out))
    return bytes(out)


def _tpk(name: str, textures: dict[int, bytes], file_base: int) -> bytes:
    """A texture pack whose data offsets are absolute in a file where the pack starts
    at `file_base`."""
    info_name = struct.pack("<I", 5) + name.encode().ljust(0x1C, b"\0")
    info_name += b"Global\\Test.tpk".ljust(0x40, b"\0") + b"\0" * 0x1C
    hashes = b"".join(struct.pack("<II", h, 0) for h in textures)
    records = bytearray()
    data = bytearray()
    info_len = 8 + len(info_name) + 8 + len(hashes) + 8 + 24 * len(textures)
    # root header, info header, info, data header, 0x33320001 chunk, data chunk header, fill
    data_start = file_base + 8 + 8 + info_len + 8 + (8 + 24) + 8 + 8
    for h, blob in textures.items():
        records += struct.pack("<IIIIII", h, data_start + len(data), len(blob), 0, 0x100, 0)
        data += blob
    info = _chunk(0x33310001, info_name) + _chunk(0x33310002, hashes)
    info += _chunk(0x33310003, bytes(records))
    dhead = _chunk(0x33320001, b"\0" * 24)
    dbody = _chunk(0x33320002, b"\x11" * 8 + bytes(data))
    root = _chunk(0xB3310000, info) + _chunk(0xB3320000, dhead + dbody)
    return _chunk(0xB3300000, root)


def _texture_blob(name: str, fmt: int, w: int, h: int, tiles: bytes, palette: bytes = b"") -> bytes:
    trailer = bytearray(0xB8)
    trailer[0x0C : 0x0C + len(name)] = name.encode()
    struct.pack_into("<II", trailer, 0x38, len(tiles), len(palette))
    struct.pack_into("<HH", trailer, 0x44, w, h)
    struct.pack_into(">I", trailer, 0xB4, fmt)
    return _jdlz_literal(tiles + palette + bytes(trailer))


def _geometry(tex_hash: int) -> bytes:
    """One part: a quad as a 4-vertex strip (8-bit indices, attribute set 0x16)."""
    hdr = bytearray(192)
    struct.pack_into("<I", hdr, 0x10, 0x1234)
    struct.pack_into("<HH", hdr, 0x14, 2, 4)
    struct.pack_into("<3f", hdr, 0x20, 0, 0, 0)
    struct.pack_into("<3f", hdr, 0x30, 1, 1, 0)
    struct.pack_into("<16f", hdr, 0x40, *np.eye(4, dtype=np.float32).flatten())
    hdr[0xA4 : 0xA4 + 6] = b"QUAD_A"
    textures = struct.pack("<II", tex_hash, 0)
    # strip: 4 vertices, 4 bytes each (pos, nrm, aux, uv)
    strip = bytes([0, 0, 0, 0, 1, 1, 0, 1, 2, 2, 0, 2, 3, 3, 0, 3])
    strip += b"\0" * (-len(strip) % 16)
    pos = struct.pack(">12h", 0, 0, 0, 4096, 0, 0, 0, 4096, 0, 4096, 4096, 0)
    nrm = struct.pack(">16b", *([0, 0, 64, 0] * 4))
    clr = b"\xff\xff\xff\xff"
    uv = struct.pack(">8h", 0, 0, 4096, 0, 0, 4096, 4096, 4096)
    body = strip + pos + clr + uv + nrm
    body += b"\0" * (-len(body) % 16)  # keep every chunk 8-byte aligned, as the game does
    pos_off = len(strip)
    clr_off = pos_off + len(pos)
    uv_off = clr_off + len(clr)
    nrm_off = uv_off + len(uv)
    m800 = struct.pack(">IHHIIIIII", 0, 1, 4, len(body), pos_off, nrm_off, clr_off, uv_off, 0)
    m801 = struct.pack(">IHHBBBBHH", 0, 16, 0x4180, 4, 0, 0, 0, 0x0016, 16)
    mesh = _chunk(0x00134800, m800) + _chunk(0x00134801, m801) + _chunk(0x00134802, body)
    part = _chunk(0x00134011, bytes(hdr)) + _chunk(0x00134012, textures)
    part += _chunk(0x80134100, mesh)
    info_hdr = bytearray(0x90)
    info_hdr[0x10:0x48] = b"..\\GAMECUBE\\CDUG2\\CARS\\TST\\GEOMETRY.BIN".ljust(0x38, b"\0")
    info = _chunk(0x80134001, _chunk(0x00134002, bytes(info_hdr)))
    return _chunk(0x80134000, info + _chunk(0x80134010, part))


def test_jdlz_literals():
    data = b"0123456789abcdefXYZ"
    assert ea_nfs.jdlz_decompress(_jdlz_literal(data)) == data


def test_nfs_pack_scan_geometry_and_textures():
    # 8x8 CMPR: every DXT block c0 = blue, c1 = white, all texels pick c0
    tiles = bytes([0x00, 0x1F, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00]) * 4
    tex = _texture_blob("QUADTEX", 14, 8, 8, tiles)
    geo = _geometry(0xABCD0001)
    geo += b"\0" * (-len(geo) % 0x800)
    tpk = _tpk("TEST", {0xABCD0001: tex}, len(geo))
    pack = geo + tpk + b"\0" * (-len(tpk) % 0x800) + b"\xde\xad\xbe\xef" * 512
    assert ea.is_container("ZZDATA0.BIN", pack[:64])
    members = ea.expand(pack)
    assert [n for n, _ in members] == ["CARS/TST/GEOMETRY.BIN", "Global/Test.tpk"]
    gdata = members[0][1]
    assert ea.detect("ZZDATA0.BIN/CARS/TST/GEOMETRY.BIN", gdata[:64], len(gdata))
    geos = ea_nfs.parse_geometry(gdata)
    assert len(geos) == 1 and geos[0].parts[0].name == "QUAD_A"
    (part,) = geos[0].parts
    assert len(part.strips) == 1 and len(part.strips[0].verts) == 4
    assert part.positions.shape == (4, 3) and part.positions[3].tolist() == [1.0, 1.0, 0.0]

    class Src:
        by_path = {}

        def get(self, path):
            raise KeyError(path)

    # textures resolve through a pack in the same file (pack offsets are file-absolute)
    scenes = ea.extract(geo + tpk, "ZZDATA0.BIN/CARS/TST/GEOMETRY.BIN", Src())
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.triangles == 2 and sc.vertices == 4
    assert sc.materials[0].texture == "QUADTEX"
    assert sc.textures["QUADTEX"].shape == (8, 8, 4)
    assert tuple(sc.textures["QUADTEX"][0, 0]) == (0, 0, 255, 255)
    assert [j.name for j in sc.joints] == ["root", "QUAD_A"]
    # a texture pack on its own becomes a textures-only scene
    alone = _tpk("TEST", {0xABCD0001: tex}, 0)
    (tscene,) = ea.extract(alone, "ZZDATA0.BIN/Global/Test.tpk", None)
    assert tscene.extras["textures_only"] and "QUADTEX" in tscene.textures
    # offsets written for the pack's own start still resolve after a merge behind other data
    merged = b"\0" * 0x800 + alone
    scenes = ea.extract(geo + merged, "ZZDATA0.BIN/CARS/TST/GEOMETRY.BIN", Src())
    assert scenes[0].materials[0].texture == "QUADTEX"


def test_strip_triangles_restart_parity():
    v = [{"pos": i, "uv": 0} for i in (0, 1, 2, 2, 3, 3, 4, 5)]
    tris = ea_nfs._strip_triangles(v)
    pos = [tuple(x["pos"] for x in t) for t in tris]
    assert pos == [(0, 1, 2), (3, 4, 5)]


def test_pack_scan_ignores_non_stream_sectors():
    junk = bytes(range(256)) * 8
    geo = _geometry(1)
    pack = junk + geo + b"\0" * (-len(geo) % 0x800) + junk
    members = ea.expand(pack)
    assert [n for n, _ in members] == ["CARS/TST/GEOMETRY.BIN"]
    assert members[0][1] == geo
