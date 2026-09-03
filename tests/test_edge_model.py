"""Edge of Reality MODL / TXFL / SHDR members, written from The Sims 2's mapped ELF."""

from __future__ import annotations

import struct

import pytest

from gcrip.formats import edge_ind, edge_model, gx_texture
from gcrip.plugins import edge_model as plugin
from gcrip.plugins import edge_tex


def _member(tag: bytes, version: int, name: str, payload: bytes) -> bytes:
    n = name.encode() + b"\0"
    return (
        struct.pack(">I4sII", version, tag, 0xFFFFFFFF, len(n))
        + n
        + struct.pack(">I", len(payload))
        + payload
    )


def _strip_tokens(
    flags: int, verts: list[tuple[int, int, int]], version: int = 0x3A, dl: bytes | None = None
) -> bytes:
    out = bytes([0]) + struct.pack(">I", len(verts))
    out += b"".join(struct.pack(">4h", x, y, z, 0) for x, y, z in verts)
    if flags & edge_model.F_UV:
        out += b"".join(
            struct.pack(">2h", (i % 2) * 4096, (i // 2) * 4096) for i in range(len(verts))
        )
    if flags & edge_model.F_COLOR:
        out += bytes([255, 0, 0, 7]) * len(verts)
    if flags & edge_model.F_NORMAL:
        out += (
            bytes([0, 0, 64, 0]) if version > edge_model.OLD_NORMALS else bytes([0, 0, 64])
        ) * len(verts)
    if flags & edge_model.F_DL:
        assert dl is not None
        out += struct.pack(">IBII", len(verts), 3, len(dl), 3) + dl
    return out


def _model(
    name: str,
    strips: list[bytes],
    shader: int = 0x1234,
    flags: int = 0x1E,
    version: int = 0x3A,
    scale: float = 1.0 / 4096.0,
    splines: bytes = b"",
) -> bytes:
    body = bytes(4) + bytes(0x30) + bytes([0])
    body += struct.pack(">I", 0)  # attachment vertices
    body += splines or struct.pack(">I", 0)
    body += struct.pack(">II", 0, 0)  # dummies, cameras
    body += struct.pack(">I", 0)  # lights
    body += bytes([0]) + struct.pack(">fI", scale, 1)
    body += struct.pack(">II", 0xFFFFFFFF, 1)  # one submodel, one shader
    body += (
        struct.pack(">III", flags, shader, len(strips)) + bytes(len(strips)) + struct.pack(">I", 0)
    )
    body += b"".join(strips) + bytes([6])
    body += bytes(16 + 24 + 24 + 4)
    return _member(edge_model.MODEL, version, name, body)


QUAD = [(-4096, -4096, 0), (4096, -4096, 0), (-4096, 4096, 0), (4096, 4096, 0)]


def test_bare_strip_with_uvs_colours_and_normals():
    data = _model("prop_test", [_strip_tokens(0x1E, QUAD)])
    assert edge_model.is_model(data[:8]) and edge_model.header(data).name == "prop_test"
    m = edge_model.parse_model(data)
    assert m.version == 0x3A and not m.warnings and len(m.strips) == 1
    s = m.strips[0]
    assert s.shader == 0x1234 and s.indices.size == 6
    assert s.positions.min(axis=0).tolist() == [-1.0, -1.0, 0.0] and s.positions.max() == 1.0
    assert s.uvs.max() == 1.0 and s.normals[0].tolist() == [0.0, 0.0, 1.0]
    assert tuple(s.colors[0]) == (255, 0, 0, 255)


def test_display_list_strip_and_old_normals():
    # corners carry an index per attribute: position, normal, texcoord
    dl = bytes([0x9E]) + struct.pack(">H", 4)
    for i in (0, 1, 2, 3):
        dl += struct.pack(">3H", i, i, i)
    dl += bytes(-len(dl) % 32)
    data = _model(
        "wall_test", [_strip_tokens(0x3A, QUAD, version=0x39, dl=dl)], flags=0x3A, version=0x39
    )
    m = edge_model.parse_model(data)
    assert not m.warnings and m.strips[0].indices.size == 6
    assert m.strips[0].normals.shape == (4, 3) and m.strips[0].colors is None


def test_node_arrays_are_skipped_and_bad_versions_refused():
    splines = (
        struct.pack(">I", 1)
        + struct.pack(">I", 0)
        + bytes(0x80)
        + struct.pack(">IIIII", 0, 2, 2, 2, 3)
        + bytes(3 * 8 * 12)
    )
    data = _model("spline_test", [_strip_tokens(0x1E, QUAD)], splines=splines)
    assert len(edge_model.parse_model(data).strips) == 1
    with pytest.raises(edge_model.EdgeError):
        edge_model.parse_model(_member(edge_model.MODEL, 0x20, "old", bytes(64)))


def _texture_member(
    name: str,
    fmt: int,
    w: int,
    h: int,
    pixels: bytes,
    palette: bytes = b"",
    bpe: int = 0,
    flags: int = 0x80,
) -> bytes:
    entries = len(palette) * 8 // bpe if bpe else 0
    hdr = (
        struct.pack(">IIII", 0, 0, flags, 0)
        + struct.pack(">HHHH", w, h, entries, 0)
        + bytes([fmt, 0, gx_texture.BITS_PER_PIXEL[edge_model.TEX_FORMATS[fmt]], bpe])
        + bytes(4)
    )
    return _member(edge_model.TEXTURE, 9, name, hdr + pixels + palette)


def test_textures_cmpr_and_split_palette():
    px = bytearray(gx_texture.encoded_size(0xE, 8, 8))
    struct.pack_into(">HHI", px, 0, 0xF800, 0xF800, 0)
    t = edge_model.parse_texture(_texture_member("girder", 0x81, 8, 8, bytes(px)))
    assert t.width == 8 and tuple(t.rgba[0, 0]) == (255, 0, 0, 255)
    # C8 over a 32-bit palette stored as two IA8 TLUTs: (B, R) words then (A, G) words
    pal1 = b"".join(struct.pack(">BB", 30, (10 + i) & 0xFF) for i in range(256))
    pal2 = b"".join(struct.pack(">BB", 255, 20) for _ in range(256))
    idx = bytes(range(256))  # one 8x4 tile then more
    t = edge_model.parse_texture(_texture_member("shirt", 0x8A, 16, 16, idx, pal1 + pal2, bpe=32))
    assert t.rgba.shape == (16, 16, 4) and tuple(t.rgba[0, 0]) == (10, 20, 30, 255)
    assert tuple(t.rgba[0, 1]) == (11, 20, 30, 255)
    with pytest.raises(edge_model.EdgeError):
        edge_model.parse_texture(_texture_member("bad", 0x8A, 16, 16, idx))


def _shader_member(name: str, texture: int) -> bytes:
    body = bytes([1, 0]) + bytes(2) + bytes(12) + bytes(0x30) + bytes(9 * 4)
    body += struct.pack(">I", texture) + bytes(0x3C) + bytes(0x40)
    return _member(edge_model.SHADER, 0x16, name, body)


def test_plugin_binds_textures_through_shaders_by_hash():
    model = _model("prop_test", [_strip_tokens(0x1E, QUAD)], shader=0xAAAA)
    shader = _shader_member("prop_test", 0xBBBB)
    px = bytearray(gx_texture.encoded_size(0xE, 8, 8))
    struct.pack_into(">HHI", px, 0, 0x07E0, 0x07E0, 0)
    texture = _texture_member("prop_test_tex", 0x81, 8, 8, bytes(px))
    members = {
        "files/DATA/models.arc/Models/0000aaaa.bin": model,
        "files/DATA/shaders.arc/Shaders/0000aaaa.bin": shader,
        "files/DATA/textures.arc/Textures/0000bbbb.bin": texture,
    }

    class Src:
        by_path = {k: None for k in members}

        def get(self, p):
            return members[p]

    path = "files/DATA/models.arc/Models/0000aaaa.bin"
    assert plugin.detect(path, model[:64], len(model))
    (scene,) = plugin.extract(model, path, Src())
    assert scene.name == "prop_test" and scene.materials[0].texture == "prop_test_tex"
    assert tuple(scene.textures["prop_test_tex"][0, 0]) == (0, 255, 0, 255)
    (tex_scene,) = edge_tex.extract(texture, "files/DATA/textures.arc/Textures/0000bbbb.bin", None)
    assert tex_scene.extras == {"textures_only": True}


def test_index_with_the_pets_table_header():
    entries = [(0x10, 16, 100), (0x20, 116, 50)]
    table = struct.pack(">IIIII", 0, len(entries), 20 + 12 * len(entries), 0x10000, 0)
    table += b"".join(struct.pack(">I", h) for h, _, _ in entries)
    table += b"".join(struct.pack(">II", o, s) for _, o, s in entries)
    segs = [b"Models\0\0", table]
    head = 4 + 4 * (len(segs) + 1)
    offsets = [head]
    for s in segs:
        offsets.append(offsets[-1] + len(s))
    data = (
        struct.pack(">I", len(segs)) + struct.pack(f">{len(segs) + 1}I", *offsets) + b"".join(segs)
    )
    cats = edge_ind.categories(data)
    assert [(e.hash, e.offset, e.size) for e in cats["Models"]] == entries


# ------------------------------------------------------------ dataset members


def _old_model(name: str, first: bytes, strips: list[bytes], extra: bool) -> bytes:
    body = first + bytes(2) + name.encode() + bytes(1)
    if extra:
        body += bytes(16)  # Bustin' Out's version word and zeros
    body += bytes([0]) + struct.pack(">fI", 1.0 / 4096.0, 1)
    body += struct.pack(">II", 0xFFFFFFFF, 1)
    body += struct.pack(">III", 0x1A, 0x1234, len(strips)) + bytes(len(strips))
    if extra:
        body += struct.pack(">I", 0)
    body += b"".join(strips) + bytes([6]) + bytes(16 + 24 + 24 + 4) + bytes(5)
    return body


def _old_texture(name: str, fmt: int, w: int, h: int, pixels: bytes, wrapper: bytes = b"") -> bytes:
    hdr = struct.pack(">BBHHBBHIIH", fmt, 4, w, h, 0, 0, 0, 0x493, 0, 0)
    return b"LFXT" + wrapper + name.encode() + bytes(1) + hdr + pixels


def _dataset_sims(name: str, sections: list[tuple[str, list[tuple[int, bytes]]]]) -> bytes:
    out = name.encode() + bytes(1) + struct.pack(">I", len(sections))
    for sname, entries in sections:
        out += sname.encode() + bytes(1) + struct.pack(">I", len(entries))
        for h, payload in entries:
            out += struct.pack(">III", h, len(payload), 0) + payload
    return out


def test_sims_2003_dataset_models_and_textures_bind_by_hash():
    from gcrip.formats import edge_dataset
    from gcrip.plugins import edge_dataset as container

    px = bytearray(gx_texture.encoded_size(0xE, 8, 8))
    struct.pack_into(">HHI", px, 0, 0xF800, 0xF800, 0)
    strip = _strip_tokens(0x1A, QUAD, version=0)  # three-byte normals, no colours
    model = _old_model("prop_test", bytes(4), [strip], extra=False)
    data = _dataset_sims(
        "RF_TEST",
        [
            ("Textures", [(0x1234, _old_texture("prop_test", 0x81, 8, 8, bytes(px)))]),
            ("Shaders", [(0x1234, b"Prop_Test\0\x01" + bytes(20))]),
            ("Models", [(0x1234, model)]),
        ],
    )
    assert edge_dataset.style(data[:96]) == edge_dataset.SIMS
    kind, name, entries = edge_dataset.entries(data)
    assert name == "RF_TEST" and [e.category for e in entries] == ["Textures", "Shaders", "Models"]
    m = edge_model.parse_entry_model(entries[2].payload)
    assert m.name == "prop_test" and m.strips[0].indices.size == 6 and not m.warnings
    assert m.strips[0].normals.shape == (4, 3)
    t = edge_model.parse_entry_texture(entries[0].payload)
    assert t.name == "prop_test" and tuple(t.rgba[0, 0]) == (255, 0, 0, 255)

    assert container.is_container("0000abcd.bin", data[:64])
    members = dict(container.expand(data))
    assert sorted(members) == [
        "Models/00001234.eorm",
        "Shaders/00001234.eors",
        "Textures/00001234.eort",
    ]
    paths = {f"files/datasets.arc/Datasets/0000abcd.bin/{k}": v for k, v in members.items()}

    class Src:
        by_path = {k: None for k in paths}

        def get(self, p):
            return paths[p]

    mpath = "files/datasets.arc/Datasets/0000abcd.bin/Models/00001234.eorm"
    assert plugin.detect(mpath, paths[mpath][:64], len(paths[mpath]))
    (scene,) = plugin.extract(paths[mpath], mpath, Src())
    assert scene.name == "prop_test" and scene.materials[0].texture == "prop_test"


def test_bustin_out_wrapper_and_urbz_layout():
    from gcrip.formats import edge_dataset

    strip = _strip_tokens(0x1A, QUAD, version=0)
    bo = _old_model("Prop_BBQ", bytes((0, 1, 0, 0)), [strip], extra=True)
    m = edge_model.parse_entry_model(bo)
    assert m.name == "Prop_BBQ" and m.strips[0].indices.size == 6 and not m.warnings
    # The Urbz: an EDataHeader with an empty name, the name as a string, then the full model
    inner = _model("efx_burn", [_strip_tokens(0x1E, QUAD, version=0x35)], version=0x35)
    payload = edge_model.header(inner).payload
    urbz_entry = struct.pack(">IIIII", 0x35, 0, 0, 0, len(payload) + 9) + b"efx_burn\0" + payload
    m = edge_model.parse_entry_model(urbz_entry)
    assert m.name == "efx_burn" and m.version == 0x35 and m.strips[0].indices.size == 6
    data = struct.pack(">I", 9) + b"RD_test".ljust(64, b"\0") + struct.pack(">I", 1)
    data += (
        b"Models".ljust(32, b"\0") + struct.pack(">III", 0x5555, len(urbz_entry), 0) + urbz_entry
    )
    assert edge_dataset.style(data[:96]) == edge_dataset.URBZ
    kind, name, entries = edge_dataset.entries(data)
    assert name == "RD_test" and entries[0].category == "Models" and entries[0].hash == 0x5555
    # Shark Tale / Over the Hedge: twelve zero bytes and a section count byte in front
    hedge = (
        bytes(12)
        + bytes([1])
        + b"lvl\0"
        + b"Occluders\0"
        + struct.pack(">I", 1)
        + struct.pack(">III", 1, 4, 0)
        + b"OCCL"
    )
    assert edge_dataset.style(hedge[:96]) == edge_dataset.HEDGE
    assert edge_dataset.entries(hedge)[2][0].category == "Occluders"


def test_shark_tale_record_with_cp_display_lists():
    """Shark Tale / Over the Hedge: a name hash, nine words, the arrays, a CP chunk, an
    attribute table, a primitive chunk, a byte a strip and the 6."""
    pos = b"".join(struct.pack(">3h", x, y, z) for x, y, z in QUAD)  # 24 bytes, stride 6
    clr = struct.pack(">HH", 0xF800, 0x07E0)  # two RGB565 entries
    block = pos + bytes(8) + clr + bytes(4)  # colours at 0x20, block of 0x28
    chunk1 = b"".join(
        struct.pack(">BBI", 8, reg, val)
        for reg, val in ((0xA0, 0), (0xB0, 6), (0xA2, 0), (0xB2, 2))
    )
    chunk1 += bytes(-len(chunk1) % 32)
    corners = bytes([0, 0, 1, 0, 2, 1, 3, 1])  # (pos, colour) index8 pairs
    chunk2 = struct.pack(">BBI", 8, 0x50, 0x4400) + bytes([0x9A]) + struct.pack(">H", 4) + corners
    chunk2 += bytes(-len(chunk2) % 32)
    rec = struct.pack(">I", 0xCAFEBABE) + struct.pack(
        ">9I", 0x49000034, 4, 1, len(block), 0, 0, 0x20, 0, 0
    )
    rec += block + struct.pack(">I", len(chunk1)) + chunk1 + bytes([0])
    rec += (
        struct.pack(">II", len(chunk2), 4)
        + chunk2
        + bytes(1)
        + bytes([0x45])
        + bytes(8)
        + bytes([6])
    )
    body = bytes(4) + bytes(2) + b"hud01\0" + bytes([0]) + struct.pack(">fI", 0.5, 1)
    body += struct.pack(">II", 0xFFFFFFFF, 1) + rec + bytes(4) + bytes(16 + 24 + 24 + 4)
    m = edge_model.parse_entry_model(body)
    assert m.name == "hud01" and not m.warnings and len(m.strips) == 1
    s = m.strips[0]
    assert s.shader == 0xCAFEBABE and s.indices.size == 6
    assert s.positions.max() == 2048.0 and tuple(s.colors[0]) == (255, 0, 0, 255)
    assert tuple(s.colors[2]) == (0, 255, 0, 255)
