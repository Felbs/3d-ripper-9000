"""res `bmsh` character meshes - Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2."""

import struct

import numpy as np

from gcrip.formats import res, res_bmsh
from gcrip.plugins import res as plugin
from tests.test_res import build_linked

SCALE = 1.0 / 4096.0


def _pad(n):
    return -(-n // res_bmsh.ALIGN) * res_bmsh.ALIGN


def build(sub_batches=1, blended=True, shader_back=0x200):
    """A section with the real shape: ``sub_batches`` 0x28-byte records then the main
    record with a bone list, every table followed by its vertex buffer, blend runs stored
    after it, slot / weight lists after the blend table, uvs and one 0x99 strip."""
    meshes = []
    for k in range(sub_batches + 1):
        # a quad (4 vertices) plus, for the main mesh, a blended fifth vertex
        pts = [(0, 0, 0), (4096, 0, 0), (4096, 0, 4096), (0, 0, 4096)]
        blend_rows = 1 if (blended and k == sub_batches) else 0
        if blend_rows:
            pts.append((0, 0, 0))  # the buffer holds garbage where a blended slot sits
        table = bytearray(res_bmsh.TABLE)
        buffer = b"".join(struct.pack(">6h", x, y, z, 0, -1024, 0) for x, y, z in pts)
        buffer += bytes(_pad(len(buffer)) - len(buffer))
        rigid = struct.pack(">IIiI", 0, len(pts) - blend_rows, 0, 0)  # run ptr patched below
        rigid += bytes(_pad(len(rigid)) - len(rigid))
        blend = b""
        lists = b""
        run = b""
        if blend_rows:
            blend = struct.pack(">IIiII", 1, 1, 0, 0, 0)  # ptr patched below
            blend += bytes(_pad(len(blend)) - len(blend))
            lists = struct.pack(">H", 4) + bytes(30) + bytes([255]) + bytes(31)
            run = struct.pack(">6h", 2048, 0, 8192, 0, -1024, 0) + bytes(20)
        strip_corners = [0, 1, 3, 2] if not blend_rows else [0, 1, 3, 2, 2, 4, 4, 3, 1]
        dl = bytes(1) + struct.pack(">BH", res_bmsh.STRIP, len(strip_corners))
        for c in strip_corners:
            dl += struct.pack(">4H", c, c, c, c)
        dl += bytes(_pad(len(dl)) - len(dl))
        uvs = b"".join(struct.pack(">ffII", i / 8, 1 - i / 8, 0, 0) for i in range(len(pts)))
        uvs += bytes(_pad(len(uvs)) - len(uvs))
        bounds = bytes(32)
        # layout after the table: buffer, run, rigid, blend, lists, bounds, uvs, dl
        parts = [("buffer", buffer), ("run", run), ("rigid", rigid), ("blend", blend)]
        parts += [("lists", lists), ("bounds", bounds), ("uvs", uvs), ("dl", dl)]
        at = {}
        off = res_bmsh.TABLE
        for name, blob in parts:
            at[name] = off
            off += len(blob)
        body = bytearray(b"".join(blob for _, blob in parts))
        rigid_ptr = at["rigid"] - res_bmsh.TABLE + 8
        struct.pack_into(">i", body, rigid_ptr, at["buffer"] - (at["rigid"] + 8))
        if blend_rows:
            blend_ptr = at["blend"] - res_bmsh.TABLE + 8
            struct.pack_into(">i", body, blend_ptr, at["run"] - (at["blend"] + 8))
        struct.pack_into(">Ii", table, 0, 1, at["rigid"] - 4)
        struct.pack_into(">Ii", table, 8, 0, 1)
        struct.pack_into(">Ii", table, 0x10, blend_rows, (at["blend"] - 0x14) if blend_rows else 1)
        struct.pack_into(">i", table, 0x18, at["bounds"] - 0x18)
        struct.pack_into(">I", table, 0x1C, 36)
        struct.pack_into(">i", table, 0x20, at["uvs"] - 0x20)
        struct.pack_into(">I", table, 0x24, len(pts))
        struct.pack_into(">I", table, 0x28, len(dl))
        struct.pack_into(">i", table, 0x2C, at["dl"] - 0x2C)
        meshes.append(bytes(table) + bytes(body))

    head = bytearray(res_bmsh.HEADER)
    struct.pack_into(">II", head, 0, sub_batches + 1, 8)
    struct.pack_into(">f", head, 8, SCALE)
    records = bytearray(res_bmsh.SUB_BATCH * sub_batches)
    main = struct.pack(">Ii", 0, 0) + struct.pack(">3I", 12, 13, 14)  # ptr gshd, bones...
    main_at = res_bmsh.HEADER + len(records)
    table_at = (main_at + len(main) + 31) & ~31
    main += bytes(table_at - main_at - len(main))
    out = bytearray(head + records + main)
    out += meshes[-1]
    sub_tables = []
    for k in range(sub_batches):
        sub_tables.append(len(out))
        out += meshes[k]
    for k in range(sub_batches):
        rec = res_bmsh.HEADER + k * res_bmsh.SUB_BATCH
        struct.pack_into(">i", out, rec, -shader_back - 0x100 * (k + 1) - rec)
        struct.pack_into(">III", out, rec + 4, 6, 1, 0)
        struct.pack_into(">i", out, rec + 0x1C, sub_tables[k] - (rec + 0x1C))
    struct.pack_into(">i", out, main_at, -shader_back - main_at)
    struct.pack_into(">i", out, 0x24, table_at - 0x24)
    return bytes(out)


def test_is_bmsh_screens_on_the_header():
    assert res_bmsh.is_bmsh(build())
    assert not res_bmsh.is_bmsh(bytes(0x80))
    assert not res_bmsh.is_bmsh(b"\0\0\0\x01" + b"\0" * 4 + struct.pack(">f", 40.0) + bytes(0x80))


def test_tables_read_every_batch():
    data = build(sub_batches=2)
    found = res_bmsh.tables(data)
    assert len(found) == 3
    assert [g for g, _ in found] == [-0x300, -0x400, -0x200]
    assert found[2][1] == res_bmsh._ptr(data, 0x24)


def test_mesh_reads_the_quad_from_the_buffer():
    data = build(sub_batches=0, blended=False)
    m = res_bmsh.model(data)
    assert m is not None and len(m.batches) == 1 and not m.warnings
    b = m.batches[0]
    assert b.positions.shape == (4, 3) and b.indices.reshape(-1, 3).shape == (2, 3)
    assert np.allclose(b.positions[1], (1.0, 0.0, 0.0))
    assert np.allclose(b.positions[2], (1.0, 0.0, 1.0))
    assert np.allclose(b.normals[0], (0.0, -1.0, 0.0))
    assert np.allclose(b.uvs[2], (0.25, 0.75))
    # face normals point the way the vertex normals do
    p, t = b.positions, b.indices.reshape(-1, 3)
    fn = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    assert (fn @ np.array([0.0, -1.0, 0.0]) > 0).all()


def test_blended_slot_takes_its_copy_from_the_run():
    data = build(sub_batches=0, blended=True)
    b = res_bmsh.model(data).batches[0]
    assert b.positions.shape == (5, 3)
    assert np.allclose(b.positions[4], (0.5, 0.0, 2.0))
    # the strip restarted on repeated indices: 2 quad triangles + 1 more, no degenerates
    t = b.indices.reshape(-1, 3)
    assert len(t) == 3 and all(len(set(tri)) == 3 for tri in t.tolist())


def test_strip_rejects_out_of_range_slots():
    data = bytearray(build(sub_batches=0, blended=False))
    table = res_bmsh._ptr(data, 0x24)
    dl = res_bmsh._ptr(data, table + 0x2C)
    struct.pack_into(">H", data, dl + 4 + 8 * 2, 40)
    assert res_bmsh.model(bytes(data)).batches == []


def build_character():
    """A container: the linked level file's surf and gshd, plus a bmsh whose main record
    reaches that gshd."""
    base = bytearray(build_linked())
    found = res.sections(bytes(base))
    gshd = next(s for s in found if s.tag == "gshd")
    # append a bmsh section after the directory-less tail: rebuild through the same writer
    from tests.test_res import build_linked as _  # noqa: F401 - documents the dependency

    bmsh = build(sub_batches=0)
    # place it 0x2000 after the gshd and make the main record's pointer land on the gshd
    at = gshd.offset + 0x2000
    main_at = res_bmsh.HEADER
    blob = bytearray(bmsh)
    struct.pack_into(">i", blob, main_at, gshd.offset - (at + main_at))
    data_off = struct.unpack_from(">I", base, 8)[0]
    body_len = struct.unpack_from(">I", base, 12)[0]
    dir_off = struct.unpack_from(">I", base, 0x1C)[0]
    entries = struct.unpack_from(">I", base, 0x24)[0]
    body = bytearray(base[data_off : data_off + body_len])
    body += bytes(at - data_off - len(body)) + blob
    dirbuf = bytearray(base[dir_off : dir_off + 4 + entries * res.ENTRY])
    struct.pack_into(">I", dirbuf, 0, entries + 1)
    dirbuf += struct.pack(">I4sIII", 9, b"bmsh", at - data_off, len(blob), 0)
    new_dir = data_off + len(body) + (-len(body) % 32)
    out = bytearray(base[:data_off]) + body + bytes(new_dir - data_off - len(body))
    struct.pack_into(">I", out, 12, len(body))
    struct.pack_into(">2I", out, 0x1C, new_dir, len(dirbuf))
    struct.pack_into(">I", out, 0x24, entries + 1)
    return bytes(out + dirbuf)


def test_character_member_names_its_surfs_and_binds_them():
    data = build_character()
    names = [n for n, _ in plugin.expand(data)]
    bmsh = [n for n in names if "_bmsh_" in n]
    assert bmsh == ["003_bmsh_9_t000.bin"]
    members = dict(plugin.expand(data))

    class Src:
        by_path = {f"c/{n}": b for n, b in members.items()}

        def get(self, p):
            return self.by_path[p]

    scenes = plugin.extract(members[bmsh[0]], f"c/{bmsh[0]}", Src())
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.materials[0].texture == "surf_000" and "surf_000" in sc.textures
    assert sc.extras["format"] == "res_bmsh"
    assert len(sc.primitives[0].indices) == 9
