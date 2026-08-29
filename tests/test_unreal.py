"""Unreal Engine 2 packages (Ubisoft GameCube): header tables, properties, StaticMesh, Texture."""

import struct

import numpy as np

from gcrip.formats import dxt, unreal
from gcrip.plugins import unreal as plug


def cidx(v: int) -> bytes:
    """UE compact index: sign 0x80 | more 0x40 | 6 bits, then 7-bit bytes (more 0x80)."""
    neg = v < 0
    v = abs(v)
    out = [(0x80 if neg else 0) | (v & 0x3F)]
    v >>= 6
    if v:
        out[0] |= 0x40
    while v:
        out.append((v & 0x7F) | (0x80 if v >> 7 else 0))
        v >>= 7
    return bytes(out)


def make_package() -> bytes:
    """Little-endian v102/33 package: names, one texture import, a StaticMesh export and a
    DXT1 Texture export."""
    names = [
        "None",
        "Materials",
        "Material",
        "EnableCollision",
        "Core",
        "Package",
        "Engine",
        "Texture",
        "Class",
        "StaticMesh",
        "Quad",
        "Format",
        "USize",
        "VSize",
        "Tex",
        "Wood",
    ]
    ni = {n: i for i, n in enumerate(names)}
    # objects: exports 1 = Class StaticMesh? keep it simple: class references are imports
    imports = [
        ("Core", "Package", 0, "Engine"),  # -1
        ("Core", "Class", -1, "StaticMesh"),  # -2
        ("Core", "Class", -1, "Texture"),  # -3
        ("Engine", "Texture", -1, "Wood"),  # -4
    ]
    # mesh data
    props = cidx(ni["Materials"]) + bytes([0x59]) + bytes([16]) + bytes([0])
    # array: count 1, element: EnableCollision bool (0xd3, size 0), Material object -4, None
    elem = (
        cidx(ni["EnableCollision"])
        + bytes([0xD3, 0])
        + cidx(ni["Material"])
        + bytes([0x05])
        + cidx(-4)
        + cidx(0)
    )
    arr = cidx(1) + elem
    props = cidx(ni["Materials"]) + bytes([0x59, len(arr)]) + arr + cidx(0)
    bbox = struct.pack("<6f", 0, 0, 0, 1, 1, 0) + b"\x01" + struct.pack("<4f", 0.5, 0.5, 0, 1)
    verts = b"".join(
        struct.pack("<8f", x, y, 0, 0, 0, 1, x, y) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))
    )
    mesh = props + bbox + cidx(4) + verts
    mesh += struct.pack("<I", 2) + cidx(4) + struct.pack("<4H", 0, 1, 2, 3)
    mesh += struct.pack("<I", 4) + cidx(0)
    mesh += (
        struct.pack("<I", 2)
        + cidx(1)
        + struct.pack("<I", 1)
        + struct.pack("<5H", 0, 0, 3, 2, 2)
        + struct.pack("<I", 0)
        + cidx(-4)
    )
    # texture: 4x4 DXT1 (one block, solid red)
    block = struct.pack("<HHI", 0xF800, 0xF800, 0)
    tprops = (
        cidx(ni["Format"])
        + bytes([0x01])
        + bytes([3])
        + cidx(ni["USize"])
        + bytes([0x22])
        + struct.pack("<i", 4)
        + cidx(ni["VSize"])
        + bytes([0x22])
        + struct.pack("<i", 4)
        + cidx(0)
    )
    tex = (
        tprops + cidx(1) + struct.pack("<I", 0) + cidx(8) + block + struct.pack("<IIBB", 4, 4, 2, 2)
    )
    header_size = 0x24 + 16 + 4
    name_table = b"".join(
        cidx(len(n) + 1) + n.encode() + b"\0" + struct.pack("<I", 0) for n in names
    )
    o_names = header_size
    o_data = o_names + len(name_table)
    exports_data = mesh + tex
    o_imports = o_data + len(exports_data)
    import_table = b"".join(
        cidx(ni[cp]) + cidx(ni[cn]) + struct.pack("<i", pk) + cidx(ni[nm])
        for cp, cn, pk, nm in imports
    )
    o_exports = o_imports + len(import_table)
    export_table = (
        cidx(-2)
        + cidx(0)
        + struct.pack("<i", 0)
        + cidx(ni["Quad"])
        + struct.pack("<I", 0)
        + cidx(len(mesh))
        + cidx(o_data)
    )
    export_table += (
        cidx(-3)
        + cidx(0)
        + struct.pack("<i", 0)
        + cidx(ni["Tex"])
        + struct.pack("<I", 0)
        + cidx(len(tex))
        + cidx(o_data + len(mesh))
    )
    head = unreal.MAGIC_LE + struct.pack("<I", (33 << 16) | 102) + struct.pack("<I", 1)
    head += struct.pack("<6I", len(names), o_names, 2, o_exports, len(imports), o_imports)
    head += bytes(16) + struct.pack("<I", 0)
    assert len(head) == header_size
    return head + name_table + exports_data + import_table + export_table


def test_unreal_package():
    data = make_package()
    pkg = unreal.parse(data)
    assert pkg.order == "<" and pkg.version == 102 and pkg.licensee == 33
    assert [i.name for i in pkg.imports] == ["Engine", "StaticMesh", "Texture", "Wood"]
    assert [(e.class_name, e.name) for e in pkg.exports] == [
        ("StaticMesh", "Quad"),
        ("Texture", "Tex"),
    ]
    m = unreal.static_mesh(pkg, data, pkg.exports[0])
    assert m is not None and len(m.positions) == 4 and m.indices.tolist() == [0, 1, 2, 3]
    assert len(m.sections) == 1 and m.sections[0].material == -4 and m.sections[0].triangles == 2
    t = unreal.texture(pkg, data, pkg.exports[1])
    assert t is not None and (t.width, t.height, t.fmt) == (4, 4, 3)
    rgba = unreal.texture_rgba(t)
    assert rgba.shape == (4, 4, 4) and rgba[0, 0].tolist() == [255, 0, 0, 255]
    assert plug.detect("dataGCN/Staticmeshes/x.usx", data[:64], len(data))
    scenes = plug.extract(data, "dataGCN/Staticmeshes/x.usx", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2
    assert scenes[0].materials[0].name == "Wood"


def test_dxt1_decode():
    block = struct.pack("<HHI", 0x07E0, 0x001F, 0x55555555)  # green / blue, all index 1
    img = dxt.decode(block, 4, 4, "DXT1")
    assert img.shape == (4, 4, 4) and img[2, 2].tolist() == [0, 0, 255, 255]
    assert np.all(img[..., 3] == 255)


def make_level() -> bytes:
    """A map package with one StaticMeshActor (state frame + tagged properties) referencing
    ``Meshes.Quad`` from a sibling ``.usx`` (make_package)."""
    names = [
        "None",
        "Core",
        "Package",
        "Class",
        "Engine",
        "StaticMesh",
        "StaticMeshActor",
        "Meshes",
        "Quad",
        "Location",
        "Rotation",
        "DrawScale",
        "Vector",
        "Rotator",
        "Actor0",
    ]
    ni = {n: i for i, n in enumerate(names)}
    imports = [
        ("Core", "Package", 0, "Engine"),  # -1
        ("Core", "Class", -1, "StaticMeshActor"),  # -2
        ("Core", "Package", 0, "Meshes"),  # -3
        ("Engine", "StaticMesh", -3, "Quad"),  # -4
    ]
    frame = cidx(-2) + cidx(-2) + bytes([255] * 8) + struct.pack("<I", 0) + cidx(0)
    props = cidx(ni["StaticMesh"]) + bytes([0x05]) + cidx(-4)
    props += (
        cidx(ni["Location"]) + bytes([0x3A]) + cidx(ni["Vector"]) + struct.pack("<3f", 10, 20, 30)
    )
    props += (
        cidx(ni["Rotation"]) + bytes([0x3A]) + cidx(ni["Rotator"]) + struct.pack("<3i", 0, 16384, 0)
    )
    props += cidx(ni["DrawScale"]) + bytes([0x24]) + struct.pack("<f", 2.0)
    props += cidx(0)
    actor = frame + props
    header_size = 0x24 + 16 + 4
    name_table = b"".join(
        cidx(len(n) + 1) + n.encode() + bytes([0]) + struct.pack("<I", 0) for n in names
    )
    o_names = header_size
    o_data = o_names + len(name_table)
    o_imports = o_data + len(actor)
    import_table = b"".join(
        cidx(ni[cp]) + cidx(ni[cn]) + struct.pack("<i", pk) + cidx(ni[nm])
        for cp, cn, pk, nm in imports
    )
    o_exports = o_imports + len(import_table)
    export_table = (
        cidx(-2)
        + cidx(0)
        + struct.pack("<i", 0)
        + cidx(ni["Actor0"])
        + struct.pack("<I", unreal.RF_HAS_STACK | 1)
        + cidx(len(actor))
        + cidx(o_data)
    )
    head = unreal.MAGIC_LE + struct.pack("<I", (33 << 16) | 102) + struct.pack("<I", 1)
    head += struct.pack("<6I", len(names), o_names, 1, o_exports, len(imports), o_imports)
    head += bytes(16) + struct.pack("<I", 0)
    return head + name_table + actor + import_table + export_table


class _Src:
    def __init__(self, files):
        self.by_path = files

    def get(self, path):
        return self.by_path[path]


def test_level_places_static_mesh_actors():
    level = make_level()
    pkg = unreal.parse(level)
    e = pkg.exports[0]
    props = unreal.actor_props(pkg, level, e)
    assert unreal.full_name(pkg, props["StaticMesh"][2]) == "Meshes.Quad"
    assert unreal.rotator(props["Rotation"], "<") == (0, 16384, 0)
    src = _Src({"files/dataGCN/StaticMeshes/Meshes.usx": make_package()})
    plug._pkg_cache.clear()
    plug._mesh_cache.clear()
    scenes = plug.extract(level, "files/dataGCN/Maps/Test.unr", src)
    assert len(scenes) == 1 and scenes[0].extras["format"] == "unreal-level"
    s = scenes[0]
    assert s.extras["actors"] == 1 and s.extras["missing_meshes"] == 0
    pos = s.primitives[0].positions
    # scale 2, yaw 90 degrees: (1, 0, 0) -> (0, 2, 0); + (10, 20, 30); then Y-up = (x, z, y)
    assert any(np.allclose(p, (10, 30, 22), atol=1e-4) for p in pos)
    assert any(np.allclose(p, (10, 30, 20), atol=1e-4) for p in pos)
    assert s.materials[0].texture == "Meshes.Wood" or s.materials[0].texture is None
