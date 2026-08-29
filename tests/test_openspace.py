"""OpenSpace (Rayman 3 GameCube) level memory images: pointer tables, super objects, geometry."""

import struct

import numpy as np

from gcrip.formats import openspace
from gcrip.plugins import openspace as plug

B = openspace.BASE


def make_level() -> tuple[bytes, bytes]:
    """A level with one world -> IPO super object whose physical object holds a one-quad
    GeometricObject (Rayman 3 GC layout); returns (lvl, ptr)."""
    lvl = bytearray(0x1400)
    ptrs: list[tuple[int, int]] = []  # (position, value) pointer fields inside lvl

    def ptr(pos: int, value: int) -> None:
        struct.pack_into(">I", lvl, pos, value - B)
        ptrs.append((pos, 1))

    # layout offsets (absolute in lvl, all >= 4)
    tex_info = 0x40  # TextureInfo (0x4a name)
    tex_table = 0x100  # 1 pointer + 1 file id
    so_world, so_ipo = 0x120, 0x160
    mat = 0x1A0  # matrices: ipo at +0, world (identity) at +0x60
    ipo, phys, vset, lods = 0x200, 0x240, 0x260, 0x280
    geo, etypes, elems, elem = 0x2A0, 0x300, 0x310, 0x320
    material = 0x400
    verts, uvs, mapv, mapu, disc = 0x500, 0x540, 0x560, 0x570, 0x580
    # texture info + table
    struct.pack_into(">HH", lvl, tex_info + 0x1C, 8, 8)
    lvl[tex_info + 0x4A : tex_info + 0x4A + 9] = b"rock.tga\0"
    ptr(tex_table, tex_info)
    struct.pack_into(">I", lvl, tex_table + 4, 2)
    # super objects: world (type 1) -> ipo (type 0x20)
    struct.pack_into(">I", lvl, so_world, 1)
    ptr(so_world + 8, so_ipo)
    ptr(so_world + 0xC, so_ipo)
    struct.pack_into(">I", lvl, so_world + 0x10, 1)
    ptr(so_world + 0x20, mat + 0x60)  # identity matrix for the world
    struct.pack_into(">I", lvl, so_ipo, 0x20)
    ptr(so_ipo + 4, ipo)
    ptr(so_ipo + 0x1C, so_world)
    ptr(so_ipo + 0x20, mat)
    m = np.eye(4, dtype=">f4")
    m[3, :3] = (10, 20, 30)
    struct.pack_into(">I", lvl, mat, 2)
    lvl[mat + 4 : mat + 4 + 64] = m.tobytes()
    struct.pack_into(">4f", lvl, mat + 68, 1, 1, 1, 1)
    struct.pack_into(">I", lvl, mat + 0x60, 1)
    lvl[mat + 0x64 : mat + 0x64 + 64] = np.eye(4, dtype=">f4").tobytes()
    struct.pack_into(">4f", lvl, mat + 0x64 + 64, 1, 1, 1, 1)
    # ipo -> physical -> visual set -> lod data -> geometric object
    ptr(ipo, phys)
    lvl[ipo + 0x2C : ipo + 0x2C + 5] = b"quad\0"
    ptr(phys, vset)
    struct.pack_into(">IHH", lvl, vset, 0, 1, 0)
    ptr(vset + 0xC, lods)
    ptr(lods, geo)
    # geometric object (Rayman 3 GC: i32 after blend weights)
    ptr(geo, verts)
    ptr(geo + 0x10, etypes)
    ptr(geo + 0x14, elems)
    struct.pack_into(">HH", lvl, geo + 0x24, 4, 1)
    struct.pack_into(">H", lvl, etypes, 1)
    ptr(elems, elem)
    # element: material, counts, uv pointer (+0x1c), OPT block at +0x34
    ptr(elem, material)
    struct.pack_into(">HHHh", lvl, elem + 4, 0, 4, 1, 0)
    ptr(elem + 0x1C, uvs)
    struct.pack_into(">BBH", lvl, elem + 0x34, 1, 0, 4)
    ptr(elem + 0x38, mapv)
    ptr(elem + 0x3C, mapu)
    struct.pack_into(">HH", lvl, elem + 0x40, 0, 2)
    ptr(elem + 0x48, disc)
    struct.pack_into(">I", lvl, material + 0x64, 1)
    ptr(material + 0x68, tex_info)
    struct.pack_into(">12f", lvl, verts, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0)
    struct.pack_into(">8f", lvl, uvs, 0, 0, 1, 0, 1, 1, 0, 1)
    struct.pack_into(">4H", lvl, mapv, 0, 1, 2, 3)
    struct.pack_into(">4H", lvl, mapu, 0, 1, 2, 3)
    struct.pack_into(">6H", lvl, disc, 0, 1, 2, 0, 2, 3)
    pt = struct.pack(">I", len(ptrs)) + b"".join(struct.pack(">2I", f, p - B) for p, f in ptrs)
    return bytes(lvl), pt


def test_openspace_level():
    lvl, pt = make_level()
    lv = openspace.Level(lvl, None, openspace.read_ptr(pt))
    infos, files = openspace.texture_table(lv)
    assert len(infos) == 1 and files == [2] and openspace.texture_name(lv, infos[0]) == "rock.tga"
    sos = openspace.super_objects(lv)
    assert sorted(r["type"] for r in sos.values()) == ["ipo", "world"]
    inst = openspace.instances(lv)
    assert len(inst) == 1 and inst[0].name == "quad" and len(inst[0].meshes) == 1
    mesh = inst[0].meshes[0]
    assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3] and mesh.tpl == (2, 0)
    np.testing.assert_allclose(mesh.uvs[2], [1, 1])
    np.testing.assert_allclose(inst[0].matrix[3, :3], [10, 20, 30])

    class Src:
        by_path = {"Levels/quad/quad.lvl": lvl, "Levels/quad/quad.ptr": pt}

        def get(self, p):
            return self.by_path[p]

    assert plug.detect("Levels/quad/quad.lvl", lvl[:64], len(lvl))
    scenes = plug.extract(lvl, "Levels/quad/quad.lvl", Src())
    assert len(scenes) == 1 and scenes[0].triangles == 2
    # world placement then Z-up -> Y-up: (x, y, z) -> (x + 10, z + 30, -(y + 20))
    np.testing.assert_allclose(scenes[0].primitives[0].positions[2], [11, 30, -21])
