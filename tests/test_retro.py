"""Retro (Metroid Prime) PAK / LZO / CMDL / TXTR / CINF+CSKR on synthetic data."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from gcrip.formats import lzo, retro_cmdl, retro_pak, retro_skin, retro_txtr
from gcrip.plugins import retro

# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _align(b: bytes, n: int = 32, fill: bytes = b"\x00") -> bytes:
    return b + fill * (-len(b) % n)


def build_txtr_i8(w: int = 8, h: int = 4, value: int = 0x80) -> bytes:
    return struct.pack(">IHHI", 1, w, h, 1) + bytes([value]) * (w * h)


def build_material_set(texture_id: int) -> bytes:
    mat = struct.pack(">II", 0x1083, 1)  # flags, texture count
    mat += struct.pack(">I", 0)  # texture index
    mat += struct.pack(">I", 0x30F)  # pos, nrm, tex0 as 16-bit indices
    mat += struct.pack(">I", 0)  # group
    mat += struct.pack(">HH", 0, 1)  # blend dst/src
    mat += struct.pack(">II", 1, 1)  # one colour channel, lit
    mat += struct.pack(">I", 1)  # one TEV stage
    mat += struct.pack(">IIII", 0x0007A14F, 0x00021CE7, 0x100, 0x100) + bytes([0, 0, 0, 4])
    mat += struct.pack(">HBB", 0, 0, 0)  # stage samples texture 0 through texgen 0
    mat += struct.pack(">II", 1, 0x40)  # one texgen: type 0, source TEX0
    mat += struct.pack(">II", 4, 0)  # no UV animations
    return struct.pack(">II", 1, texture_id) + struct.pack(">II", 1, len(mat)) + mat


def build_cmdl(texture_id: int) -> bytes:
    """One quad (tristrip) in a version-2 CMDL: float normals, float UVs."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 2, 0], [1, 2, 3]], ">f4").tobytes()
    nrm = np.array([[0, 0, 1]] * 4, ">f4").tobytes()
    uv = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], ">f4").tobytes()
    dl = bytes([0x98, 0, 4])
    for i in range(4):
        dl += struct.pack(">HHH", i, i, i)
    surf = struct.pack(">3fIIIII", 0.5, 1, 1.5, 0, len(dl), 0, 0, 0)
    surf += struct.pack(">3f", 0, 0, 1)
    surf = _align(surf, 32) + dl
    sections = [
        _align(build_material_set(texture_id)),
        _align(pos),
        _align(nrm),
        b"",  # colours
        _align(uv),
        _align(struct.pack(">II", 1, len(_align(surf)))),
        _align(surf),
    ]
    hdr = struct.pack(">III", 0xDEADBABE, 2, 0)
    hdr += struct.pack(">6f", 0, 0, 0, 1, 2, 3)
    hdr += struct.pack(">II", len(sections), 1)
    hdr += struct.pack(f">{len(sections)}I", *[len(s) for s in sections])
    return _align(hdr) + b"".join(sections)


def build_pak(entries: list[tuple[str, int, bytes, bool]], names: dict[tuple[str, int], str]):
    """entries: (type, id, data, compress) -> bytes of a Prime 1 PAK."""
    out = bytearray(b"\x00\x03\x00\x05\x00\x00\x00\x00")
    out += struct.pack(">I", len(names))
    for (t, i), n in names.items():
        out += t.encode() + struct.pack(">II", i, len(n)) + n.encode()
    out += struct.pack(">I", len(entries))
    table_pos = len(out)
    out += b"\x00" * (0x14 * len(entries))
    out = bytearray(_align(bytes(out), 32))
    for k, (t, i, data, comp) in enumerate(entries):
        blob = struct.pack(">I", len(data)) + zlib.compress(data) if comp else data
        blob = _align(blob, 32, b"\xff")
        struct.pack_into(
            ">I4sIII", out, table_pos + 0x14 * k, int(comp), t.encode(), i, len(blob), len(out)
        )
        out += blob
    return bytes(out)


class _Src:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path: str) -> bytes:
        return self.files[path]


# ---------------------------------------------------------------------------
# LZO
# ---------------------------------------------------------------------------


def test_lzo_literals_and_overlapping_match():
    # 6 literals, M3 match of 12 bytes at distance 6 with 1 trailing literal, EOF marker
    stream = bytes([0x17]) + b"Hello " + bytes([0x2A, 0x15, 0x00]) + b"!" + b"\x11\x00\x00"
    assert lzo.decompress(stream) == b"Hello Hello Hello !"


def test_lzo_short_run_and_m2_match():
    stream = b"\x01abcd\x48\x00\x11\x00\x00"
    assert lzo.decompress(stream) == b"abcdbcd"


def test_lzo_segmented_with_stored_segment():
    comp = bytes([0x17]) + b"Hello " + bytes([0x2A, 0x15, 0x00]) + b"!" + b"\x11\x00\x00"
    seg = struct.pack(">h", len(comp)) + comp + struct.pack(">h", -3) + b"xyz"
    assert lzo.decompress_segmented(seg, 22) == b"Hello Hello Hello !xyz"


# ---------------------------------------------------------------------------
# PAK
# ---------------------------------------------------------------------------


def test_pak_expand_names_and_decompresses():
    cmdl = build_cmdl(0xAA)
    txtr = build_txtr_i8()
    pak = build_pak(
        [("CMDL", 0xBB, cmdl, True), ("TXTR", 0xAA, txtr, False), ("TXTR", 0xAA, txtr, False)],
        {("TXTR", 0xAA): "My Tex"},
    )
    assert retro.is_container("data.pak", pak[:64])
    entries = retro.expand(pak)
    assert [n for n, _ in entries] == ["0x000000BB.CMDL", "My_Tex_0x000000AA.TXTR"]
    assert entries[0][1] == cmdl
    assert entries[1][1][: len(txtr)] == txtr  # stored resources keep their 0xFF padding
    assert retro_pak.parse_name("My_Tex_0x000000AA.TXTR") == ("TXTR", 0xAA)


# ---------------------------------------------------------------------------
# TXTR / CMDL / plugin
# ---------------------------------------------------------------------------


def test_txtr_decode():
    img = retro_txtr.decode(build_txtr_i8(8, 4, 0x80))
    assert img.shape == (4, 8, 4)
    assert (img[..., :3] == 0x80).all() and (img[..., 3] == 255).all()


def test_cmdl_parse():
    m = retro_cmdl.parse(build_cmdl(0xAA))
    assert m.version == 2 and len(m.surfaces) == 1
    assert m.material_sets[0].texture_ids == [0xAA]
    mat = m.material_sets[0].materials[0]
    assert mat.diffuse() == (0, 0)
    prims = retro_cmdl.parse_display_list(m.surfaces[0].dl, mat)
    assert len(prims) == 1 and prims[0][0] == 0x98 and len(prims[0][2]) == 4


def test_plugin_extracts_textured_scene():
    cmdl = build_cmdl(0xAA)
    files = {"files/a.pak/0x000000BB.CMDL": cmdl, "files/a.pak/0x000000AA.TXTR": build_txtr_i8()}
    src = _Src(files)
    assert retro.detect("files/a.pak/0x000000BB.CMDL", cmdl[:64], len(cmdl))
    scenes = retro.extract(cmdl, "files/a.pak/0x000000BB.CMDL", src)
    assert len(scenes) == 1
    sc = scenes[0]
    assert sc.triangles == 2 and sc.vertices == 4
    assert sc.materials[0].texture == "0x000000AA"
    assert "0x000000AA" in sc.textures
    p = sc.primitives[0]
    # Z-up (1, 2, 3) -> Y-up (1, 3, -2)
    assert any(np.allclose(v, [1, 3, -2]) for v in p.positions)
    assert p.uvs is not None and p.normals is not None


# ---------------------------------------------------------------------------
# skeleton
# ---------------------------------------------------------------------------


def test_cinf_and_cskr():
    cinf = struct.pack(">I", 2)
    cinf += struct.pack(">II3fI", 3, 99, 0, 0, 1, 0)  # root (parent not in table)
    cinf += struct.pack(">II3fII", 4, 3, 0, 0, 2, 1, 3)  # child of 3, linked to 3
    cinf += struct.pack(">I", 0)  # build order
    cinf += (
        struct.pack(">I", 2) + b"root\0" + struct.pack(">I", 3) + b"tip\0" + struct.pack(">I", 4)
    )
    skel = retro_skin.parse_cinf(cinf)
    assert [b.id for b in skel.bones] == [3, 4] and skel.names == {3: "root", 4: "tip"}
    cskr = struct.pack(">II", 1, 2) + struct.pack(">If", 3, 0.25) + struct.pack(">If", 4, 0.75)
    cskr += struct.pack(">I", 3)
    groups = retro_skin.parse_cskr(cskr)
    joints, weights = retro_skin.skin_arrays(groups, skel, 3)
    assert joints[0].tolist() == [1, 0, 0, 0]
    assert np.allclose(weights[0], [0.75, 0.25, 0, 0])
