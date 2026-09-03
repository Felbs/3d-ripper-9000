"""Point of View's engine on GameCube (Smashing Drive): ``PHM`` models and ``TIM`` textures
inside the ``.wad`` records (gcrip.formats.toc_wad hands them out as ``NAME.PHM`` /
``NAME.TIM``).

Read from the shipped ``smash.elf``, which carries DWARF 1: ``s_model`` (256 bytes) is the
file itself, every pointer a file offset (``ModelRemapHeader`` adds the base to each)::

    s_model    +0x08 u16 vertex flags, u16 vertex size (44); +0x0c f32 radius; +0x10 centre,
               +0x20 min, +0x30 max (4 f32 each); +0x40 vertices, +0x44 vertex list;
               +0x58 normals, +0x5c list; +0x60 materials, +0x64 list (s_draw_material,
               144: 4 colours, f32 shininess, u32 flags, i32 maps[15] = texture-def
               indices); +0x6c bones, +0x70 list (s_model_bone, 96: char[16] name, f32[16]
               local matrix, i32 parent, sibling, child, mesh); +0x74 meshes, +0x78 list of
               pointers to s_model_mesh (80: centre / min / max, u32 flags, f32 radius, u32
               polygons, ptr index list, u32 collision faces, ptr, ptr commands);
               +0xac texture defs, +0xb0 list (s_texture_def, 20: char[16] name, ptr)
    vertex     s_model_vertex (44): f32 u, v; f32[4] coord; f32[4] normal; u32 RGBA
    commands   s_model_command (8): u8 type, u8 parm8, u16 parm16, u32 parm32 - 1 selects
               material parm8, 4 draws a triangle strip of parm32 + 2 indices starting at
               index parm16 of the mesh's u32 index list (fans come as strips with the hub
               repeated: degenerate triangles), 0 ends the list

``TIM`` (the type tag of the wad record): 64-byte ``s_texture_header`` records, the first
carrying the count at +0 - u16 flags at +4 (low nibble of byte 5 is the GX format), u16
width, height, depth, u32 image bytes, u32 CLUT entries, ptr image, ptr CLUT, u32 CLUT
format - followed by the tiles and palettes (``TextureLoad``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

VERTEX = 44
MATERIAL = 144
BONE = 96
MESH = 80
TEXDEF = 20
CMD_MATERIAL = 1
CMD_STRIP = 4
MAX_COUNT = 1 << 20


class PovError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def is_model(head: bytes, size: int) -> bool:
    """A POV model: no magic, vertex records of 44 bytes and a vertex list inside the file."""
    if len(head) < 0x40 or size < 0x100:
        return False
    if any(head[:8]):
        return False
    vflags, vsize = struct.unpack_from(">HH", head, 8)
    radius = struct.unpack_from(">f", head, 12)[0]
    lo = struct.unpack_from(">3f", head, 0x20)
    hi = struct.unpack_from(">3f", head, 0x30)
    return (
        vsize == VERTEX
        and vflags < 0x100
        and 0 <= radius < 1e7
        and all(abs(x) < 1e7 for x in lo + hi)
        and all(a <= b for a, b in zip(lo, hi, strict=True))
    )


@dataclass
class Mesh:
    name: str
    triangles: np.ndarray  # (T,3) into the model's vertices
    materials: np.ndarray  # (T,) material index per triangle


@dataclass
class Bone:
    name: str
    matrix: np.ndarray
    parent: int
    mesh: int


@dataclass
class Model:
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray
    materials: list[list[int]]  # texture-def indices a material maps to
    texture_defs: list[str]
    meshes: list[Mesh]
    bones: list[Bone]
    warnings: list[str] = field(default_factory=list)


def _cstr(b: bytes, at: int, n: int = 16) -> str:
    return b[at : at + n].split(b"\0")[0].decode("latin-1", "replace")


def parse(b: bytes) -> Model:
    if not is_model(b[:0x48], len(b)):
        raise PovError("not a POV model")
    w = struct.unpack_from(">64I", b, 0)
    nv, pv = w[0x40 // 4], w[0x44 // 4]
    nmat, pmat = w[0x60 // 4], w[0x64 // 4]
    nbone, pbone = w[0x6C // 4], w[0x70 // 4]
    nmesh, pmesh = w[0x74 // 4], w[0x78 // 4]
    ntex, ptex = w[0xAC // 4], w[0xB0 // 4]
    if pv + nv * VERTEX > len(b):
        raise PovError("vertex list past the file")
    v = np.frombuffer(b, ">f4", nv * 11, pv).reshape(nv, 11)
    colors = np.frombuffer(b, np.uint8, nv * VERTEX, pv).reshape(nv, VERTEX)[:, 40:44].copy()
    warn: list[str] = []
    texdefs = []
    for i in range(min(ntex, MAX_COUNT)):
        o = ptex + TEXDEF * i
        if o + TEXDEF > len(b):
            break
        texdefs.append(_cstr(b, o))
    materials = []
    for i in range(min(nmat, MAX_COUNT)):
        o = pmat + MATERIAL * i
        if o + MATERIAL > len(b):
            break
        maps = struct.unpack_from(">15i", b, o + 72)
        materials.append([m for m in maps if m >= 0])
    bones = []
    for i in range(min(nbone, MAX_COUNT)):
        o = pbone + BONE * i
        if o + BONE > len(b):
            break
        m = np.frombuffer(b, ">f4", 16, o + 16).reshape(4, 4).copy()
        parent, _sib, _child, mesh = struct.unpack_from(">4i", b, o + 80)
        bones.append(Bone(_cstr(b, o), m, parent, mesh))
    meshes = []
    for i in range(min(nmesh, MAX_COUNT)):
        at = pmesh + 4 * i
        if at + 4 > len(b):
            break
        mp = _u32(b, at)
        if mp + MESH > len(b):
            warn.append(f"mesh {i}: record past the file")
            continue
        _flags, _radius, npoly, plist, _ncf, _pcf, cmds = struct.unpack_from(">IfIIIII", b, mp + 48)
        avail = (len(b) - plist) // 4 if plist < len(b) else 0
        idx = np.frombuffer(b, ">u4", min(npoly * 4, avail), plist)
        tris = []
        mats = []
        material = 0
        p = cmds
        while p + 8 <= len(b):
            t, p8, p16, p32 = struct.unpack_from(">BBHI", b, p)
            p += 8
            if t == 0:
                break
            if t == CMD_MATERIAL:
                material = p8
            elif t == CMD_STRIP:
                seg = idx[p16 : p16 + p32 + 2].astype(np.int64)
                if len(seg) < 3:
                    continue
                k = np.arange(len(seg) - 2)
                a = seg[k]
                bb = np.where(k % 2 == 0, seg[k + 1], seg[k + 2])
                c = np.where(k % 2 == 0, seg[k + 2], seg[k + 1])
                t3 = np.stack([a, bb, c], 1)
                tris.append(t3)
                mats.append(np.full(len(t3), material, np.int64))
        if not tris:
            warn.append(f"mesh {i}: no strips")
            continue
        t3 = np.concatenate(tris)
        m3 = np.concatenate(mats)
        keep = (t3[:, 0] != t3[:, 1]) & (t3[:, 1] != t3[:, 2]) & (t3[:, 0] != t3[:, 2])
        keep &= t3.max(1) < nv
        name = next((bone.name for bone in bones if bone.mesh == i), f"mesh_{i}")
        meshes.append(Mesh(name, t3[keep], m3[keep]))
    return Model(
        np.ascontiguousarray(v[:, 2:5], dtype=np.float32),
        np.ascontiguousarray(v[:, 6:9], dtype=np.float32),
        np.ascontiguousarray(v[:, 0:2], dtype=np.float32),
        colors,
        materials,
        texdefs,
        meshes,
        bones,
        warn,
    )


# ---------------------------------------------------------------------------
# TIM textures
# ---------------------------------------------------------------------------

TEXTURE_HEADER = 64


def is_tim(head: bytes, size: int) -> bool:
    if len(head) < 24 or size < TEXTURE_HEADER:
        return False
    n = _u32(head, 0)
    if not 0 < n <= 256:
        return False
    fmt = head[5] & 15
    width, height = struct.unpack_from(">HH", head, 6)
    return fmt in gx_texture.TILE_DIMS and 0 < width <= 1024 and 0 < height <= 1024


@dataclass
class Texture:
    width: int
    height: int
    fmt: int
    rgba: np.ndarray | None
    error: str | None = None


def parse_tim(b: bytes) -> list[Texture]:
    n = _u32(b, 0)
    out = []
    for i in range(min(n, 256)):
        h = TEXTURE_HEADER * i  # the count shares the first header's +0
        if h + TEXTURE_HEADER > len(b):
            break
        fmt = b[h + 5] & 15
        width, height, _depth, image_size, clut_entries, image, clut, clut_fmt = struct.unpack_from(
            ">HHHIIIII", b, h + 6
        )
        tex = Texture(width, height, fmt, None)
        try:
            need = gx_texture.encoded_size(fmt, width, height)
            if image + need > len(b):
                raise PovError("image past the file")
            palette = None
            if fmt in (8, 9, 10):
                count = clut_entries or (16 if fmt == 8 else 256)
                palette = gx_texture.decode_palette(
                    min(clut_fmt, 2), b[clut : clut + 2 * count], count
                )
            tex.rgba = gx_texture.decode(fmt, width, height, b[image : image + need], palette)
        except Exception as e:  # noqa: BLE001 - one bad texture, the rest decode
            tex.error = str(e)
        out.append(tex)
    return out
