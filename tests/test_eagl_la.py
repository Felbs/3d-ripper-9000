"""EA Los Angeles 2003-04 EAGL packets (Medal of Honor: Rising Sun, GoldenEye: Rogue
Agent): separately indexed streams behind light-block externs, display lists found behind the
last stream, and the .msh / .cpt wrappers whose ELF tails live in .rtc files."""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ea_la, eagl
from gcrip.plugins import ea_la as la_plugin
from gcrip.plugins import eagl as eagl_plugin
from tests.test_ea_la import shpg as _shpg

ANIM = "__MATRIX4 *:::EAGLAnimationBuffer"
MODELVIEW = "__const MATRIX4:::EAGL::ViewPort::gpModelViewMatrix"
LIGHT = "__EAGL::LightBlock:::g_pMOHLightBlock"
IRRAD = "__COORD4:::g_pMOHIrradLightBlock"
STATE = "__EAGL::GeoPrimState:::RUNTIME_ALLOC::UID=1978;;SetPrimitiveType=EAGL::PT_TRIANGLESTRIP;"
TAR = "__EAGL::TAR:::RUNTIME_ALLOC::moh_tar=;SHAPENAME=!xHl,1"


def shpg() -> bytes:
    """The Frontline test shape, named after the TAR's SHAPENAME."""
    return _shpg().replace(b"0000", b"!xHl", 1)


class Obj:
    """A relocatable EAGL object: ``.data`` bytes, symbols and relocations, emitted either
    whole (a level.viv ``.o``) or split into the front (ELF header + .data) and the tail
    (tables + section headers) the way .msh / .cpt + .rtc ship it."""

    def __init__(self):
        self.data = bytearray()
        self.names = ["", ""]  # 0 null, 1 the section
        self.values = [0, 0]
        self.shndx = [0, 1]
        self.relocs: list[tuple[int, int]] = []

    def sym(self, name: str, value: int = 0, defined: bool = False) -> int:
        if name in self.names:
            return self.names.index(name)
        self.names.append(name)
        self.values.append(value)
        self.shndx.append(1 if defined else 0)
        return len(self.names) - 1

    def put(self, blob: bytes, align: int = 16) -> int:
        while len(self.data) % align:
            self.data.append(0)
        at = len(self.data)
        self.data += blob
        return at

    def ptr(self, at: int, value: int, sym: int = 1) -> None:
        struct.pack_into("<I", self.data, at, value)
        self.relocs.append((at, sym))

    def packet(self, shader: str, entries: list[tuple[int, int | str]]) -> None:
        """A packet: 0x1c header bytes, the shader pointer, the uncounted palette pointer,
        then (count, pointer | extern) pairs and a zero terminator."""
        pk = self.put(bytes(0x1C + 8 + 8 * (len(entries) + 1)), 32)
        self.ptr(pk + 0x1C, 0, self.sym(shader))
        self.ptr(pk + 0x20, 0, 1)
        o = pk + 0x24
        for count, target in entries:
            struct.pack_into(">I", self.data, o, count)
            if isinstance(target, str):
                self.ptr(o + 4, 0, self.sym(target))
            else:
                self.ptr(o + 4, target, 1)
            o += 8
        self.sym(f"__Model:::{shader}_model", pk, True)

    def build(self) -> tuple[bytes, bytes]:
        strtab = bytearray(b"\0")
        offs = []
        for n in self.names:
            offs.append(len(strtab) if n else 0)
            if n:
                strtab += n.encode() + b"\0"
        symtab = bytearray()
        for i in range(len(self.names)):
            symtab += struct.pack("<IIIBBH", offs[i], self.values[i], 4, 0, 0, self.shndx[i])
        rel = b"".join(struct.pack("<II", off, (sym << 8) | 2) for off, sym in self.relocs)
        shstr = b"\0.data\0.shstrtab\0.strtab\0.symtab\0.rel.data\0"
        body = bytearray(0x40)
        off_data = len(body)
        body += self.data
        split = len(body)
        off_shstr = len(body)
        body += shstr
        off_str = len(body)
        body += strtab
        body += bytes(-len(body) % 4)
        off_sym = len(body)
        body += symtab
        off_rel = len(body)
        body += rel
        body += bytes(-len(body) % 4)
        e_shoff = len(body)
        sections = [
            (0, 0, 0, 0),
            (1, off_data, len(self.data), 1),
            (7, off_shstr, len(shstr), 3),
            (17, off_str, len(strtab), 3),
            (25, off_sym, len(symtab), 2),
            (33, off_rel, len(rel), 9),
        ]
        for name, off, size, typ in sections:
            link = 4 if typ == 9 else (3 if typ == 2 else 0)
            info = 1 if typ in (2, 9) else 0
            entsize = 16 if typ == 2 else (8 if typ == 9 else 0)
            body += struct.pack("<IIIIIIIIII", name, typ, 0, 0, off, size, link, info, 4, entsize)
        hdr = b"\x7fELF\x01\x01\x01" + bytes(9)
        hdr += struct.pack("<HHIIIIIHHHHHH", 1, 8, 1, 0, 0, e_shoff, 0, 0x34, 0, 0, 40, 6, 2)
        body[: len(hdr)] = hdr
        return bytes(body[:split]), bytes(body[split:])


QUAD = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]])


def rising_sun_skin() -> Obj:
    """A 2003 skin packet: header, one skin row, s16 positions (10 fraction bits), s8 normals
    and s16 texcoords with different counts, the light block between the matrices and the
    streams, and a 4-byte-corner strip behind the last stream."""
    ob = Obj()
    header = ob.put(struct.pack(">4I", 4, 0, 0, 0))
    weight = struct.unpack(">I", struct.pack(">f", 1.0))[0]
    skin = ob.put(struct.pack(">4I", weight | 7, 0, 0, 0))
    pos = ob.put((QUAD * 1024).astype(">i2").tobytes(), 4)
    nrm = ob.put(np.array([[0, 0, 64], [0, 64, 0]], np.int8).tobytes(), 4)
    uv = ob.put((QUAD[:, :2] * 1024).astype(">i2").tobytes(), 4)
    dl = b"\x98\x00\x04" + b"".join(bytes([3, i, i % 2, i]) for i in range(4))
    ob.put(dl, 4)
    ob.packet(
        "Moh3_Skin_LitTextureObjectFog",
        [
            (1, header),
            (1, ANIM),
            (1, skin),
            (1, MODELVIEW),
            (1, LIGHT),
            (4, pos),
            (2, nrm),
            (4, uv),
            (1, TAR),
            (1, STATE),
        ],
    )
    return ob


def goldeneye_mesh(compartment: bool = False) -> Obj:
    """A 2004 static packet: s16 (or u16 + origin) positions, one RGBA8 colour, s16
    texcoords, f32 x4 normals, the packet constants behind the state, then two strips whose
    corners are [pos][clr][nrm u16][uv]; the header counts the corners of one merged strip."""
    ob = Obj()
    header = ob.put(struct.pack(">4I", 7, 4, 0, 0))
    scale = 256
    quad = QUAD + (0 if not compartment else 0)
    pos = ob.put((quad * scale).astype(">u2" if compartment else ">i2").tobytes(), 4)
    clr = ob.put(bytes([255, 128, 0, 255]), 4)
    uv = ob.put((QUAD[:, :2] * 1024).astype(">i2").tobytes(), 4)
    nrm = ob.put(np.array([[0, 0, 1, 0]] * 4, ">f4").tobytes(), 4)
    # the packet constants pack right behind the streams (4-byte boundaries throughout)
    origin = ob.put(struct.pack(">4f", 10.0, 20.0, 30.0, 0.0), 4)
    zero = ob.put(bytes(16), 4)
    four = ob.put(struct.pack(">I", 4), 4)
    matrix = ob.put(np.eye(4, dtype=">f4").tobytes(), 4)
    corners = [bytes([i, 0, 0, i, i]) for i in (0, 1, 2, 1, 3, 2)]
    dl = b"\x98\x00\x03" + b"".join(corners[:3]) + b"\x98\x00\x03" + b"".join(corners[3:])
    ob.put(dl, 16)
    ob.packet(
        "Moh3_Cpt_Texture1" if compartment else "Moh3_Msh_Texture1",
        [
            (1, header),
            (1, MODELVIEW),
            (1, IRRAD),
            (4, pos),
            (1, clr),
            (4, uv),
            (4, nrm),
            (1, STATE),
            (1, TAR),
            (1, origin),
            (1, zero),
            (1, four),
            (1, matrix),
        ],
    )
    return ob


def test_rising_sun_skin_packet():
    front, tail = rising_sun_skin().build()
    obj = eagl.parse(front + tail)
    assert obj.warnings == [] and len(obj.models) == 1
    (pk,) = obj.models[0].packets
    assert pk.shader == "Moh3_Skin_LitTextureObjectFog" and pk.stride == 4
    np.testing.assert_allclose(pk.positions, QUAD)
    assert len(pk.indices) == 6
    np.testing.assert_allclose(pk.uvs, QUAD[:, :2])
    np.testing.assert_allclose(pk.normals, [[0, 0, 1], [0, 1, 0], [0, 0, 1], [0, 1, 0]])
    assert pk.textures == ["!xHl"]
    # the slot byte (3 = GX position matrix 1) reads the skin row: bone 7 at weight 1
    assert pk.joints is not None and pk.joints[0].tolist() == [7, 0, 0, 0]
    np.testing.assert_allclose(pk.weights[0], [1, 0, 0, 0])


def test_goldeneye_mesh_packet_counts_a_merged_strip():
    front, tail = goldeneye_mesh().build()
    obj = eagl.parse(front + tail)
    assert obj.warnings == []
    (pk,) = obj.models[0].packets
    assert pk.stride == 5 and len(pk.indices) == 6
    np.testing.assert_allclose(pk.positions, QUAD[[0, 1, 2, 1, 3, 2]])
    np.testing.assert_allclose(pk.normals[0], [0, 0, 1])
    assert pk.colors is not None and pk.colors[0].tolist() == [255, 128, 0, 255]
    np.testing.assert_allclose(pk.uvs[4], [1, 1])
    assert pk.joints is None


def test_compartment_positions_are_unsigned_from_the_packet_origin():
    front, tail = goldeneye_mesh(compartment=True).build()
    (pk,) = eagl.parse(front + tail).models[0].packets
    np.testing.assert_allclose(pk.positions[0], [10, 20, 30])
    np.testing.assert_allclose(pk.positions[4], [11, 21, 30])


def rtc(entries: dict[int, bytes]) -> bytes:
    body = bytearray(b"RTC\0" + struct.pack(">IIIII", 0x42042F00, 2, 0, len(entries), len(entries)))
    table = 0x18 + 12 * len(entries)
    blobs = bytearray()
    for ident, blob in sorted(entries.items()):
        body += struct.pack(">3I", ident, table + len(blobs), len(blob))
        blobs += blob
    out = body + blobs
    struct.pack_into(">I", out, 0xC, len(out))
    return bytes(out)


def msh_file(front: bytes, ident: int) -> bytes:
    head = bytearray(0x100)
    struct.pack_into(
        ">6I", head, 0, ea_la.MSH_EAGL_VERSION, 0x100 + len(front), 0x80, 4, 0x100, len(front)
    )
    struct.pack_into(">I", head, 0x34, ident)
    return bytes(head) + front


def cpt_file(fronts: list[bytes], shapes: bytes | None = None) -> bytes:
    head = bytearray(0x80)
    body = bytearray()
    if shapes:
        struct.pack_into(">II", head, 8, 0x80, len(shapes))
        body += shapes
        body += bytes(-len(body) % 0x80)
    for f in fronts:
        body += f
        body += bytes(-len(body) % 0x80)
    struct.pack_into(">II", head, 0, ea_la.CPT_EAGL_VERSION, 0x80 + len(body))
    return bytes(head) + body


class FakeSrc:
    def __init__(self, files):
        self.files = files
        self.by_path = dict.fromkeys(files)

    def get(self, path):
        return self.files[path]


def test_wrappers_join_their_tails_from_the_rtc_files():
    front, tail = rising_sun_skin().build()
    front2, tail2 = goldeneye_mesh(compartment=True).build()
    art = cpt_file([], shapes=shpg())
    msh = msh_file(front, 0xA98BC7FA)
    cpt = cpt_file([front2, front])
    assert ea_la.is_eagl_msh(msh[:64], len(msh)) and not ea_la.is_msh(msh[:64], len(msh))
    assert ea_la.is_eagl_cpt(cpt[:64], len(cpt)) and ea_la.is_eagl_cpt(art[:64], len(art))
    assert ea_la.rtc_tables(rtc({0xA98BC7FA: tail})) == {0xA98BC7FA: tail}
    assert ea_la.eagl_msh_object(msh, {0xA98BC7FA: tail}) == front + tail
    assert ea_la.eagl_cpt_objects(cpt, {0: tail2, 1: tail}) == [front2 + tail2, front + tail]
    assert ea_la.eagl_cpt_objects(art, {}) == []
    assert ea_la.cpt_shapes(art) == shpg() and ea_la.cpt_shapes(cpt) is None
    files = {
        "files/DATA/1/1_1/symbols.rtc": rtc({0xA98BC7FA: tail}),
        "files/DATA/1/1_1/level.viv/Head.msh": msh,
        "files/DATA/1/1_1/level.viv/1_1_Art.cpt": art,
        "files/DATA/1/1_1/comp.viv/1_1_Art_c0.cpt": cpt,
        "files/DATA/1/1_1/comp.viv/1_1_Art_c0.rtc": rtc({0: tail2, 1: tail}),
        "files/DATA/1/1_1/level.viv/Head_GEO.mesh.o": front + tail,
    }
    src = FakeSrc(files)
    path = "files/DATA/1/1_1/level.viv/Head.msh"
    assert la_plugin.detect(path, msh[:64], len(msh))
    (scene,) = la_plugin.extract(msh, path, src)
    assert scene.warnings == [] and len(scene.primitives) == 1
    # the shape "!xHl" of the TAR comes from the level's _Art.cpt bundle, one container over
    assert scene.materials[0].texture == "!xHl"
    assert tuple(scene.textures["!xHl"][0, 0]) == (0, 0, 255, 255)
    path = "files/DATA/1/1_1/comp.viv/1_1_Art_c0.cpt"
    assert la_plugin.detect(path, cpt[:64], len(cpt))
    scenes = la_plugin.extract(cpt, path, src)
    assert [len(s.primitives) for s in scenes] == [1, 1]
    np.testing.assert_allclose(scenes[0].primitives[0].positions[0], [10, 20, 30])
    # the art file alone carries textures, not geometry
    assert la_plugin.extract(art, "files/DATA/1/1_1/level.viv/1_1_Art.cpt", src) == []
    # the complete .o objects go through the EAGL plugin itself
    path = "files/DATA/1/1_1/level.viv/Head_GEO.mesh.o"
    assert eagl_plugin.detect(path, files[path][:64], len(files[path]))
    (scene,) = eagl_plugin.extract(files[path], path, src)
    assert len(scene.primitives) == 1
