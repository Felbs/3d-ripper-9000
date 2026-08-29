"""Sega GVR textures and GVM archives."""

import struct

from gcrip.formats import gvr
from gcrip.plugins import gvm as plug


def build_gvrt(w: int = 8, h: int = 8) -> bytes:
    pixels = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0]) * ((w // 4) * (h // 4))  # CMPR white
    body = struct.pack(">HBB2H", 0, 0, 0x0E, w, h) + pixels
    return b"GVRT" + struct.pack("<I", len(body)) + body


def build_gvm() -> bytes:
    entries = b""
    for i, name in enumerate((b"skin", b"eye")):
        entries += (
            struct.pack(">H", i) + name.ljust(28, b"\0") + struct.pack(">HHI", 0x010E, 0x33, i)
        )
    header = struct.pack(">2H", 0xF, 2) + entries
    return b"GVMH" + struct.pack("<I", len(header)) + header + build_gvrt() + build_gvrt(16, 8)


def test_gvr_and_gvm():
    t = gvr.gvr_texture(build_gvrt(), "solo")
    assert t is not None and t.rgba.shape == (8, 8, 4) and int(t.rgba[0, 0, 0]) == 255
    texs = gvr.gvm_textures(build_gvm())
    assert [(x.name, x.width, x.height) for x in texs] == [("skin", 8, 8), ("eye", 16, 8)]
    assert all(x.rgba is not None for x in texs)
    scenes = plug.extract(build_gvm(), "files/sonictex.prs/payload.bin", None)
    assert scenes and scenes[0].name == "sonictex" and set(scenes[0].textures) == {"skin", "eye"}
    assert scenes[0].extras["textures_only"]
