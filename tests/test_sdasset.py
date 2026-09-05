"""Silicon Dreams / Gusto ``SDASSETF`` asset files (Freestyle Street Soccer, GUVE51).

The regression these guard: ``*_models.ast`` / ``*_textures.ast`` were classified as
Nintendo AST audio by extension and claimed by nothing, so the ``gx`` fallback scanned
them into two-position noise meshes (88 verts / 2 unique positions / 99.7% degenerate
edges on ``thestreet-kai_models``).  The reader walks the chunk tree byte-exact in both
byte orders, assembles strips over the interleaved vertex buffers (skinning blocks
included), binds the sibling texture file and routes every such file to ``sdasset``.
"""

import struct

import numpy as np

from gcrip import classify
from gcrip.formats import sdasset
from gcrip.plugins import plugins_for
from gcrip.plugins import sdasset as plugin

# --- builders ----------------------------------------------------------------------------


def _name(s: str) -> bytes:
    raw = s.encode() + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def _tag(t: str, le: bool) -> bytes:
    raw = t.ljust(4, "\0").encode()
    return raw[::-1] if le else raw


def leaf(tag, arg, payload, ver=1, le=True):
    e = "<" if le else ">"
    return _tag(tag, le) + struct.pack(e + "III", ver, arg, len(payload)) + payload


def container(tag, name, body, children, ver=1, flags=0, le=True):
    e = "<" if le else ">"
    head = struct.pack(e + "III", ver | (flags << 24), len(body), len(children))
    return _tag(tag, le) + head + _name(name) + body + children


def asset_file(chunks, le=True):
    e = "<" if le else ">"
    magic = sdasset.MAGIC_LE if le else sdasset.MAGIC_BE
    return magic + struct.pack(e + "II", 1, len(chunks)) + b"".join(chunks)


def material(name, texture, effect="\\\\Proteus\\TEXTURED"):
    efct = leaf("EFCT", 1, _name(effect) + struct.pack("<I", 1) + _name(texture) + bytes(40))
    return container("MTRL", name, bytes(40), efct, ver=3, flags=0x09)


QUAD = np.array(
    [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], np.float32
)  # a strip 0 1 2 3 = two triangles facing +Z


def data_chunk(ident, positions, blocks=(), attrs=(1, 2, 4)):
    stride = sum(sdasset.ATTR_SIZES[a] for a in attrs)

    def verts(pos):
        rows = []
        for p in pos:
            row = b""
            for a in attrs:
                if a == 1:
                    row += struct.pack("<3f", *p)
                elif a == 2:
                    row += struct.pack("<3f", 0, 0, 1)
                elif a == 3:
                    row += bytes((255, 128, 64, 255))
                elif a == 4:
                    row += struct.pack("<2f", p[0], p[1])
            rows.append(row)
        return b"".join(rows)

    body = struct.pack("<IIII", 4, ident, stride, len(positions))
    body += bytes(attrs) + b"\x80" + bytes(8 - len(attrs) - 1) + bytes(8)
    body += verts(positions)
    body += struct.pack("<I", len(blocks))
    for bones, pos, junk in blocks:
        body += struct.pack("<I", len(bones)) + struct.pack(f"<{len(bones)}I", *bones)
        body += struct.pack("<I", len(pos)) + verts(pos) + junk
    return leaf("DATA", ident, body)


def mesh_chunk(ident, name, data_id, strips, width=2, nattr=3, ver=5, trailers=None):
    desc = struct.pack("<8I", *([(0x0F << 24) | (width << 16), 1] * nattr + [0, 0] * (4 - nattr)))
    bbox = struct.pack("<6f", 0, 0, 0, 1, 1, 0)
    if ver >= 5:
        head = bbox + struct.pack(
            "<8I", ident, sum(map(len, strips)), len(strips), 0, 0, 0, 0, data_id
        )
    else:
        head = struct.pack("<3I", ident, sum(map(len, strips)), len(strips)) + bbox
        head += struct.pack("<3I", 0, 0, data_id)
    body = _name(name) + head + desc + bytes(96)
    fmt = {1: "B", 2: "H", 4: "I"}[width]
    for k, s in enumerate(strips):
        idx = b"".join(struct.pack("<" + fmt, i) * nattr for i in s)
        idx += b"\0" * (-len(idx) % 4)
        body += struct.pack("<I", len(s)) + idx + struct.pack("<I", trailers[k] if trailers else 0)
    return leaf("MESH", ident, body, ver=ver)


def lod_chunk(ident, dist, ids, name=""):
    return leaf(
        "LOD",
        ident,
        struct.pack("<f", dist) + _name(name) + struct.pack(f"<{len(ids) + 1}I", len(ids), *ids),
        ver=2,
    )


def wght_chunk(ident, entries):
    body = struct.pack("<I", len(entries))
    for bones, ws in entries:
        body += struct.pack("<I", len(bones)) + struct.pack(f"<{len(bones)}I", *bones)
        body += struct.pack(f"<{len(ws)}f", *ws)
    return leaf("WGHT", ident, body)


def model(name, children):
    return container("MDL", name, bytes(0x14), b"".join(children), ver=5, flags=0x0F)


def skeleton(names, parents, translations):
    blob = b"".join(n.encode() + b"\0" for n in names)
    body = struct.pack("<II", len(names), len(blob)) + blob
    body += struct.pack(f"<{len(names)}i", *parents)
    for t in translations:  # identity rotation, translation in the last row
        m = np.eye(4, dtype=np.float32)
        m[3, :3] = t
        body += m.tobytes()
    body += bytes(4 * len(names))
    return container("SKEL", "Player", body, b"", ver=1, flags=0x0F)


def rigid_file():
    return asset_file(
        [
            material("brick", "WallTex"),
            model(
                "box",
                [
                    leaf("BND", 1, bytes(40)),
                    data_chunk(1, QUAD),
                    leaf("WDGE", 1, struct.pack("<IIIIII", 4, 4, 0, 1, 2, 3)),
                    mesh_chunk(1, "brick", 1, [[0, 1, 2, 3]]),
                    lod_chunk(1, 100.0, [1]),
                    leaf("INFO", 1, b"ProteusMaxExporter\0\0"),
                ],
            ),
        ]
    )


def texture_file(name="WallTex", w=8, h=4):
    body = struct.pack(">HHHH", w, h, w, h) + bytes(4) + bytes((3, 2, 1, 0)) + bytes((8, 0, 0, 0))
    body += bytes(4) + struct.pack(">I", 0x10000)
    pixels = bytes(range(w * h))  # one I8 tile of 8x4
    imag = leaf("IMAG", 0, b"GC\0\0" + pixels, le=False)
    return asset_file([container("BMAP", name, body, imag, ver=3, le=False)], le=False)


# --- the chunk walk ----------------------------------------------------------------------


def test_walk_tiles_a_little_endian_file_exactly():
    data = rigid_file()
    assert sdasset.is_sdasset(data[:8])
    assert sdasset.tiles(data)
    (seg,) = sdasset.parse(data)
    assert [c.tag for c in seg.chunks] == ["MTRL", "MDL"]
    assert seg.chunks[1].name == "box"
    assert [c.tag for c in seg.chunks[1].children] == ["BND", "DATA", "WDGE", "MESH", "LOD", "INFO"]
    assert seg.end == len(data)


def test_walk_tiles_a_big_endian_texture_file():
    data = texture_file()
    assert sdasset.tiles(data)
    (seg,) = sdasset.parse(data)
    assert not seg.le
    assert seg.chunks[0].tag == "BMAP" and seg.chunks[0].children[0].tag == "IMAG"


def test_a_truncated_file_is_refused_not_misread():
    data = rigid_file()
    assert not sdasset.tiles(data[:-8])
    assert not sdasset.tiles(b"RIFF" + data[4:])


def test_concatenated_files_are_separate_segments():
    data = rigid_file() + rigid_file()
    segs = sdasset.parse(data)
    assert len(segs) == 2 and segs[1].end == len(data)
    assert len(sdasset.read(data)) == 2


# --- geometry ----------------------------------------------------------------------------


def test_rigid_mesh_reads_positions_normals_uvs_and_strips():
    (asset,) = sdasset.read(rigid_file())
    (mdl,) = asset.models
    vb = mdl.buffers[1]
    assert np.array_equal(vb.positions, QUAD)
    assert vb.normals is not None and np.allclose(vb.normals[:, 2], 1)
    assert vb.uvs is not None and np.allclose(vb.uvs, QUAD[:, :2])
    (mesh,) = mdl.detail_meshes()
    assert mesh.name == "brick" and mesh.data_id == 1
    tri = sdasset.triangulate(mesh.strips)
    assert tri.tolist() == [[0, 1, 2], [2, 1, 3]]  # both wound to face +Z
    p = vb.positions[tri]
    assert np.all(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])[:, 2] > 0)


def test_degenerate_strip_triangles_are_dropped_and_u8_indices_are_padded():
    data = asset_file(
        [
            model(
                "m",
                [
                    data_chunk(1, QUAD, attrs=(1, 2, 3, 4)),
                    mesh_chunk(1, "x", 1, [[0, 1, 2, 2, 3], [3, 2, 1]], width=1, nattr=4),
                ],
            )
        ]
    )
    (asset,) = sdasset.read(data)
    (mesh,) = asset.models[0].meshes
    assert mesh.complete and [len(s) for s in mesh.strips] == [5, 3]
    assert len(sdasset.triangulate(mesh.strips)) == 2  # 0 1 2 | 1 2 2 x | 2 2 3 x | 3 2 1
    assert asset.models[0].buffers[1].colors is not None


def test_version3_mesh_layout_puts_counts_before_the_bbox():
    data = asset_file(
        [
            model(
                "ball",
                [
                    data_chunk(1, QUAD),
                    mesh_chunk(1, "1 - Default", 1, [[0, 1, 2, 3]], width=4, ver=3),
                ],
            )
        ]
    )
    (asset,) = sdasset.read(data)
    (mesh,) = asset.models[0].meshes
    assert mesh.complete and mesh.data_id == 1 and mesh.strips[0].tolist() == [0, 1, 2, 3]


def test_lowest_distance_lod_is_the_detail_set():
    data = asset_file(
        [
            model(
                "m",
                [
                    data_chunk(1, QUAD),
                    mesh_chunk(1, "lo", 1, [[0, 1, 2]]),
                    mesh_chunk(2, "hi", 1, [[0, 1, 2, 3]]),
                    lod_chunk(1, 100.0, [1], name="Player"),
                    lod_chunk(2, 25.0, [2], name="Player"),
                ],
            )
        ]
    )
    (asset,) = sdasset.read(data)
    assert [m.name for m in asset.models[0].detail_meshes()] == ["hi"]


def test_skinning_blocks_extend_the_buffer_to_the_weight_count():
    extra = np.array([[2, 2, 0], [3, 3, 0]], np.float32)
    weights = [([0], [1.0])] * 4 + [([1, 2], [0.75, 0.25])] * 2
    junk = bytes(2 * 2 * 32)  # (nv) x (bones - 1) bone-space copies at the 32-byte stride
    data = asset_file(
        [
            model(
                "m",
                [
                    data_chunk(1, QUAD, blocks=[([0, 5, 6], extra, junk)]),
                    wght_chunk(1, weights),
                    mesh_chunk(1, "x", 1, [[0, 1, 4, 5]]),
                ],
            )
        ]
    )
    (asset,) = sdasset.read(data)
    vb = asset.models[0].buffers[1]
    assert vb.complete and len(vb.positions) == 6
    assert np.array_equal(vb.positions[4:], extra)
    assert vb.blocks == [([0, 5, 6], 2)]
    assert len(asset.models[0].weights[1]) == 6


def test_a_block_header_is_searched_for_when_the_copy_arithmetic_is_off():
    """Ryu_Mouth's 79-vertex block carries 77 x 4 copies, not 79 x 4."""
    extra = np.array([[2, 2, 0], [3, 3, 0]], np.float32)
    more = np.array([[9, 9, 9]], np.float32)
    weights = [([0], [1.0])] * 7
    short = bytes(2 * 2 * 32 - 64)  # 64 bytes fewer than nv * (n-1) * stride
    data = asset_file(
        [
            model(
                "m",
                [
                    data_chunk(1, QUAD, blocks=[([0, 5, 6], extra, short), ([0, 1], more, b"")]),
                    wght_chunk(1, weights),
                ],
            )
        ]
    )
    (asset,) = sdasset.read(data)
    vb = asset.models[0].buffers[1]
    assert vb.complete and len(vb.positions) == 7 and np.array_equal(vb.positions[6], more[0])


# --- skeleton ----------------------------------------------------------------------------


def test_skeleton_locals_are_parent_relative():
    skel = skeleton(["Player", "Pelvis"], [-1, 0], [(0, 0, 10), (0, 0, 15)])
    data = asset_file([skel, model("m", [data_chunk(1, QUAD)])])
    (asset,) = sdasset.read(data)
    assert asset.skeleton is not None
    assert asset.skeleton.names == ["Player", "Pelvis"] and asset.skeleton.parents == [-1, 0]
    (t0, r0, s0), (t1, r1, s1) = asset.skeleton.locals()
    assert np.allclose(t0, (0, 0, 10)) and np.allclose(t1, (0, 0, 5))
    assert np.allclose(r1, (0, 0, 0, 1)) and np.allclose(s1, 1)


# --- textures ----------------------------------------------------------------------------


def test_bitmap_format_comes_from_the_bit_depth_and_compressed_flag():
    (asset,) = sdasset.read(texture_file())
    (bm,) = asset.bitmaps
    assert (bm.name, bm.width, bm.height, bm.fmt) == ("WallTex", 8, 4, 1)
    rgba = sdasset.decode_bitmap(bm)
    assert rgba.shape == (4, 8, 4) and rgba[0, 0, 0] == 0 and rgba[3, 7, 0] == 31


def test_compressed_flag_means_cmpr():
    data = bytearray(texture_file())
    # byte 3 of the first format word (after name 8 + 12 bytes of dims/zero) is the flag
    off = data.index(b"IMAG") - 16 + 3
    data[off] = 7
    (asset,) = sdasset.read(bytes(data))
    assert asset.bitmaps[0].fmt == 14


# --- the plugin --------------------------------------------------------------------------


class FakeSrc:
    def __init__(self, files):
        self.by_path = dict(files)

    def get(self, path):
        return self.by_path[path]


def test_files_route_to_sdasset_and_classify_as_models_not_audio():
    data = rigid_file()
    path = "files/Skins/TheStreet-Kai/thestreet-kai_models.ast"
    assert [m.NAME for m in plugins_for(path, data[:64], len(data))] == ["sdasset"]
    assert classify.classify(path, data[:64], len(data)).kind == "model"
    tex = texture_file()
    assert [m.NAME for m in plugins_for("files/x_textures.ast", tex[:64], len(tex))] == ["sdasset"]
    assert classify.classify("files/x.ast", b"STRM" + bytes(60)).kind == "audio"
    assert not plugin.detect("files/x.ast", b"STRM" + bytes(60), 4096)


def test_plugin_binds_the_sibling_texture_file_case_insensitively():
    path = "files/Skins/Team/Ryu/Ryu_Models.ast"
    src = FakeSrc(
        {path: rigid_file(), "files/Skins/Team/Ryu/Ryu_Textures.ast": texture_file("walltex")}
    )
    (scene,) = plugin.extract(src.get(path), path, src)
    assert scene.name == "box"
    assert len(scene.primitives) == 1 and scene.primitives[0].indices.tolist() == [0, 1, 2, 2, 1, 3]
    assert scene.materials[0].texture == "walltex" and "walltex" in scene.textures
    assert scene.extras["format"] == "sdasset" and scene.extras["triangles"] == 2


def test_plugin_yields_a_scene_per_concatenated_player_and_skins_them():
    skel = skeleton(["Player", "Pelvis"], [-1, 0], [(0, 0, 0), (0, 0, 5)])
    player = asset_file(
        [
            material("skin", "Face"),
            skel,
            model(
                "Ryu",
                [
                    data_chunk(1, QUAD),
                    wght_chunk(
                        1, [([1], [1.0]), ([0, 1], [0.75, 0.25]), ([1], [1.0]), ([1], [1.0])]
                    ),
                    mesh_chunk(1, "skin", 1, [[0, 1, 2, 3]]),
                ],
            ),
        ]
    )
    scenes = plugin.extract(player + player, "files/Skins/T/t_models.ast", FakeSrc({}))
    assert [s.name for s in scenes] == ["Ryu", "Ryu"]
    scene = scenes[0]
    assert [j.name for j in scene.joints] == ["Player", "Pelvis"]
    prim = scene.primitives[0]
    assert prim.joints is not None and prim.joints[1].tolist() == [0, 1, 0, 0]
    assert np.allclose(prim.weights[1], [0.75, 0.25, 0, 0])
    assert scene.extras["skinned_meshes"] == 1


def test_a_texture_file_exports_pictures_only():
    (scene,) = plugin.extract(texture_file(), "files/Skins/T/t_textures.ast", None)
    assert scene.extras == {"textures_only": True, "format": "sdasset"}
    assert list(scene.textures) == ["WallTex"]
