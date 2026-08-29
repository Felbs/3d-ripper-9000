"""Phantasy Star Online BML archives and GameCube-order Ninja models."""

import struct

from gcrip.formats import bml
from gcrip.plugins import bml as plug
from gcrip.plugins import ninja_gc
from tests.test_sa2b import build_model


def literal_prs(payload: bytes) -> bytes:
    packed = bytearray()
    for i in range(0, len(payload), 8):
        packed.append(0xFF)
        packed += payload[i : i + 8]
    packed += bytes([0x02, 0x00, 0x00])
    return bytes(packed)


def build_nj() -> bytes:
    """NJCM block (little-endian size) whose payload is the big-endian chunk object of
    tests.test_sa2b (object at payload offset 0x40 -> move it to 0)."""
    d = build_model()
    payload = d[0x40:]  # object first; its pointers were absolute, so rebase them
    obj = bytearray(payload)
    # attach, child, sibling pointers in the object (offsets 4, 44, 48) and the attach's
    # vlist / plist pointers (attach at 0x80 - 0x40 = 0x40)
    for at in (4, 0x40, 0x44):
        v = struct.unpack_from(">I", obj, at)[0]
        if v:
            struct.pack_into(">I", obj, at, v - 0x40)
    body = bytes(obj)
    return b"NJCM" + struct.pack("<I", len(body)) + body + b"POF0" + struct.pack("<I", 0)


def test_ninja_gc_model():
    nj = build_nj()
    assert ninja_gc.detect("files/x.nj", nj[:64], len(nj))
    scenes = ninja_gc.extract(nj, "files/x.nj", None)
    assert len(scenes) == 1 and scenes[0].triangles == 2 and len(scenes[0].joints) == 1


def test_bml_archive():
    nj = build_nj()
    packed = literal_prs(nj)
    header = bytearray(64)
    struct.pack_into(">I", header, 4, 1)
    entry = b"lobby_obj.gj".ljust(32, b"\0") + struct.pack(">5I", len(packed), 0, len(nj), 0, 0)
    entry = entry.ljust(64, b"\0")
    data = bytes(header) + entry
    data += bytes(0x800 - len(data)) + packed
    assert bml.is_bml(data[:96], len(data))
    ms = bml.members(data)
    assert [(m.name, m.offset, m.packed, m.size) for m in ms] == [
        ("lobby_obj.gj", 0x800, len(packed), len(nj))
    ]
    assert plug.is_container("files/bm_x.bml", data[:96])
    assert plug.expand(data) == [("lobby_obj.gj", nj)]
