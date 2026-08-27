"""Star Fox Adventures model / texture parsers and plugin on a synthetic MODELS.bin."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from gcrip.formats import sfa
from gcrip.plugins import sfa as plugin


def _zlb(payload: bytes) -> bytes:
    comp = zlib.compress(payload, 9)
    return b"ZLB\0" + struct.pack(">III", 1, len(payload), len(comp)) + comp


def _facefeed(payload: bytes) -> bytes:
    z = _zlb(payload)
    # ZLB at word 9 -> field 8 = 12 (header size (12 - 3) * 4 = 0x24)
    head = b"\xfa\xce\xfe\xed" + struct.pack(">III", len(payload), 12, len(z) - 16)
    head += b"\0" * (0x24 - len(head))
    return head + z


class _Writer:
    """LSB-first bit writer matching the game's render script packing."""

    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, n: int) -> None:
        for i in range(n):
            self.bits.append((value >> i) & 1)

    def bytes(self) -> bytes:
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            chunk = self.bits[i : i + 8]
            out.append(sum(b << k for k, b in enumerate(chunk)))
        return bytes(out)


def build_model() -> bytes:
    """Two bones (root, child at +10 y), one coarse blend (0.25/0.75).  Draw 0: a triangle
    on bone 1's slot (bone space), draw 1: a triangle on the blend slot (bind space)."""
    out = bytearray(b"\0" * 0x100)
    positions = np.array(
        [[0, 0, 0], [8, 0, 0], [0, 8, 0], [16, 16, 16], [24, 16, 16], [16, 24, 16]], ">i2"
    )
    normals = np.array([[0, 0, 64]] * 6, ">i1")
    texcoords = np.array([[0, 0], [256, 0], [0, 256]], ">i2")
    out[0x24] = 0  # normal flags
    tex_off = len(out)
    out += struct.pack(">I", 7)  # model texture 0 -> TEX1 id 7
    pos_off = len(out)
    out += positions.tobytes()
    nrm_off = len(out)
    out += normals.tobytes()
    clr_off = len(out)
    out += struct.pack(">H", 0xF00F)
    tc_off = len(out)
    out += texcoords.tobytes()
    out += b"\0" * ((-len(out)) % 4)
    shader_off = len(out)
    sh = bytearray(b"\0" * 0x44)
    struct.pack_into(">i", sh, 0x24, 0)  # layer 0 texture index 0
    struct.pack_into(">i", sh, 0x34, -1)  # no NBT texture
    struct.pack_into(">I", sh, 0x3C, sfa.SHADER_FLAG_CULL_BACK)
    sh[0x40] = sfa.SHADER_ATTR_NRM
    sh[0x41] = 1
    out += sh
    joint_off = len(out)
    out += struct.pack(">BBBB3f3f", 0xFF, 0, 0, 0, 0, 0, 0, 0, 0, 0)  # root (0x1C bytes)
    out += struct.pack(">BBBB3f3f", 0, 1, 0, 0, 0, 10, 0, 0, 10, 0)  # child, head +10 y
    blend_off = len(out)
    out += bytes([0, 1, 1, 0])  # weight0 = 0.25
    # display lists: 3 direct bytes? no probes, 1 pnmtx byte + 16-bit pos/nrm/tex indices
    dl0 = struct.pack(">BH", 0x90 | 6, 3)
    for i in range(3):
        dl0 += struct.pack(">BHHH", 0, i, i, i)
    dl1 = struct.pack(">BH", 0x90 | 6, 3)
    for i in range(3):
        dl1 += struct.pack(">BHHH", 3, 3 + i, 3 + i, i)
    dl0_off = len(out)
    out += dl0 + b"\0" * ((-len(dl0)) % 32)
    dl1_off = len(out)
    out += dl1 + b"\0" * ((-len(dl1)) % 32)
    dlinfo_off = len(out)
    out += struct.pack(">IH", dl0_off, len(dl0)) + b"\0" * 0x16
    out += struct.pack(">IH", dl1_off, len(dl1)) + b"\0" * 0x16
    w = _Writer()
    w.put(1, 4)
    w.put(0, 6)  # shader 0
    w.put(3, 4)
    w.put(1, 1)  # pos 16-bit
    w.put(1, 1)  # nrm 16-bit
    w.put(1, 1)  # tex 16-bit
    w.put(4, 4)
    w.put(2, 4)
    w.put(1, 8)  # slot 0 -> bone 1
    w.put(2, 8)  # slot 1 -> blend 0 (2 joints + 0)
    w.put(2, 4)
    w.put(0, 8)
    w.put(2, 4)
    w.put(1, 8)
    w.put(5, 4)
    script = w.bytes()
    bits_off = len(out)
    out += script + b"\0" * 4
    struct.pack_into(">I", out, 0x20, tex_off)
    struct.pack_into(">I", out, 0x28, pos_off)
    struct.pack_into(">I", out, 0x2C, nrm_off)
    struct.pack_into(">I", out, 0x30, clr_off)
    struct.pack_into(">I", out, 0x34, tc_off)
    struct.pack_into(">I", out, 0x38, shader_off)
    struct.pack_into(">I", out, 0x3C, joint_off)
    struct.pack_into(">I", out, 0x54, blend_off)
    struct.pack_into(">I", out, 0xD0, dlinfo_off)
    struct.pack_into(">I", out, 0xD4, bits_off)
    struct.pack_into(">H", out, 0xD8, len(script))
    struct.pack_into(">HHHH", out, 0xE4, 6, 6, 1, 3)
    out[0xF2] = 1
    out[0xF3] = 2
    out[0xF4] = 1
    out[0xF5] = 2
    out[0xF8] = 1
    out[0xFA] = 0
    return bytes(out)


def build_texture() -> bytes:
    """RGB565 4x4 blue, wrap clamp/repeat, in a ZLB."""
    head = bytearray(b"\0" * 0x60)
    struct.pack_into(">HH", head, 0xA, 4, 4)
    head[0x16] = 4
    head[0x17] = 0
    head[0x18] = 1
    return _zlb(bytes(head) + b"\x00\x1f" * 16)


class _Src:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.by_path = dict.fromkeys(files, True)

    def get(self, path: str) -> bytes:
        return self.files[path]


def _disc() -> _Src:
    model = build_model()
    models_bin = _facefeed(model)
    models_bin += b"\0" * ((-len(models_bin)) % 32)
    tab = struct.pack(">III", 0x10000000, 0xFFFFFFFF, 0)
    tex = build_texture()
    tex1_bin = b"\0" * 32 + tex
    tex1_tab = struct.pack(">I", 0x01000000) * 7 + struct.pack(">I", 0x81000000 | 16)
    return _Src(
        {
            "swaphol/MODELS.bin": models_bin,
            "swaphol/MODELS.tab": tab,
            "swaphol/TEX1.bin": tex1_bin,
            "swaphol/TEX1.tab": tex1_tab,
        }
    )


def test_unwrap_and_parse():
    src = _disc()
    raw = sfa.unwrap(src.get("swaphol/MODELS.bin"))
    assert raw == build_model()
    m = sfa.parse_model(raw)
    assert len(m.positions) == 6 and len(m.joints) == 2 and len(m.blends) == 1
    assert m.joints[1].parent == 0 and m.joints[1].translation == (0.0, 10.0, 0.0)
    assert m.blends[0].weight0 == 0.25
    assert m.texture_ids == [7] and len(m.shaders) == 1 and m.shaders[0].layers[0].texture == 0
    assert len(m.draws) == 2
    assert m.draws[0].vcd == {"direct": 1, "pos": 2, "nrm": 2, "tex0": 2}
    assert m.draws[0].matrix_map[:2] == [1, 2]
    prims = sfa.parse_display_list(m.draws[1])
    assert len(prims) == 1 and prims[0][1] == 6 and list(prims[0][2]["pos"]) == [3, 4, 5]
    np.testing.assert_allclose(sfa.scale_positions(m.positions[[1]], 6), [[8 / 256, 0, 0]])


def test_textures():
    src = _disc()
    frames = sfa.texture_entries(src.get("swaphol/TEX1.tab"), src.get("swaphol/TEX1.bin"), 7)
    assert len(frames) == 1
    tex = sfa.parse_texture(sfa.unwrap(frames[0]))
    assert (tex.width, tex.height, tex.fmt, tex.wrap_s, tex.wrap_t) == (4, 4, 4, 0, 1)
    img = sfa.decode_texture(tex)
    assert img.shape == (4, 4, 4) and tuple(img[0, 0]) == (0, 0, 255, 255)
    assert sfa.texture_entries(src.get("swaphol/TEX1.tab"), src.get("swaphol/TEX1.bin"), 3) == []


def test_plugin_scene():
    src = _disc()
    data = src.get("swaphol/MODELS.bin")
    assert plugin.detect("swaphol/MODELS.bin", data[:64], len(data))
    assert not plugin.detect("swaphol/TEX1.bin", data[:64], len(data))
    assert not plugin.detect("swaphol/MODELS.bin", b"\0" * 64, len(data))
    scenes = plugin.extract(data, "swaphol/MODELS.bin", src)
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.name == "model0000" and [j.parent for j in sc.joints] == [None, 0]
    assert sc.materials[0].texture == "tex0007" and not sc.materials[0].double_sided
    assert sc.materials[0].clamp_u and not sc.materials[0].clamp_v
    assert "tex0007" in sc.textures
    assert len(sc.primitives) == 2
    rigid, blended = sc.primitives
    # bone-space (8/256, 0, 0) moved by bone 1's world translation (0, 10, 0)
    np.testing.assert_allclose(rigid.positions[1], [8 / 256, 10, 0], atol=1e-6)
    assert rigid.joints[0, 0] == 1 and rigid.weights[0, 0] == 1.0
    np.testing.assert_allclose(blended.positions[0], [16 / 256, 16 / 256, 16 / 256], atol=1e-6)
    assert list(blended.joints[0][:2]) == [0, 1]
    np.testing.assert_allclose(blended.weights[0][:2], [0.25, 0.75])
    assert rigid.uvs is not None and np.allclose(rigid.uvs[1], [256 / 1024, 0])
