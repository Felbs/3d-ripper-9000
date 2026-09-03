"""Nintendo SDK geometry palettes (.gpl): display objects with DO-relative pointers, quantised
arrays, vertex-descriptor states and GX lists; textures from the named .tpl (or the split
.tpl files beside a Harvest Moon character)."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import nin_gpl
from gcrip.plugins import nin_gpl as plugin


def gpl(version: int, interleaved: bool) -> bytes:
    """One display object: a quad as a strip.  ``interleaved`` puts normals 6 bytes into a
    6-component S16 array the way the 0x005bbc61 files do; otherwise separate arrays."""
    vcd_id = nin_gpl.STATE_VCD[version]
    body = bytearray(0x14)  # header, filled at the end
    desc = len(body)
    body += bytes(8)
    obj = len(body)
    body += bytes(0x18)  # DOLayout

    def put(blob: bytes) -> int:
        while len(body) % 4:
            body.append(0)
        at = len(body)
        body.extend(blob)
        return at - obj  # DO-relative

    quad = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], np.float32)
    normal = np.array([[0, 0, 1]] * 4, np.float32)
    if interleaved:
        rows = np.concatenate([quad * 4096, normal * 16384], 1).astype(">i2")
        pos_arr = put(rows.tobytes())
        nrm_arr = pos_arr + 6
        pos_hdr = put(struct.pack(">IHBB", pos_arr, 4, 0x3C, 6))
        lit_hdr = put(struct.pack(">IHBB", nrm_arr, 4, 0x3E, 6))
    else:
        pos_arr = put((quad * 4096).astype(">i2").tobytes())
        nrm_arr = put((normal * 16384).astype(">i2").tobytes())
        pos_hdr = put(struct.pack(">IHBB", pos_arr, 4, 0x3C, 3))
        lit_hdr = put(struct.pack(">IHBB", nrm_arr, 4, 0x3E, 3))
    clr_arr = put(bytes([200, 100, 50]))
    clr_hdr = put(struct.pack(">IHBB", clr_arr, 1, 0x10, 3))
    uv_arr = put(quad[:, :2].astype(">f4").tobytes())
    tpl_name = put(b"quad.tpl\0")
    tex_hdr = put(struct.pack(">IHBBII", uv_arr, 4, 0x40, 2, tpl_name, 0))
    dl = b"\x98\x00\x04" + b"".join(struct.pack(">3B", i, i, i) for i in range(4))
    dl_at = put(dl)
    vcd = (2 << 2) | (2 << 4) | (2 << 10)  # pos, nrm, tex0 as index8
    states = put(
        struct.pack(">BBHIII", nin_gpl.STATE_TEXTURE, 0, 0, 0x11110001, 0, 0)
        + struct.pack(">BBHIII", vcd_id, 0, 0, vcd, dl_at, len(dl))
    )
    disp_hdr = put(struct.pack(">IIHH", dl_at, states, 2, 0))
    name = len(body)
    body += b"quad\0"
    struct.pack_into(">5IBBH", body, obj, pos_hdr, clr_hdr, tex_hdr, lit_hdr, disp_hdr, 1, 0, 0)
    struct.pack_into(">II", body, desc, obj, name)
    struct.pack_into(">5I", body, 0, version, 0, 0, 1, desc)
    return bytes(body)


def tpl(images: int) -> bytes:
    """A standard TPL of ``images`` 4x4 I8 textures, image i a flat grey of 16 * i."""
    table_at = 12
    headers_at = table_at + 8 * images
    data_at = headers_at + 36 * images
    out = bytearray(struct.pack(">3I", 0x0020AF30, images, table_at))
    for i in range(images):
        out += struct.pack(">II", headers_at + 36 * i, 0)
    for i in range(images):
        out += struct.pack(">HHIIIIII", 4, 4, 1, data_at + 16 * i, 0, 0, 0, 0)
        out += struct.pack(">fBBBB", 0.0, 0, 0, 0, 0)
    for i in range(images):
        out += bytes([16 * i]) * 16
    return bytes(out)


class Src:
    def __init__(self, files):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, p):
        return self.files[p]


def test_both_sdk_versions_and_array_layouts():
    for version, interleaved in ((0x005BBC61, True), (0x00B749E0, False)):
        data = gpl(version, interleaved)
        assert nin_gpl.is_gpl(data[:64], len(data))
        pal = nin_gpl.parse(data)
        assert pal.warnings == [] and [o.name for o in pal.objects] == ["quad"]
        obj = pal.objects[0]
        assert obj.tpl == "quad.tpl" and len(obj.draws) == 1
        draw = obj.draws[0]
        assert draw.texture == 1 and len(draw.triangles) == 2
        np.testing.assert_allclose(draw.positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]])
        np.testing.assert_allclose(draw.normals, [[0, 0, 1]] * 4)
        np.testing.assert_allclose(draw.uvs[3], [1, 1])
        assert draw.colors is None  # no colour in the vertex descriptor


def test_plugin_binds_the_named_tpl_or_the_split_ones_beside():
    data = gpl(0x005BBC61, True)
    files = {"files/quad.arc/quad.gpl": data, "files/quad.arc/quad.tpl": tpl(2)}
    path = "files/quad.arc/quad.gpl"
    assert plugin.detect(path, data[:64], len(data))
    (scene,) = plugin.extract(data, path, Src(files))
    assert len(scene.primitives) == 1 and scene.materials[0].texture == "quad_001"
    assert scene.textures["quad_001"][0, 0, 0] == 16
    split = {
        "files/quad.arc/quad.gpl": data,
        "files/quad.arc/quad_a.tpl": tpl(1),
        "files/quad.arc/quad_b.tpl": tpl(1),
    }
    (scene,) = plugin.extract(data, path, Src(split))
    # texture 1 is the first image of the second split palette (a flat 0 grey)
    assert scene.materials[0].texture == "quad_001" and scene.textures["quad_001"][0, 0, 0] == 0
