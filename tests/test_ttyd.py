"""Paper Mario: TTYD map (ver1.02 packed display list) and AnimGroup actor on synthetic files."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ttyd_agb, ttyd_map
from gcrip.plugins import ttyd

MAIN = 0x20


def _tpl_rgb5a3(count: int = 1) -> bytes:
    head = struct.pack(">III", 0x0020AF30, count, 0x0C)
    table = b""
    imgs = b""
    img_base = 0x0C + 8 * count
    for i in range(count):
        hdr_off = img_base + i * 0x40
        table += struct.pack(">II", hdr_off, 0)
        data_off = hdr_off + 0x20
        imgs += struct.pack(">HHIIIIII", 4, 4, 5, data_off, 0, 0, 1, 1)
        imgs += struct.pack(">fBBBB", 0, 0, 0, 0, 0)
        imgs += struct.pack(">16H", *([0xFC00 | (i * 0x100)] * 16))
    return head + table + imgs


class _Main:
    """Main-data builder: returns offsets relative to 0x20."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def add(self, blob: bytes, align: int = 4) -> int:
        self.buf += b"\0" * ((-len(self.buf)) % align)
        off = len(self.buf)
        self.buf += blob
        return off

    def reserve(self, size: int, align: int = 4) -> int:
        return self.add(b"\0" * size, align)

    def put(self, at: int, fmt: str, *values) -> None:
        struct.pack_into(fmt, self.buf, at, *values)


def build_map() -> bytes:
    m = _Main()
    info = m.reserve(0x14)  # information chunk must come first
    ver = m.add(b"ver1.02\0")
    s_name = m.add(b"S\0")
    a_name = m.add(b"A\0")
    date = m.add(b"2004/01/01\0")
    tex_name = m.add(b"brick\0")
    mat_name = m.add(b"wall\0")
    t_mesh = m.add(b"mesh\0")
    t_null = m.add(b"null\0")
    n_root = m.add(b"world_root\0")
    n_poly = m.add(b"polySurface1\0")
    # texture table + entry + sampler
    tex_table = m.add(struct.pack(">II", 1, tex_name))
    tex_entry = m.add(struct.pack(">IBBBBHHBBBB", tex_name, 0, 0, 0, 0, 4, 4, 0, 0, 0, 0))
    sampler = m.add(struct.pack(">IIBBBB", tex_entry, 0, 1, 0, 0, 0))
    # material: 0x114 bytes
    mat = m.reserve(0x114)
    m.put(mat, ">I4BBBBB", mat_name, 255, 255, 255, 255, 1, 0, 0, 1)
    m.put(mat + 0x0C, ">I", sampler)
    m.put(mat + 0x2C, ">7f", 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0)
    mat_table = m.add(struct.pack(">III", 1, mat_name, mat))
    # vertex arrays (u32 count + data) and the vcd table
    pos = m.add(struct.pack(">I9h", 3, 0, 0, 0, 64, 0, 0, 0, 64, 0))
    nrm = m.add(struct.pack(">I3h", 1, 0, 0, 16384))
    clr = m.add(struct.pack(">I4B", 1, 255, 128, 0, 255))
    tex0 = m.add(struct.pack(">I6h", 3, 0, 0, 256, 0, 0, 256))
    vcd = m.reserve(0x54)
    m.put(vcd, ">9I", pos, nrm, 1, clr, 0, 1, tex0, 0, 0)
    m.put(vcd + 0x44, ">4I", 4, 8, 0, 0)  # pos shift 4 (64 -> 4.0), tex shift 8 (256 -> 1.0)
    # packed display list: one triangle, INDEX16 pos/nrm/clr/tex0
    dl = struct.pack(">BH", 0x90, 3) + struct.pack(">12H", 0, 0, 0, 0, 1, 0, 0, 1, 2, 0, 0, 2)
    dl_off = m.add(dl + b"\0" * ((-len(dl)) % 0x20), 0x20)
    mesh = m.add(struct.pack(">BBBBIIIII", 0, 0, 0, 1, 1, 0x17, vcd, dl_off, len(dl)))
    draw_mode = m.add(bytes([0, 1, 0, 0]) + struct.pack(">II", 0, 0))
    # scene graph: root -> A (empty), S -> polySurface(mesh part)
    root = m.reserve(0x60)
    a_node = m.reserve(0x60)
    s_node = m.reserve(0x60)
    poly = m.reserve(0x68)

    def node(off, name, typ, parent, child, sib, trans, parts):
        m.put(off, ">6I", name, typ, parent, child, sib, 0)
        m.put(off + 0x18, ">9f", 1, 1, 1, 0, 0, 0, *trans)
        m.put(off + 0x58, ">II", draw_mode, len(parts))
        for i, (pm, pme) in enumerate(parts):
            m.put(off + 0x60 + i * 8, ">II", pm, pme)

    node(root, n_root, t_null, 0, a_node, 0, (0, 0, 0), [])
    node(a_node, a_name, t_null, root, 0, s_node, (0, 0, 0), [])
    node(s_node, s_name, t_null, root, poly, 0, (0, 0, 0), [])
    node(poly, n_poly, t_mesh, s_node, 0, 0, (10, 0, 0), [(mat, mesh)])
    m.put(info, ">5I", ver, root, s_name, a_name, date)
    zero = m.add(struct.pack(">I", 0))
    fog = m.add(struct.pack(">IIffI", 0, 0, 0, 0, 0))
    m.buf += b"\0" * ((-len(m.buf)) % 0x20)
    chunks = [
        ("animation_table", zero),
        ("curve_table", zero),
        ("fog_table", fog),
        ("information", info),
        ("light_table", zero),
        ("material_name_table", mat_table),
        ("texture_table", tex_table),
        ("vcd_table", vcd),
    ]
    names = b""
    table = b""
    for name, off in chunks:
        table += struct.pack(">II", off, len(names))
        names += name.encode() + b"\0"
    body = bytes(m.buf) + table + names
    total = MAIN + len(body)
    head = struct.pack(">IIII", total, len(m.buf), 0, len(chunks)) + b"\0" * 0x10
    return head + body


def build_agb() -> bytes:
    f = bytearray(b"\0" * 0x1B0)
    f[4:11] = b"c_kuri\0"
    f[0x44:0x4B] = b"c_kuri\0"
    f[0x84:0x8C] = b"Jan 2004"
    tables: dict[str, bytes] = {}
    shape = bytearray(b"\0" * 0xA8)
    shape[:4] = b"body"
    struct.pack_into(">6I", shape, 0x40, 0, 3, 0, 0, 0, 0)
    struct.pack_into(">II", shape, 0x58, 0, 3)
    struct.pack_into(">4I", shape, 0x98, 0, 1, 1, 2)
    tables["shape"] = bytes(shape)
    tables["dc"] = struct.pack(">II", 0, 3)
    tables["vpos"] = struct.pack(">9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    tables["ipos"] = struct.pack(">3I", 0, 1, 2)
    tables["vnrm"] = b""
    tables["inrm"] = b""
    tables["vclr"] = b""
    tables["iclr"] = b""
    for t in range(8):
        tables[f"itex{t}"] = struct.pack(">3I", 0, 1, 2) if t == 0 else b""
    tables["vtex"] = struct.pack(">6f", 0, 0, 1, 0, 0, 1)
    tables["texmtx"] = struct.pack(">B3x5f", 0, 0.0, 0.0, 1.0, 1.0, 0.0)
    tables["texbase"] = struct.pack(">Ii", 0, 3)
    tex = bytearray(b"\0" * 0x40)
    struct.pack_into(">II", tex, 4, 0, 0)
    tex[0x0C:0x11] = b"skin\0"
    tables["texture"] = bytes(tex)
    draw = bytearray(b"\0" * 0x6C)
    struct.pack_into(">I", draw, 0, 1)
    struct.pack_into(">I", draw, 8, 0)
    struct.pack_into(">i", draw, 0x10, 0)
    struct.pack_into(">II", draw, 0x38, 0, 1)
    tables["draw"] = bytes(draw)
    tables["vis"] = b"\x01\x01"
    node = [1.0, 2.0, 3.0, 1.0, 1.0, 1.0] + [0.0] * 18
    node += [0.0, 0.0, 0.0, 1.0, 1.0, 1.0] + [0.0] * 18
    tables["node"] = struct.pack(">48f", *node)
    g0 = b"body".ljust(0x40, b"\0") + struct.pack(">iiiIII", -1, -1, 0, 0, 0, 0)
    g1 = b"root".ljust(0x40, b"\0") + struct.pack(">iiiIII", -1, 0, -1, 1, 24, 0)
    tables["group"] = g0 + g1
    tables["anim"] = b""
    order = [
        "shape", "dc", "vpos", "ipos", "vnrm", "inrm", "vclr", "iclr",
        *[f"itex{t}" for t in range(8)], "vtex", "texmtx", "texbase", "texture", "draw",
        "vis", "node", "group", "anim",
    ]  # fmt: skip
    counts = {
        "shape": 1, "dc": 1, "vpos": 3, "ipos": 3, "vnrm": 0, "inrm": 0, "vclr": 0, "iclr": 0,
        "itex0": 3, "vtex": 3, "texmtx": 1, "texbase": 1, "texture": 1, "draw": 1, "vis": 2,
        "node": 48, "group": 2, "anim": 0,
    }  # fmt: skip
    for i, key in enumerate(order):
        blob = tables[key]
        f += b"\0" * ((-len(f)) % 0x20)
        struct.pack_into(">I", f, 0xE8 + i * 4, counts.get(key, 0))
        struct.pack_into(">I", f, 0x14C + i * 4, len(f) if blob else 0)
        f += blob
    struct.pack_into(">I", f, 0, len(f))
    return bytes(f)


class _Src:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.by_path = files

    def get(self, path: str) -> bytes:
        return self.by_path[path]


def test_map_parse_and_scene():
    data = build_map()
    assert ttyd_map.looks_like_map(data[:64], len(data))
    assert ttyd.detect("m/gor_01/d", data[:64], len(data))
    assert not ttyd.detect("m/gor_01/t", data[:64], len(data))
    model = ttyd_map.parse(data)
    assert model.version == "ver1.02" and model.texture_names == ["brick"]
    assert [n.name for n in model.nodes] == ["world_root", "A", "S", "polySurface1"]
    assert model.nodes[2].children == [3]
    part = model.nodes[3].parts[0]
    assert np.allclose(part.mesh.positions.max(), 4.0)
    assert part.mesh.uvs[0] is not None and part.mesh.uvs[0].max() == 1.0
    assert np.allclose(part.mesh.normals[0], [0, 0, 1])
    src = _Src({"m/gor_01/t": _tpl_rgb5a3()})
    scenes = ttyd.extract(data, "m/gor_01/d", src)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene.triangles == 1
    assert scene.materials[0].texture == "brick" and scene.textures["brick"].shape == (4, 4, 4)
    assert np.allclose(scene.primitives[0].positions[:, 0].min(), 10.0)  # node translation baked
    assert scene.primitives[0].colors is not None and scene.primitives[0].colors[0, 1] < 0.6


def test_agb_parse_and_scene():
    data = build_agb()
    assert ttyd_agb.looks_like_agb(data[:64], len(data), "c_kuri")
    assert ttyd.detect("a/c_kuri", data[:64], len(data))
    assert not ttyd.detect("a/c_kuri-", data[:64], len(data))
    agb = ttyd_agb.parse(data)
    assert [g.name for g in agb.groups] == ["body", "root"]
    assert len(agb.shapes) == 1 and len(agb.shapes[0].draws) == 1
    draw = agb.shapes[0].draws[0]
    assert draw.positions.shape == (3, 3) and draw.triangles.shape == (1, 3)
    assert ttyd_agb.texture_index(agb, 0) == 0
    scenes = ttyd.extract(data, "a/c_kuri", _Src({"a/c_kuri-": _tpl_rgb5a3()}))
    assert len(scenes) == 1
    scene = scenes[0]
    assert len(scene.joints) == 2 and scene.joints[1].parent == 0
    assert np.allclose(scene.joints[1].translation, (1, 2, 3))
    prim = scene.primitives[0]
    assert np.allclose(prim.positions[0], (1, 2, 3))
    assert prim.joints is not None and prim.joints[0, 0] == 1
    assert scene.materials[0].texture == "image0" and "image0" in scene.textures
    assert not scene.materials[0].clamp_u  # wrap flags 3 = repeat both
