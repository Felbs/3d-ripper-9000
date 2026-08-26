"""TGC (embedded mini-disc) parsing and manifest recursion, on a synthetic image."""

from __future__ import annotations

import struct

from gcrip.classify import classify
from gcrip.disc import tgc
from gcrip.disc.image import DiscImage
from gcrip.manifest import build_manifest
from tests.builders import build_disc, build_rarc

BMD = b"J3D2bmd3" + bytes(56)
HEADER_SIZE = 0x8000


def build_tgc(files: dict[str, bytes], *, game_id: bytes = b"GZLE01") -> bytes:
    """Wrap a synthetic disc in a TGC header the way Collector's Edition does: the disc
    bytes follow a 0x8000 header, FST offsets stay virtual (file_offset_base) and the
    file area is relocated (file_area_offset)."""
    disc = build_disc(files, game_id=game_id, title=b"Embedded")
    fst_off = struct.unpack(">I", disc[0x424:0x428])[0]
    fst_size = struct.unpack(">I", disc[0x428:0x42C])[0]
    dol_off = struct.unpack(">I", disc[0x420:0x424])[0]
    # smallest file offset in the FST = start of the file area (virtual)
    n = struct.unpack(">I", disc[fst_off + 8 : fst_off + 12])[0]
    offsets = []
    for i in range(1, n):
        e = disc[fst_off + 12 * i : fst_off + 12 * i + 12]
        if e[0] == 0:
            offsets.append(struct.unpack(">I", e[4:8])[0])
    base = min(offsets)
    hdr = struct.pack(
        ">14I",
        0xAE0F38A2,
        0,
        HEADER_SIZE,
        0x100000,
        HEADER_SIZE + fst_off,
        fst_size,
        fst_size,
        HEADER_SIZE + dol_off,
        0x100,
        HEADER_SIZE + base,
        len(disc) - base,
        0,
        0,
        base,
    )
    return hdr + bytes(HEADER_SIZE - len(hdr)) + disc


def test_parse_tgc_offsets():
    blob = build_tgc({"res/Object/Link.arc": build_rarc({"bdl/link.bmd": BMD}), "a.bin": b"ab"})
    assert tgc.is_tgc(blob)
    t = tgc.parse(blob)
    assert t.header.game_id == "GZLE01"
    assert t.header.title == "Embedded"
    by_path = {f.path: f for f in t.files}
    assert set(by_path) == {"res/Object/Link.arc", "a.bin"}
    assert blob[by_path["a.bin"].offset : by_path["a.bin"].offset + 2] == b"ab"
    arc = by_path["res/Object/Link.arc"]
    assert blob[arc.offset : arc.offset + 4] == b"RARC"
    assert "res/Object" in t.dirs
    assert classify("x.tgc", blob[:32], len(blob)).fmt == "TGC"


def test_manifest_walks_tgc(tmp_path):
    inner = build_tgc({"res/Object/Link.arc": build_rarc({"bdl/link.bmd": BMD})})
    disc = build_disc({"tgc/zelda.tgc": inner, "top.bmd": BMD})
    p = tmp_path / "ce.iso"
    p.write_bytes(disc)
    with DiscImage(p) as img:
        m = build_manifest(img)
    by_path = {f.path: f for f in m.files}
    assert by_path["files/tgc/zelda.tgc"].fmt == "TGC"
    model = by_path["files/tgc/zelda.tgc/files/res/Object/Link.arc/root/bdl/link.bmd"]
    assert model.fmt == "BMD"
    assert model.sha1 == by_path["files/top.bmd"].sha1
    boot = by_path["files/tgc/zelda.tgc/sys/boot.bin"]
    assert boot.container == "files/tgc/zelda.tgc"
    # the whole chain is uncompressed, so the model's bytes really sit at disc_offset
    with DiscImage(p) as img:
        assert img.read(model.disc_offset, model.size) == BMD
    assert not m.errors
