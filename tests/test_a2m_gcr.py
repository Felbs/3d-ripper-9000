"""A2M .gcr level archives (Scooby-Doo! Mystery Mayhem): DTStreamFAT records handing out the
RenderWare world and clumps, and the TEXDIC image dictionaries."""

from __future__ import annotations

import struct

from gcrip.formats import a2m_gcr
from gcrip.formats import rwstream as rw
from gcrip.plugins import a2m_gcr as plugin
from gcrip.plugins import renderware as rwp

RW = 0x1003FFFF


def chunk(kind: int, body: bytes) -> bytes:
    return struct.pack("<3I", kind, len(body), RW) + body


def gcr(records: list[tuple[int, int, bytes]]) -> bytes:
    """(class id, resource id, payload) records, each padded to 32 bytes on disc."""
    table = bytearray(struct.pack(">4I", a2m_gcr.GCR_MAGIC, len(records), 0, 0))
    body = bytearray()
    for cls, res, payload in records:
        table += struct.pack(">4I", len(body), cls, res, len(payload))
        body += payload + bytes(-len(payload) % 32)
    return bytes(table) + bytes(body)


def texdic(images: dict[str, tuple[int, int, int, bytes, bytes]]) -> bytes:
    out = bytearray()
    for name, (w, h, depth, pixels, palette) in images.items():
        stride = len(pixels) // h
        body = chunk(rw.STRUCT, struct.pack("<4I", w, h, depth, stride)) + pixels + palette
        out += chunk(a2m_gcr.IMAGE, body)
        out += struct.pack("<I", len(name)) + name.encode()
    return bytes(out)


def test_gcr_records_and_renderware_members():
    world = chunk(rw.WORLD, b"W" * 40)
    clump = chunk(rw.CLUMP, b"C" * 20)
    data = gcr([(24, 0xFFFFFFFF, world), (69, 7, b"code"), (91, 0x70B, clump)])
    assert a2m_gcr.is_gcr(data[:64], len(data))
    assert plugin.is_container("level/EP1L01.gcr", data[:64])
    recs = a2m_gcr.records(data)
    assert [(r.class_id, r.resource) for r in recs] == [(24, 0xFFFFFFFF), (69, 7), (91, 0x70B)]
    # a record runs to the next one on disc; the RW member is cut at its own chunk size
    assert recs[0].end - recs[0].offset == 64 and recs[2].end == len(data)
    assert plugin.expand(data) == [("world_ffffffff.bsp", world), ("obj_70b.dff", clump)]
    assert not a2m_gcr.is_gcr(b"\0" * 64, 64)


def test_texdic_images_decode_and_name_the_renderware_lookup():
    palette = b"".join(struct.pack("4B", i, 0, 255 - i, 255) for i in range(256))
    px8 = bytes([0, 1, 2, 3]) + bytes(4) + bytes([4, 5, 6, 7]) + bytes(4)  # 4x2, stride 8
    px32 = bytes([9, 8, 7, 6] * 2)  # 2x1 RGBA
    data = texdic({"clue": (4, 2, 8, px8, palette), "photo": (2, 1, 32, px32, b"")})
    assert a2m_gcr.is_texdic(data[:40])
    assert a2m_gcr.texdic_names(data) == ["clue", "photo"]
    imgs = a2m_gcr.texdic_images(data)
    assert imgs["clue"].shape == (2, 4, 4) and tuple(imgs["clue"][1, 3]) == (7, 0, 248, 255)
    assert imgs["photo"].shape == (1, 2, 4) and tuple(imgs["photo"][0, 1]) == (9, 8, 7, 6)

    class Src:
        def __init__(self, files):
            self.files = files
            self.by_path = dict.fromkeys(files)

        def get(self, p):
            return self.files[p]

    files = {"level/EP1/L01/EN/TEXDIC_0.txd": data}
    index = rwp._TextureIndex(Src(files))
    # the archive's `gen` folder looks across the level folder for the dictionaries
    model = "level/EP1/L01/gen/EP1L01.gcr/obj_70b.dff"
    assert index._candidates(model) == ["level/EP1/L01/EN/TEXDIC_0.txd"]
    img = index.find(model, "clue")
    assert img is not None and img.shape == (2, 4, 4)
