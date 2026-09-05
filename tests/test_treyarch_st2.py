"""Treyarch NGL stashes (Kelly Slater's Pro Surfer): the ``.ST2`` container, the ``GCNT``
texture and ``GCNM`` mesh chunks, and the routing that keeps the ``gx`` fallback off them.

The GKSE52 regression: 209 stashes were claimed by nothing, so the scanner exported their
bounding-box tables as 36 garbage models out of 42 (quality audit).  Every mesh decoded
here is checked against the chunk's own declared triangle count, the same identity the
real files satisfy (181 of 183 rigid parts and every batch-split skinned part on the
cached stashes; the two misses are zero-area triangles the game counts).
"""

import struct

import numpy as np

from gcrip.formats import treyarch_st2 as st2
from gcrip.plugins import ngl, plugins_for
from gcrip.plugins import treyarch_st2 as container

# --- builders --------------------------------------------------------------------------


def gcnt(width=8, height=4, fmt=5, pixels=None, palette=b""):
    """A GCNT chunk: 0x28 header + pixels (+ palette for C4/C8)."""
    if pixels is None:
        # RGB5A3 with the top bit set: 0x8000 | r5<<10 | g5<<5 | b5 -> opaque
        pixels = struct.pack(f">{width * height}H", *([0x8000 | (31 << 10)] * (width * height)))
    hdr = st2.TAG_TEX + struct.pack(">I", 3)
    hdr += struct.pack(">HxxIHHBBxxII", 0x20, len(pixels), width, height, fmt, 1, 0, 0)
    return hdr + pixels + palette


def _part_record(
    hdr,
    nidx,
    idx_off,
    nslots,
    slots_off,
    hdr2,
    ntris,
    remap_off,
    nverts,
    verts_off,
    nnrm,
    nrm_off,
    nslots2,
    slots2_off,
):
    return struct.pack(
        ">22I",
        hdr, 0x3F800000, 0, 0, 0, 0x3F800000, 0, 0,  # hdr, radius, centre, 1.0, nbones, 0
        nidx, idx_off, nslots, slots_off, hdr2, 0, ntris, remap_off,
        nverts, verts_off, nnrm, nrm_off, nslots2, slots2_off,
    )  # fmt: skip


def _slots(uvs, color=(255, 255, 255, 255)):
    return b"".join(
        bytes(color) + struct.pack(">hhI", int(u * 512), int(v * 512), 0) for u, v in uvs
    )


def _quad_strip():
    """Two quads as one strip with a doubled-index restart between them: 4 triangles."""
    return [0, 1, 2, 3, 3, 4, 4, 5, 6, 7]


QUAD_POS = np.array(
    [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [3, 0, 0], [2, 1, 0], [3, 1, 0]],
    np.float32,
)


def gcnm_rigid(name=b"board000", part=b"deck"):
    """One rigid part: 8 positions / 8 normals / 8 slots, (pos, nrm, slot) triples."""
    strip = _quad_strip()
    idx = b"".join(struct.pack(">HHH", i, i, i) for i in strip)
    idx += b"\0" * (-len(idx) % 4)
    pos = QUAD_POS.astype(">f4").tobytes()
    nrm = struct.pack(">24h", *([0, 0, 16384] * 8))
    slots = _slots([(p[0] / 3, p[1]) for p in QUAD_POS])
    parts_off = 0x70
    hdr_off = parts_off + 88
    idx_off = hdr_off + st2.PART_HEADER
    verts_off = idx_off + len(idx)
    nrm_off = verts_off + len(pos)
    slots_off = nrm_off + len(nrm)
    end = slots_off + len(slots)
    body = bytearray(end)
    body[parts_off : parts_off + 88] = _part_record(
        hdr_off, len(strip) * 3, idx_off, 0, 0, 0, 4, 0, 8, verts_off, 8, nrm_off, 8, slots_off
    )
    body[hdr_off + 0x10 : hdr_off + 0x10 + len(part)] = part
    body[idx_off : idx_off + len(idx)] = idx
    body[verts_off : verts_off + len(pos)] = pos
    body[nrm_off : nrm_off + len(nrm)] = nrm
    body[slots_off : slots_off + len(slots)] = slots
    return _gcnm_head(name, end, 0, 0, 1, parts_off) + bytes(body[0x70:])


def gcnm_skinned(name=b"surfer000", part=b"ks_p_trso"):
    """One skinned part over two bones, split into two per-bone batches (5 + 5 indices)."""
    strip = _quad_strip()
    batches = (5, 5)  # bone 0 draws the first quad, bone 1 the second - no bridge tris
    idx = struct.pack(">10H", *strip)
    slots = _slots([(p[0] / 3, p[1]) for p in QUAD_POS])
    remap = struct.pack(">8H", *range(8))
    recs = b""
    for i, p in enumerate(QUAD_POS):
        bone = 0 if p[0] < 1.5 else 1
        recs += struct.pack(">3f3h", *p, 0, 0, 16384) + struct.pack(
            ">H4B4B", 1, bone, 0, 0, 0, 255, 0, 0, 0
        )
        assert len(recs) == (i + 1) * st2.RECORD
    bones_off = 0x70
    parts_off = bones_off + 2 * 64
    hdr_off = parts_off + 88
    hdr2 = hdr_off + st2.PART_HEADER
    idx_off = hdr2 + st2.PART_HEADER2
    slots_off = idx_off + len(idx)
    remap_off = slots_off + len(slots)
    verts_off = remap_off + len(remap)
    end = verts_off + len(recs)
    body = bytearray(end)
    ident = np.eye(4, dtype=">f4")
    b0, b1 = ident.copy(), ident.copy()
    b1[3, :3] = (2.0, 0.0, 0.0)  # bone 1 sits at x=2 (row-vector convention)
    body[bones_off : bones_off + 64] = b0.tobytes()
    body[bones_off + 64 : bones_off + 128] = b1.tobytes()
    body[parts_off : parts_off + 88] = _part_record(
        hdr_off, len(strip), idx_off, 8, slots_off, hdr2, 4, remap_off, 8, verts_off, 0, 0, 0, 0
    )
    body[hdr_off + 0x10 : hdr_off + 0x10 + len(part)] = part
    body[hdr2 : hdr2 + 8] = struct.pack(">II", *batches)
    body[idx_off : idx_off + len(idx)] = idx
    body[slots_off : slots_off + len(slots)] = slots
    body[remap_off : remap_off + len(remap)] = remap
    body[verts_off : verts_off + len(recs)] = recs
    return _gcnm_head(name, end, 2, bones_off, 1, parts_off) + bytes(body[0x70:])


def _gcnm_head(name, size, nbones, bones_off, nparts, parts_off):
    head = (
        st2.TAG_MESH
        + struct.pack(">III", 0xA, 1, size)
        + struct.pack(">IIII", 0x01000222, 0, 0, size - 16)
    )
    head += name.ljust(32, b"\0")
    head += struct.pack(">5f", 0, 0, 0, 1.0, 1.0) + struct.pack(">II", 0, 0)
    head += struct.pack(">IIIII", nbones, bones_off, nparts, parts_off, 0)
    assert len(head) == 0x70
    return head


def stash(chunks):
    """A stash whose section A holds *chunks* [(kind, name, bytes)], directory at the tail."""
    body = bytearray()
    entries = []
    for kind, name, blob in chunks:
        off = len(body)
        body += blob + b"\0" * (-len(blob) % 32)
        entries.append((kind, name, off, len(blob)))
    data_end = st2.HEADER + len(body)
    head = struct.pack(
        ">10I", data_end, st2.MAGIC, len(entries), 0x40, 0x40, data_end, data_end, 0, data_end, 0
    )
    head += b"\0" * 16 + b"\xde\xad\xf0\x0d" * 2
    assert len(head) == st2.HEADER
    tail = b""
    for kind, name, off, size in entries:
        e = bytearray(64)
        struct.pack_into(">II", e, 32, off, size)
        e[40], e[41] = kind, 3
        e[52:64] = name[:12].ljust(12, b"\0")
        tail += bytes(e)
    return bytes(head) + bytes(body) + tail


# --- the stash --------------------------------------------------------------------------


def test_stash_is_recognised_by_magic_and_directory_arithmetic():
    data = stash([(6, b"dtop.gct", gcnt())])
    assert st2.is_stash(data[:64], len(data))
    assert not st2.is_stash(data[:64], len(data) + 64)  # directory must fit exactly
    assert not st2.is_stash(bytes(64))


def test_expand_yields_every_mesh_and_texture_chunk_once():
    data = stash(
        [(6, b"dtop.gct", gcnt()), (4, b"hadow.gcmesh", gcnm_rigid()), (1, b"ent", b"spawn x\r\n")]
    )
    members = st2.expand(data)
    assert [n for n, _ in members] == ["000_dtop.gct", "001_hadow.gcmesh"]
    assert members[0][1][:4] == st2.TAG_TEX and members[1][1][:4] == st2.TAG_MESH
    assert len(members[1][1]) == struct.unpack_from(">I", members[1][1], 12)[0]


def test_container_plugin_claims_the_stash_and_keeps_the_scanner_off_it():
    data = stash([(6, b"dtop.gct", gcnt())])
    assert container.is_container("KSP_AUX.ST2", data[:64])
    assert container.expand(data)
    names = [m.NAME for m in plugins_for("files/SURFERS/KSP_AUX.ST2", data[:64], len(data))]
    assert names == ["st2"]  # ordinary claim: no gx fallback
    assert container.extract(data, "files/SURFERS/KSP_AUX.ST2", None) == []


# --- textures ---------------------------------------------------------------------------


def test_texture_decodes_rgb5a3():
    rgba = st2.decode_texture(gcnt())
    assert rgba.shape == (4, 8, 4)
    assert tuple(rgba[0, 0]) == (255, 0, 0, 255)


def test_c8_texture_uses_the_palette_after_the_pixels_in_the_header_tlut_format():
    w, h = 8, 4
    pixels = bytes([1] * (w * h))  # every texel -> palette entry 1
    pal = struct.pack(">256H", 0, 0x07E0, *([0] * 254))  # entry 1 = pure green RGB565
    data = gcnt(w, h, fmt=9, pixels=pixels, palette=pal)
    assert st2.texture_header(data, 0).span == len(data)
    rgba = st2.decode_texture(data)
    assert tuple(rgba[0, 0]) == (0, 255, 0, 255)


# --- meshes -----------------------------------------------------------------------------


def test_rigid_mesh_tiles_the_chunk_and_matches_its_declared_triangles():
    m = st2.parse_mesh(gcnm_rigid())
    assert m.name == "board000" and [p.name for p in m.parts] == ["deck"]
    (p,) = m.parts
    assert p.tiled and not p.skinned
    assert len(p.triangles) == p.declared_triangles == 4  # the restart doubles are dropped
    assert p.positions.shape == (8, 3) and np.allclose(p.normals[:, 2], 1.0)
    assert np.allclose(p.uvs[:, 1], QUAD_POS[:, 1])  # s16 / 512


def test_skinned_mesh_splits_the_strip_per_bone_batch():
    m = st2.parse_mesh(gcnm_skinned())
    (p,) = m.parts
    assert p.skinned and p.tiled and len(m.bones) == 2
    # batches 5 + 5 without a bridge: exactly the declared 4, not the 6 a single strip gives
    assert len(p.triangles) == p.declared_triangles == 4
    assert len(st2.strip_triangles(np.array(_quad_strip()))) == 4  # doubled-index restarts
    assert len(st2.strip_triangles(np.array([0, 1, 2, 3, 4, 5, 6, 7]))) == 6  # no restart
    assert p.joints is not None and list(p.joints[:, 0]) == [0, 0, 0, 0, 1, 1, 1, 1]
    assert np.allclose(p.weights[:, 0], 1.0)


def test_mesh_scene_carries_parts_skeleton_and_extras():
    scene = st2.mesh_scene(st2.parse_mesh(gcnm_skinned()))
    assert [j.name for j in scene.joints] == ["bone_00", "bone_01"]
    assert scene.joints[1].translation == (2.0, 0.0, 0.0)  # row-vector bind matrix
    assert len(scene.primitives) == 1 and scene.primitives[0].joints is not None
    assert scene.extras["declared_triangles"] == 4 and scene.extras["tiled"]


def test_ngl_plugin_routes_members_and_exports_scenes():
    mesh = gcnm_rigid()
    tex = gcnt()
    assert [m.NAME for m in plugins_for("a.ST2/001_x.gcmesh", mesh[:64], len(mesh))] == ["ngl"]
    assert [m.NAME for m in plugins_for("a.ST2/000_x.gct", tex[:64], len(tex))] == ["ngl"]
    # Ultimate Spider-Man's pack textures are not this plugin's: they bind through ngl_mesh
    assert not ngl.detect("amalga_gc.pak/pack/12ab.gct", tex[:64], len(tex))
    # ... nor its 0x1F meshes (a version-0xA claim only)
    later = bytearray(mesh)
    struct.pack_into(">I", later, 4, 0x1F)
    assert not ngl.detect("a.ST2/001_x.gcmesh", bytes(later[:64]), len(later))
    (scene,) = ngl.extract(mesh, "a.ST2/001_x.gcmesh", None)
    assert scene.name == "board000" and len(scene.primitives) == 1
    (scene,) = ngl.extract(tex, "a.ST2/000_dtop.gct", None)
    assert scene.extras["textures_only"] and set(scene.textures) == {"000_dtop"}
