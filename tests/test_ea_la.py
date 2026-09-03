"""EA Los Angeles (Medal of Honor: Frontline): .msh static meshes and .cpt compartments
with embedded SHPG materials and shared-material references into the level's art file."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ea_la
from gcrip.plugins import ea_la as plugin


def shpg() -> bytes:
    """A one-entry GameCube shape: 4x4 CMPR, every block blue."""
    block = bytes([0x00, 0x1F, 0xFF, 0xFF, 0, 0, 0, 0])  # c0 blue, c1 white, all texels c0
    body = block * 4
    entry = bytes([0x1E]) + (0).to_bytes(3, "little") + struct.pack("<6H", 4, 4, 0, 0, 0, 0) + body
    head = b"SHPG" + struct.pack("<II", 16 + 8 + len(entry), 1) + b"G343"
    return head + b"0000" + struct.pack("<I", 24) + entry


class Builder:
    """Records are laid out at build time: the material tables and the chunk table are
    contiguous arrays, the vertex data and shapes go wherever they land."""

    def __init__(self, msh: bool):
        self.msh = msh
        self.body = bytearray(48)
        self.materials: list[list[bytes]] = [[], []]
        self.chunks: list[bytes] = []

    def put(self, blob: bytes, align: int = 16) -> int:
        while len(self.body) % align:
            self.body.append(0)
        at = len(self.body)
        self.body += blob
        return at

    def material(self, table: int, shape: bytes | None, shared: int | None = None) -> int:
        at = self.put(shape, 32) if shape else 0
        m = bytearray(0x70)
        struct.pack_into(">II", m, 0x60, at, 2 if shared is not None else 0)
        struct.pack_into(">I", m, 0x6C, shared or 0)
        self.materials[table].append(bytes(m))
        return len(self.materials[0]) + len(self.materials[1]) - 1

    def chunk(self, material: int, wide: bool, strip: bool) -> None:
        pos = self.put(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], ">f4").tobytes(), 32)
        clr = self.put(bytes([255, 0, 0, 255] * 4))
        nrm = self.put(bytes([0, 0, 64] * 4))
        uv = self.put(np.array([[0, 0], [1, 0], [0, 1], [1, 1]], ">f4").tobytes())
        corners = b"".join(struct.pack(">4H" if wide else "4B", i, i, i, i) for i in range(4))
        dl = self.put(b"\0" * ea_la.DL_HEADER + corners, 32)
        if self.msh:
            data = struct.pack(">4I", (0 if wide else 1) | (4 if strip else 0), 0, 0, 4)
        else:
            data = struct.pack(">HH", 1 if wide else 0, 4)
        data += struct.pack(">5I", pos, clr, nrm, uv, dl)
        dat = self.put(data)
        self.chunks.append((material, dat))

    def build(self) -> bytes:
        tables = []
        for mats in self.materials:
            tables.append((self.put(b"".join(mats), 32) if mats else 0, len(mats)))
        # material index -> record offset, A table then B
        offsets = []
        for at, n in tables:
            offsets += [at + 0x70 * k for k in range(n)]
        recs = []
        for material, dat in self.chunks:
            mat = offsets[material]
            if self.msh:
                recs.append(struct.pack(">8I", 0, mat, dat, 0, 0, 0, 0, 0))
            else:
                recs.append(struct.pack(">5I", 0, 0, mat, dat, 0))
        chunks = (self.put(b"".join(recs), 32) if recs else 0, len(recs))
        size = len(self.body)
        struct.pack_into(
            ">12I", self.body, 0, ea_la.MSH_VERSION if self.msh else ea_la.CPT_VERSION, size,
            tables[0][0], tables[0][1], tables[1][0], tables[1][1], chunks[0], chunks[1],
            0, 0, 0, 0,
        )  # fmt: skip
        return bytes(self.body)


def msh_file() -> bytes:
    b = Builder(True)
    b.material(0, shpg())
    b.material(0, None)
    b.chunk(0, wide=True, strip=True)
    b.chunk(1, wide=False, strip=False)
    return b.build()


def test_msh_chunks_and_embedded_shape():
    data = msh_file()
    assert ea_la.is_msh(data[:64], len(data))
    assert not ea_la.is_cpt(data[:64], len(data))
    model = ea_la.parse(data)
    assert model.warnings == [] and len(model.chunks) == 2
    strip, tris = model.chunks
    assert len(strip.triangles) == 2 and len(tris.triangles) == 1
    np.testing.assert_allclose(strip.positions[:4], [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]])
    np.testing.assert_allclose(strip.normals[0], [0, 0, 1])
    assert strip.colors[0].tolist() == [255, 0, 0, 255]
    np.testing.assert_allclose(strip.uvs[3], [1, 1])
    assert strip.material == 0 and tris.material == 1
    img = ea_la.material_texture(data, model.materials[0])
    assert img.shape == (4, 4, 4) and tuple(img[0, 0]) == (0, 0, 255, 255)
    assert ea_la.material_texture(data, model.materials[1]) is None


class FakeSrc:
    def __init__(self, files):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path):
        return self.files[path]


def test_cpt_compartment_binds_through_the_art_file():
    art = Builder(False)
    art.material(0, None)
    art.material(0, shpg())
    art_data = art.build()
    comp = Builder(False)
    comp.material(0, None, shared=1)
    comp.chunk(0, wide=False, strip=True)
    comp_data = comp.build()
    assert ea_la.is_cpt(comp_data[:64], len(comp_data))
    assert ea_la.parse(comp_data).materials[0].shared == 1
    files = {
        "files/DATA/1/1_1/level.viv/1_1_ART.cpt": art_data,
        "files/DATA/1/1_1/comp.viv/1_1_ART_c0.cpt": comp_data,
    }
    path = "files/DATA/1/1_1/comp.viv/1_1_ART_c0.cpt"
    assert plugin.detect(path, comp_data[:64], len(comp_data))
    (sc,) = plugin.extract(comp_data, path, FakeSrc(files))
    assert sc.warnings == [] and len(sc.primitives) == 1
    assert sc.materials[0].texture is not None and sc.materials[0].texture in sc.textures
    assert tuple(sc.textures[sc.materials[0].texture][0, 0]) == (0, 0, 255, 255)
    # the art file alone has no chunks and yields no scene
    assert plugin.extract(art_data, "files/DATA/1/1_1/level.viv/1_1_ART.cpt", FakeSrc(files)) == []
