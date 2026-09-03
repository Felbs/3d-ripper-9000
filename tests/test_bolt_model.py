"""Mass Media BOLT model members (the LoadNode tree and MESH::Load stream) and material lists,
written from the Muppets Party Cruise ELF."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from gcrip.formats import bolt_model, gx_texture
from gcrip.plugins import bolt as container
from gcrip.plugins import bolt_mat
from gcrip.plugins import bolt_model as plugin
from tests.test_bolt import _archive


def _name16(s: str) -> bytes:
    return s.encode().ljust(16, b"\0")


def _matrix(tx: float = 0.0, ty: float = 0.0, tz: float = 0.0, scale: float = 1.0) -> bytes:
    m = np.eye(4) * scale
    m[3] = [tx, ty, tz, 1.0]
    return m.astype(">f4").tobytes()


def _mesh(
    material: int = 0,
    vt: int = 0x18,
    f32: bool = False,
    normals: bool = False,
    npos: int = 4,
    dl: bytes | None = None,
    vsize: int | None = None,
) -> bytes:
    """A quad as a strip.  ``vt`` 0x18: s16 positions, s16 UVs, direct RGB565 colours."""
    pos_frac, tex_frac, nrm_frac = 4, 8, 6
    quad = [(-1, -1, 0), (1, -1, 0), (-1, 1, 0), (1, 1, 0)]
    pts = [quad[i % 4] for i in range(npos)]
    if f32:
        vt |= 1
        pos = b"".join(struct.pack(">3f", *p) for p in pts)
    else:
        pos = b"".join(struct.pack(">3h", *(c << pos_frac for c in p)) for p in pts)
    if normals:
        vt |= 2
        nrm = bytes([0, 0, 1 << nrm_frac]) * 4
        nnrm = 4
    else:
        nrm = b""
        nnrm = 0
    uv = b"".join(
        struct.pack(">2h", u << tex_frac, v << tex_frac)
        for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))
    )
    idx_w = 2 if npos > 256 else 1
    if dl is None:
        dl = bytes([0x9A]) + struct.pack(">H", 4)
        for i in range(4):
            dl += i.to_bytes(idx_w, "big")
            if normals:
                dl += bytes([i])
            dl += struct.pack(">H", 0xF800 if i == 0 else 0x07E0)  # red then green
            dl += bytes([i])
    width = idx_w + (1 if normals else 0) + 2 + 1
    out = struct.pack(">HH", 2, material)
    out += struct.pack(">H", 5) + b"quad\0"
    out += struct.pack(">HH", 0, vt)
    out += bytes([vsize if vsize is not None else width, pos_frac, nrm_frac, tex_frac])
    out += struct.pack(">H", npos) + pos
    out += struct.pack(">H", nnrm) + nrm
    out += struct.pack(">H", 0)  # no colour array: colours are direct
    out += struct.pack(">H", 4) + uv
    out += struct.pack(">I", len(dl)) + dl
    out += bytes([0])  # not skinned
    return out


def _node(kind: int, body: bytes = b"", children: list[bytes] = ()) -> bytes:
    return bytes([kind]) + body + struct.pack(">H", len(children)) + b"".join(children)


def _model(root_children: list[bytes], group: str = "Data_Test_GCN") -> bytes:
    return (
        bolt_model.TAG
        + bytes([len(group)])
        + group.encode()
        + _node(bolt_model.ANIMCONTROL, struct.pack(">H", 0) + _name16("B00_Tile"), root_children)
    )


def _object(name: str, matrix: bytes, children: list[bytes]) -> bytes:
    return _node(bolt_model.OBJECT, _name16(name) + bytes(4) + matrix + bytes(12), children)


def _texture(w: int = 8, h: int = 8) -> bytes:
    """A CMPR texture whose first block is solid red."""
    pixels = bytearray(gx_texture.encoded_size(0xE, w, h))
    struct.pack_into(">HHI", pixels, 0, 0xF800, 0xF800, 0)
    return struct.pack(">HHBBBI", w, h, 0, 5, 1, len(pixels)) + bytes(pixels)


def _material_list(names: list[str], textures: list[bytes], refs: list[int | None]) -> bytes:
    pool = b"Data_Test_GCN\0" + b"".join(n.encode() + b"\0" for n in names)
    body = struct.pack(">HHH", len(refs), len(refs), len(textures))
    body += b"".join(textures)
    for ref in refs:
        body += bytes([0, 1, 6]) + struct.pack(">3f", 0.9, 0.9, 0.9) + struct.pack(">II", 0, 0)
        if ref is None:
            body += struct.pack(">H", 0) + struct.pack(">4f", 0.25, 0.5, 0.75, 1.0)
        else:
            body += struct.pack(">HH", 1, ref)
    return bolt_model.TAG + struct.pack(">I", len(pool)) + pool + struct.pack(">I", 0) + body


def test_tree_meshes_and_object_matrices():
    inner = _object(
        "lever01",
        _matrix(0, 0, 5),
        [
            _node(bolt_model.BBOX, bytes(0x18 + 12 + 4)),
            _node(bolt_model.MESH, _mesh(material=1, normals=True)),
        ],
    )
    anim = _node(
        bolt_model.ANIM,
        _name16("gear01")
        + _matrix(2, 0, 0)
        + bytes(12)
        + struct.pack(">H", 1)
        + bytes(3)
        + bytes([0])
        + struct.pack(">H", 2)
        + bytes(64),
        [inner],
    )
    wall = _object(
        "B00_WALL01", _matrix(0, 15, 32), [_node(bolt_model.MESH, _mesh(material=0, f32=True))]
    )
    data = _model([wall, anim, _node(bolt_model.SKIN, bytes(1)), _node(bolt_model.LOD)])
    assert bolt_model.is_model(data[:64]) and not bolt_model.is_material_list(data[:64])
    model = bolt_model.parse(data)
    assert model.group == "Data_Test_GCN" and model.name == "B00_Tile" and not model.warnings
    assert [m.node for m in model.meshes] == ["B00_WALL01", "lever01"]
    wall_mesh, lever = model.meshes
    assert wall_mesh.material == 0 and lever.material == 1 and wall_mesh.indices.size == 6
    assert wall_mesh.positions.min(axis=0).tolist() == [-1.0, -1.0, 0.0]
    assert tuple(wall_mesh.colors[0]) == (255, 0, 0, 255) and tuple(wall_mesh.colors[1]) == (
        0,
        255,
        0,
        255,
    )
    assert wall_mesh.uvs.max() == 1.0 and wall_mesh.normals is None
    pos, nrm = bolt_model.transform(wall_mesh)
    assert pos[0].tolist() == [-1.0, 14.0, 32.0]
    # lever sits in gear01 (x + 2) which sits in the tile: translations compose
    pos, nrm = bolt_model.transform(lever)
    assert pos[0].tolist() == [1.0, -1.0, 5.0] and nrm[0].tolist() == [0.0, 0.0, 1.0]


def test_index_width_follows_the_declared_vertex_size():
    # 300 positions: the display list carries u16 position indices
    m = bolt_model.parse(
        _model([_object("big", _matrix(), [_node(bolt_model.MESH, _mesh(npos=300))])])
    )
    assert len(m.meshes) == 1 and m.meshes[0].positions.shape == (4, 3)
    # a vertexSize the layout cannot produce skips the mesh with a warning instead of misreading it
    m = bolt_model.parse(
        _model([_object("bad", _matrix(), [_node(bolt_model.MESH, _mesh(vsize=9))])])
    )
    assert not m.meshes and "vertexSize" in m.warnings[0]


def test_unknown_node_type_and_short_member_raise():
    with pytest.raises(bolt_model.BoltModelError):
        bolt_model.parse(_model([_node(9)]))
    with pytest.raises(bolt_model.BoltModelError):
        bolt_model.parse(
            _model([_object("cut", _matrix(), [_node(bolt_model.MESH, _mesh()[:30])])])
        )


def test_material_list_textures_and_colours():
    data = _material_list(["Map #1", "WALL", "FLAT"], [_texture()], [0, None])
    assert bolt_model.is_material_list(data[:64])
    ml = bolt_model.parse_material_list(data)
    assert ml.name == "Data_Test_GCN" and [t.name for t in ml.textures] == ["Map #1"]
    assert [m.name for m in ml.materials] == ["WALL", "FLAT"]
    assert ml.materials[0].texture == 0 and ml.materials[1].texture is None
    assert ml.materials[1].color == (0.25, 0.5, 0.75, 1.0)
    rgba = ml.textures[0].decode()
    assert rgba.shape == (8, 8, 4) and tuple(rgba[0, 0]) == (255, 0, 0, 255)


def test_container_names_members_and_plugins_bind_materials():
    matlist = _material_list(["Map #1", "WALL", "FLAT"], [_texture()], [0, None])
    model = _model(
        [
            _object(
                "B00_WALL01",
                _matrix(),
                [
                    _node(bolt_model.MESH, _mesh(material=0)),
                    _node(bolt_model.MESH, _mesh(material=1)),
                ],
            )
        ]
    )
    arc = _archive([(0x0B, matlist, None), (0x0B, model, None), (0x03, b"raw!", None)])
    members = container.expand(arc)
    assert [n for n, _ in members] == ["g00_0000_t0b.bmat", "g00_0001_t0b.bmdl", "g00_0002_t03.bin"]

    class Src:
        by_path = {f"boards/B.BLT/{n}": None for n, _ in members}

        def get(self, p):
            return dict(members)[p.split("/", 2)[2]]

    src = Src()
    path = "boards/B.BLT/g00_0001_t0b.bmdl"
    assert plugin.detect(path, model[:64], len(model))
    (scene,) = plugin.extract(model, path, src)
    assert scene.name == "g00_0001_t0b_B00_Tile" and len(scene.primitives) == 2
    assert [m.name for m in scene.materials] == ["WALL", "FLAT"]
    assert scene.materials[0].texture == "tex000_Map_1" and "tex000_Map_1" in scene.textures
    assert scene.materials[1].texture is None and scene.materials[1].base_color == (
        0.25,
        0.5,
        0.75,
        1.0,
    )
    (tex_scene,) = bolt_mat.extract(matlist, "boards/B.BLT/g00_0000_t0b.bmat", src)
    assert tex_scene.extras == {"textures_only": True} and list(tex_scene.textures) == [
        "tex000_Map_1"
    ]


# ------------------------------------------------------------ the other generations

TAG_13 = bytes((1, 3, 0, 0x0A))  # Pac-Man Fever
TAG_1918 = bytes((1, 9, 0, 0x12))  # Shrek Super Party


def _mesh_13(material: int = 0, wide: bool = False) -> bytes:
    """A 2002 quad: float arrays, RGBA8 colours, UVs, one strip; ``wide`` widens the indices."""
    vt = 0x0C | (1 if wide else 0)
    quad = [(-1, -1, 0), (1, -1, 0), (-1, 1, 0), (1, 1, 0)]
    out = struct.pack(">HHH", 2, material, 4) + b"quad" + struct.pack(">HH", vt, 4)
    out += b"".join(struct.pack(">3f", *p) for p in quad)
    out += struct.pack(">H", 0)
    out += struct.pack(">H", 4) + bytes([255, 0, 0, 255]) * 4
    out += struct.pack(">H", 4) + b"".join(
        struct.pack(">2f", u, v) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))
    )
    w = 2 if wide else 1
    dl = bytes([0x98]) + struct.pack(">H", 4)
    for i in range(4):
        dl += i.to_bytes(w, "big") * 3
    dl += bytes(-len(dl) % 32)
    return out + struct.pack(">I", len(dl)) + dl + bytes([0])


def _model_13(nodes: bytes, group: str = "distill_test") -> bytes:
    return TAG_13 + bytes([len(group)]) + group.encode() + nodes


def _material_list_13(
    textures: list[tuple[str, bytes]], materials: list[tuple[str, list[int]]]
) -> bytes:
    out = TAG_13 + bytes([12]) + b"distill_test" + struct.pack(">H", len(textures))
    for name, body in textures:
        out += struct.pack(">H", len(name)) + name.encode() + body
    out += struct.pack(">H", len(materials))
    for name, refs in materials:
        out += struct.pack(">H", len(name)) + name.encode() + struct.pack(">H", len(refs))
        out += b"".join(struct.pack(">H", r) for r in refs)
    return out


def test_2002_tree_uses_child_and_sibling_flags():
    # root object -> child bbox; the bbox's sibling is a mesh; the root's sibling is a second
    # object with a wide-index mesh and a light hanging off it
    mesh = bytes([bolt_model.MESH]) + _mesh_13(material=0) + bytes([0, 0])
    bbox = bytes([bolt_model.BBOX]) + bytes(0x28) + bytes([0, 1]) + mesh
    light = bytes([bolt_model.LIGHT]) + bytes(16) + bytes([0])
    mesh2 = (
        bytes([bolt_model.MESH]) + _mesh_13(material=1, wide=True) + bytes([1]) + light + bytes([0])
    )
    second = (
        bytes([bolt_model.OBJECT])
        + _name16("Prop")
        + bytes([0])
        + _matrix(10, 0, 0)
        + bytes(12)
        + bytes([1])
        + mesh2
        + bytes([0])
    )
    root = (
        bytes([bolt_model.OBJECT])
        + _name16("Plane01")
        + bytes([0])
        + _matrix()
        + bytes(12)
        + bytes([1])
        + bbox
        + bytes([1])
        + second
    )
    data = _model_13(root)
    assert bolt_model.is_model(data[:64]) and not bolt_model.is_material_list(data[:64])
    m = bolt_model.parse(data)
    assert m.version == (1, 3, 10) and m.name == "Plane01" and not m.warnings
    assert [(x.node, x.material) for x in m.meshes] == [("Plane01", 0), ("Prop", 1)]
    first, second_mesh = m.meshes
    assert first.indices.size == 6 and tuple(first.colors[0]) == (255, 0, 0, 255)
    assert first.uvs.max() == 1.0 and first.normals is None
    pos, _ = bolt_model.transform(second_mesh)
    assert pos[:, 0].min() == 9.0 and pos[:, 0].max() == 11.0
    assert [t for _, t, _ in m.nodes].count(bolt_model.LIGHT) == 1


def test_2002_material_list_inline_strings_and_mip_chains():
    cmpr = bytearray(gx_texture.encoded_size(0xE, 8, 8) + gx_texture.encoded_size(0xE, 4, 4))
    struct.pack_into(">HHI", cmpr, 0, 0xF800, 0xF800, 0)
    tex = struct.pack(">HHBBB", 8, 8, 0, 5, 2) + bytes(cmpr)
    c8 = (
        struct.pack(">HHBBBB", 8, 4, 0, 3, 0xFF, 1)
        + bytes(32)
        + struct.pack(">H", 0x200)
        + bytes(0x200)
    )
    data = _material_list_13(
        [("(wall.bmp)", tex), ("(floor.bmp)", c8)], [("WALL", [0]), ("No Material", [])]
    )
    assert bolt_model.is_material_list(data[:64]) and not bolt_model.is_model(data[:64])
    ml = bolt_model.parse_material_list(data)
    assert ml.name == "distill_test" and [t.name for t in ml.textures] == [
        "(wall.bmp)",
        "(floor.bmp)",
    ]
    assert ml.textures[0].mips == 2 and ml.textures[1].palette is not None
    assert ml.materials[0].texture == 0 and ml.materials[1].texture is None
    assert tuple(ml.textures[0].decode()[0, 0]) == (255, 0, 0, 255)
    assert ml.textures[1].decode().shape == (4, 8, 4)


def test_shrek_material_list_has_no_layer_records():
    pool = b"distill_BNTO\0Map #2\0Material #36\0FLAT\0"
    body = struct.pack(">H", 1) + _texture()
    body += struct.pack(">H", 2)
    body += (
        bytes([6])
        + struct.pack(">4f", 1, 1, 1, 1)
        + struct.pack(">4f", 0.9, 0.9, 0.9, 0)
        + struct.pack(">II", 0, 0)
    )
    body += struct.pack(">HHH", 1, 0, 0)
    body += (
        bytes([6])
        + struct.pack(">4f", 0.25, 0.5, 0.75, 1.0)
        + struct.pack(">4f", 0.9, 0.9, 0.9, 0)
        + struct.pack(">II", 0, 0)
    )
    body += struct.pack(">HH", 0, 0)
    data = TAG_1918 + struct.pack(">I", len(pool)) + pool + struct.pack(">I", 0) + body
    ml = bolt_model.parse_material_list(data)
    assert [m.name for m in ml.materials] == ["Material #36", "FLAT"]
    assert ml.materials[0].texture == 0 and ml.materials[1].texture is None
    assert ml.materials[1].color == (0.25, 0.5, 0.75, 1.0)
