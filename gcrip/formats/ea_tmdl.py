"""EA Tiburon ``TMdl`` models (``.ea3``) on GameCube - Madden NFL, NCAA Football, NFL Street,
NASCAR Thunder.  They sit in TERF archives, most of them behind the LZH1 codec (``ea_lzh1``).

All offsets in the file are absolute.  Big-endian throughout.

  TMdl header:  "TMdl", u32 file size, u16 section count, u16 header size (16), u8[4] version
                (10 10 06 00 on Madden 06), then section table entries of 16 bytes:
                tag, u32 offset, u32 size, u32 flags.
  Info          the model's name ("EAG_DUSK.ea3"), NUL-terminated.
  Geom          u32 mesh table, u32 mesh count, u32 attribute table, u32 attribute count,
                u32 attribute mask, u32 extra (a crowd/billboard index block on stadiums,
                not read).
                mesh (24 bytes):  u32 display list, u16 display list size / 32, u16 material,
                  u16 0xffff, u16 triangles, u16 vertices, u16 first attribute, u8 attribute
                  count, u8[3] pad.
                attribute (12 bytes):  u32 array, u16 count, u8 GX attribute (9 POS, 10 NRM,
                  11 CLR0, 13 TEX0 ...), u8 stride, u8 component count, u8 component type,
                  u8 fraction bits, u8 index type (2 = u8 indices, 3 = u16).
                The display list is GX: opcode (0x80 quads, 0x90 triangles, 0x98 strip,
                0xa0 fan), u16 vertex count, then one index per attribute per vertex, in the
                mesh's attribute order.  Padded with zeros to the declared size.
  Matl          u32 count, u32 record offset[count]; record: u32 name, u32 shader name
                ("OnePass", "Flat"), u16 texture count, u16 0, u32 texture name, ... - the
                texture name is the 15-character key into the Text pack's name block.
  Text          one MMAP whose "levels" are separate textures, each with a 16-byte name in the
                MMAP name block (``ea_terf.mmap_pack``).
  Swap / Extn / Lite / Loca   swap chains, extents, lights, locators - not read.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"TMdl"
MESH_SIZE = 24
ATTR_SIZE = 12
INDEX_U8 = 2
INDEX_U16 = 3
DL_UNIT = 32

VA_POS = 9
VA_NRM = 10
VA_CLR0 = 11
VA_CLR1 = 12
VA_TEX0 = 13

# GX component types for positions, normals and texture coordinates
_COMP = {0: ("u1", 1), 1: ("i1", 1), 2: (">u2", 2), 3: (">i2", 2), 4: (">f4", 4)}
# GX colour formats: bytes per colour
_COLOR_BYTES = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}


class TmdlError(ValueError):
    pass


@dataclass
class Attr:
    array: int
    count: int
    va: int
    stride: int
    comps: int
    ctype: int
    frac: int
    index: int


@dataclass
class Mesh:
    display_list: int
    dl_size: int
    material: int
    triangles: int
    vertices: int
    first_attr: int
    attr_count: int


@dataclass
class Material:
    name: str
    shader: str
    texture: str | None


@dataclass
class Model:
    name: str
    sections: dict[bytes, tuple[int, int, int]] = field(
        default_factory=dict
    )  # tag -> offset, size, flags
    meshes: list[Mesh] = field(default_factory=list)
    attrs: list[Attr] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    texture_pack: bytes | None = None


def is_tmdl(head: bytes) -> bool:
    return len(head) >= 16 and head[:4] == MAGIC


def _cstr(data: bytes, off: int, limit: int = 128) -> str:
    if not 0 <= off < len(data):
        return ""
    end = data.find(b"\0", off, off + limit)
    return data[off : end if end >= 0 else off + limit].decode("latin-1")


def parse(data: bytes) -> Model:
    if not is_tmdl(data):
        raise TmdlError("not a TMdl model")
    count, hdr = struct.unpack_from(">HH", data, 8)
    if hdr < 16 or hdr + count * 16 > len(data):
        raise TmdlError("TMdl section table runs past the file")
    model = Model(name="")
    for i in range(count):
        tag = data[hdr + 16 * i : hdr + 16 * i + 4]
        off, size, flags = struct.unpack_from(">III", data, hdr + 16 * i + 4)
        if off + size > len(data):
            raise TmdlError(f"TMdl section {tag!r} runs past the file")
        model.sections[tag] = (off, size, flags)
    if b"Info" in model.sections:
        off, size, _ = model.sections[b"Info"]
        model.name = _cstr(data, off, size)
    if b"Geom" in model.sections:
        _parse_geom(data, model)
    if b"Matl" in model.sections:
        _parse_matl(data, model)
    if b"Text" in model.sections:
        off, size, _ = model.sections[b"Text"]
        model.texture_pack = data[off : off + size]
    return model


def _parse_geom(data: bytes, model: Model) -> None:
    off, size, _ = model.sections[b"Geom"]
    if size < 24:
        return
    mesh_off, mesh_n, attr_off, attr_n, _mask, _extra = struct.unpack_from(">6I", data, off)
    if mesh_off + mesh_n * MESH_SIZE > len(data) or attr_off + attr_n * ATTR_SIZE > len(data):
        raise TmdlError("Geom tables run past the file")
    for i in range(attr_n):
        model.attrs.append(Attr(*struct.unpack_from(">IHBBBBBB", data, attr_off + i * ATTR_SIZE)))
    for i in range(mesh_n):
        dl, units, mat, _sentinel, tris, verts, first, na = struct.unpack_from(
            ">IHHHHHHB", data, mesh_off + i * MESH_SIZE
        )
        model.meshes.append(Mesh(dl, units * DL_UNIT, mat, tris, verts, first, na))


def _parse_matl(data: bytes, model: Model) -> None:
    off, size, _ = model.sections[b"Matl"]
    if size < 4:
        return
    count = struct.unpack_from(">I", data, off)[0]
    if count > 4096 or off + 4 + count * 4 > len(data):
        raise TmdlError("Matl table runs past the file")
    for i in range(count):
        rec = struct.unpack_from(">I", data, off + 4 + i * 4)[0]
        if rec + 16 > len(data):
            raise TmdlError("Matl record runs past the file")
        name_off, shader_off, ntex, _z, tex_off = struct.unpack_from(">IIHHI", data, rec)
        texture = _cstr(data, tex_off) if ntex and tex_off else None
        model.materials.append(
            Material(_cstr(data, name_off), _cstr(data, shader_off), texture or None)
        )


# ---------------------------------------------------------------- vertex arrays


def array(data: bytes, attr: Attr) -> np.ndarray:
    """Decode one attribute array to float32 (positions/normals/uvs) or uint8 RGBA (colours)."""
    end = attr.array + attr.count * attr.stride
    if attr.count == 0 or end > len(data) or attr.stride == 0:
        raise TmdlError("attribute array runs past the file")
    raw = data[attr.array : end]
    if attr.va in (VA_CLR0, VA_CLR1):
        return _colors(raw, attr)
    if attr.ctype not in _COMP:
        raise TmdlError(f"attribute component type {attr.ctype} unknown")
    dtype, width = _COMP[attr.ctype]
    if attr.va == VA_POS:
        n = 3 if attr.comps else 2
    elif attr.va == VA_NRM:
        n = 3
    elif attr.va >= VA_TEX0:
        n = 2 if attr.comps else 1
    else:
        raise TmdlError(f"attribute {attr.va} unknown")
    if n * width > attr.stride:
        raise TmdlError("attribute stride smaller than its components")
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(attr.count, attr.stride)[:, : n * width]
    vals = np.ascontiguousarray(rows).view(dtype).reshape(attr.count, n).astype(np.float32)
    if attr.ctype != 4 and attr.frac:
        vals /= float(1 << attr.frac)
    if n == 2 and attr.va == VA_POS:
        vals = np.concatenate([vals, np.zeros((attr.count, 1), np.float32)], axis=1)
    if n == 1:
        vals = np.concatenate([vals, np.zeros((attr.count, 1), np.float32)], axis=1)
    return vals


def _colors(raw: bytes, attr: Attr) -> np.ndarray:
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(attr.count, attr.stride)
    out = np.full((attr.count, 4), 255, np.uint8)
    t = attr.ctype
    if t == 5:  # RGBA8
        out[:] = rows[:, :4]
    elif t in (1, 2):  # RGB8 / RGBX8
        out[:, :3] = rows[:, :3]
    elif t == 0:  # RGB565
        v = rows[:, :2].copy().view(">u2").reshape(-1).astype(np.uint32)
        out[:, 0] = ((v >> 11) & 31) * 255 // 31
        out[:, 1] = ((v >> 5) & 63) * 255 // 63
        out[:, 2] = (v & 31) * 255 // 31
    elif t == 3:  # RGBA4
        v = rows[:, :2].copy().view(">u2").reshape(-1).astype(np.uint32)
        for k in range(4):
            out[:, k] = ((v >> (12 - 4 * k)) & 15) * 17
    elif t == 4:  # RGBA6
        v = rows[:, :3].astype(np.uint32)
        packed = (v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]
        for k in range(4):
            out[:, k] = ((packed >> (18 - 6 * k)) & 63) * 255 // 63
    else:
        raise TmdlError(f"colour type {t} unknown")
    return out


# ---------------------------------------------------------------- display lists


def _prim_triangles(op: int, verts: list[int]) -> list[tuple[int, int, int]]:
    n = len(verts)
    if op == 0x90:
        return [(verts[i], verts[i + 1], verts[i + 2]) for i in range(0, n - n % 3, 3)]
    if op == 0x98:
        out = []
        for i in range(n - 2):
            a, b, c = verts[i], verts[i + 1], verts[i + 2]
            out.append((a, b, c) if i % 2 == 0 else (b, a, c))
        return out
    if op == 0xA0:
        return [(verts[0], verts[i], verts[i + 1]) for i in range(1, n - 1)]
    if op == 0x80:
        out = []
        for i in range(0, n - n % 4, 4):
            a, b, c, d = verts[i : i + 4]
            out += [(a, b, c), (a, c, d)]
        return out
    return []


INDEXED_LOADS = {0x20, 0x28, 0x30, 0x38}


def draw(data: bytes, mesh: Mesh, attrs: list[Attr]) -> list[tuple[int, list[tuple[int, ...]]]]:
    """[(opcode, [index tuple per vertex])] for one mesh's display list."""
    widths = [2 if a.index == INDEX_U16 else 1 for a in attrs]
    vsize = sum(widths)
    p = mesh.display_list
    end = min(p + mesh.dl_size, len(data))
    if vsize == 0 or p >= len(data):
        raise TmdlError("mesh without attributes")
    out = []
    skinned = False
    while p + 3 <= end:
        op = data[p]
        if op == 0:
            break
        if op in INDEXED_LOADS:
            # GX_CMD_LOAD_INDX_A..D: a skinned player model loads its bone matrices from
            # the indexed arrays before each strip (u16 index, u16 size / address), and
            # its vertices then lead with a matrix-index byte the attribute table omits
            p += 5
            skinned = True
            continue
        if op & 0x80 == 0 or (op & 0x78) > 0x38:
            raise TmdlError(f"display list opcode {op:#x} unknown")
        count = struct.unpack_from(">H", data, p + 1)[0]
        p += 3
        stride = vsize + (1 if skinned else 0)
        if p + count * stride > end:
            raise TmdlError("display list primitive runs past the mesh")
        verts = []
        for _ in range(count):
            idx = []
            if skinned:
                p += 1
            for w in widths:
                idx.append(data[p] if w == 1 else struct.unpack_from(">H", data, p)[0])
                p += w
            verts.append(tuple(idx))
        out.append((op & 0xF8, verts))
    return out


@dataclass
class MeshData:
    material: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None


def mesh_data(data: bytes, model: Model, mesh: Mesh) -> MeshData:
    attrs = model.attrs[mesh.first_attr : mesh.first_attr + mesh.attr_count]
    if len(attrs) != mesh.attr_count:
        raise TmdlError("mesh attributes run past the attribute table")
    arrays = [array(data, a) for a in attrs]
    slots = {a.va: k for k, a in enumerate(attrs)}
    if VA_POS not in slots:
        raise TmdlError("mesh without positions")
    prims = draw(data, mesh, attrs)
    # de-duplicate on the full index tuple so each glTF vertex is one combination
    keys: dict[tuple[int, ...], int] = {}
    tris: list[tuple[int, int, int]] = []
    for op, verts in prims:
        local = []
        for v in verts:
            k = keys.get(v)
            if k is None:
                k = keys[v] = len(keys)
            local.append(k)
        tris += _prim_triangles(op, local)
    if not tris:
        raise TmdlError("mesh draws nothing")
    order = list(keys)

    def gather(va: int) -> np.ndarray | None:
        k = slots.get(va)
        if k is None:
            return None
        arr = arrays[k]
        idx = np.array([v[k] for v in order], dtype=np.int64)
        if idx.max() >= len(arr):
            if va == VA_CLR0 and len(arr):
                # the shadow-only rigs index 0xff into a three-entry table: no colour, white
                out = np.full((len(idx), arr.shape[1]), 255, arr.dtype)
                ok = idx < len(arr)
                out[ok] = arr[idx[ok]]
                return out
            raise TmdlError(f"attribute {va} index past its array")
        return arr[idx]

    pos = gather(VA_POS)
    return MeshData(
        material=mesh.material,
        positions=np.ascontiguousarray(pos, dtype=np.float32),
        indices=np.asarray(tris, dtype=np.uint32).reshape(-1),
        normals=gather(VA_NRM),
        uvs=gather(VA_TEX0),
        colors=gather(VA_CLR0),
    )
