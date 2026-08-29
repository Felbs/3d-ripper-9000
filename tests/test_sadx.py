"""Nintendo REL relocation, SA Tools split configs and big-endian Basic models."""

import struct

import numpy as np

from gcrip.formats import rel, sadx, satools


def build_rel(payload: bytes, key: int, reloc_at: int, target: int) -> bytes:
    """One data section holding ``payload``; a single ADDR32 relocation at ``reloc_at``
    pointing at ``target`` (both section offsets)."""
    hdr = bytearray(0x40)
    sec_tab = 0x40
    sec_off = 0x50
    data_end = sec_off + len(payload)
    imp_off = (data_end + 3) & ~3
    rel_off = imp_off + 8
    struct.pack_into(">12I", hdr, 0, 7, 0, 0, 1, sec_tab, 0, 0, 1, 0, rel_off, imp_off, 8)
    section = struct.pack(">2I", sec_off, len(payload))
    imp = struct.pack(">2I", 7, rel_off)
    rels = struct.pack(">HBBI", 0, rel.R_SECTION, 0, 0)
    rels += struct.pack(">HBBI", reloc_at, 1, 0, target)
    rels += struct.pack(">HBBI", 0, rel.R_END, 0, 0)
    out = bytes(hdr) + section + bytes(sec_off - sec_tab - 8) + payload
    out += bytes(imp_off - len(out)) + imp + rels
    return out


def test_rel_fix_pointers():
    payload = bytes(16)
    data = build_rel(payload, 0xC900000, 4, 12)
    assert rel.is_rel(data[:64], len(data))
    fixed = rel.fix_pointers(data, 0xC900000)
    assert struct.unpack_from(">I", fixed, 0x50 + 4)[0] == 0xC900000 + 0x50 + 12


def test_satools_configs():
    cfgs = satools.for_datafile("files/stg00.rel")
    assert cfgs and cfgs[0].game == "SADX" and cfgs[0].key == 0xC900000
    assert any(e.type == "landtable" for e in cfgs[0].entries)
    assert satools.stage_number("stg13D.rel") == "13"


def test_basic_model_be():
    d = bytearray(0x200)
    obj, model, pts, msets, mats, polys = 0x10, 0x50, 0x80, 0xB0, 0xD0, 0xF0
    struct.pack_into(">II3f3i3fII", d, obj, 0, model, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0)
    struct.pack_into(">IIIIIHH4f", d, model, pts, 0, 4, msets, mats, 1, 1, 0, 0, 0, 1)
    for i, (x, y) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        struct.pack_into(">3f", d, pts + i * 12, x, y, 0)
    struct.pack_into(">HHIIIII", d, msets, (1 << 14) | 0, 1, polys, 0, 0, 0, 0)  # one quad
    struct.pack_into(">4H", d, polys, 0, 1, 2, 3)
    struct.pack_into(">IIfII", d, mats, 0xFFFFFFFF, 0, 0, 2, 0x2000000)
    tree = sadx.basic_object(bytes(d), obj)
    assert tree and tree.root and tree.root.model
    m = tree.root.model
    assert len(m.vertices) == 4 and len(m.strips) == 1 and len(m.strips[0].indices) == 6
    assert m.strips[0].material.texture == 2
    assert np.allclose(m.vertices[2].pos, [1, 1, 0])
