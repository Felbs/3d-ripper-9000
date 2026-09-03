"""High Voltage Software ``GGG`` models (``ISVHGGG``) - The Grim Adventures of Billy & Mandy,
Codename: Kids Next Door.  Members of ``FSTA`` ``.jam`` archives.  Big-endian.

The ``.GMS`` files beside them, once taken for the models because their payload had entropy
7.7, are DSP-ADPCM sound: 99.8% of their 8-byte frames open with a valid predictor/scale byte.
The geometry was in the "uncompressed, quantised" file all along.

  +0    "ISVH" "GGG\\0", u32 version (0x00020008), u32 file size
  +0x18 u32 header block size H - the payload starts at 0x60 + H; the vertex arrays at
        0x60 + H + the block size at +0x44
  +0x20 u32 node count, u32 material name block size M
  +0x2c u32 G - geometry header at 0x60 + G
  +0x44 u32 size of a node/instance block that precedes the vertex arrays (0 on most)
  +0x4c u32 display-list region offset from the payload start
  0x60  material names, 16 bytes each (M / 16 of them; Maya material names like HSout1L4)
  0x60+M   a flat node tree up to the geometry header: node = u32 mesh count, u32, u32,
           char name[12], followed by that many mesh records of 48 bytes:
             u32 0, i32 -1, u32 vertex base, u32 list base, u32 list count, u16 1,
             u16 vertex count, u16 0x21, u16 material, u16 triangles, u16 1, u32 flags
             (top byte: a bone / draw-group index on skinned models),
             u16 vertex base, u16 kind (0xb201 / 0xb301), u16 attribute count,
             u16 list count, u32 list bytes
  0x60+G   geometry header: u32 0x40, u32 total vertices, f32[3] (bounds, unused here),
             u32 0x1200, u32 attribute count, u32 4, u32 attribute mask, u32, u32,
             u32 (byte 0 = ?), u32, u32 whose top half is the POSITION FRACTION BITS,
             u32, u32, u32, u32, then at +0x44 seven array starts (-1 = absent):
             [?, normals, texcoords, bone indices, colours, ?, display lists]

Arrays are packed in that order after the positions (s16 xyz, 2^frac units): normals s8 xyz
(/64), texcoords s16 st (/16384), bone index u8, colours RGBA8.  Attribute mask bits:
0x80 position, 0x800 normal, 0x8000 texcoord, 0x2000 colour, 0x200 bone index (per vertex,
not in the display list).

Each mesh owns ``list bytes`` of the display-list region, its strip starting at the next
32-byte boundary: opcode 0x9c, u16 count, then per vertex one big-endian u16 index per
attribute (position, normal, colour, texcoord order), 0-based within the mesh's own vertex
range; skinned meshes (attribute word 0x02xx) lead each vertex with a u8 matrix index.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"ISVHGGG\0"
NAME_LEN = 16
NODE_SIZE = 24
MESH_SIZE = 48
MESH_FMT = ">IiIIIHHHHHHIHHHHI"
GEOM_FMT = ">IIfffIIII"
ARRAY_SLOTS = 7
SLOT_NRM, SLOT_TEX, SLOT_BONE, SLOT_CLR, SLOT_DL = 1, 2, 3, 4, 6
BIT_POS, BIT_NRM, BIT_TEX, BIT_CLR, BIT_BONE = 0x80, 0x800, 0x8000, 0x2000, 0x200
STRIP = 0x98
UV_FRAC = 14
NRM_SCALE = 64.0


class GggError(ValueError):
    pass


@dataclass
class Mesh:
    vertex_base: int
    vertex_count: int
    material: int
    triangles: int
    attrs: int
    list_count: int
    list_bytes: int
    skinned: bool  # each strip vertex starts with a u8 matrix index
    node: int
    group: int  # top byte of the flags word - a bone / draw-group index on skinned models


@dataclass
class Model:
    materials: list[str]
    nodes: list[str]
    meshes: list[Mesh]
    total_vertices: int
    mask: int
    frac: int
    payload: int  # where the vertex arrays begin (after any leading node block)
    starts: list[int] = field(default_factory=list)
    lists: int = 0  # where the display-list region begins


def is_ggg(head: bytes) -> bool:
    return head[:8] == MAGIC and len(head) >= 16


def parse(data: bytes) -> Model:
    if not is_ggg(data[:0x60]):
        raise GggError("not a GGG model")
    size = struct.unpack_from(">I", data, 12)[0]
    hdr = struct.unpack_from(">I", data, 0x18)[0]
    nnodes, mblock = struct.unpack_from(">II", data, 0x20)
    goff = struct.unpack_from(">I", data, 0x2C)[0]
    block = struct.unpack_from(">I", data, 0x44)[0]
    dl_off = struct.unpack_from(">I", data, 0x4C)[0]
    payload = 0x60 + hdr
    gh = 0x60 + goff
    if not (0x60 <= payload <= len(data) and gh + 0x60 <= payload):
        raise GggError("GGG header offsets run past the file")
    materials = [
        data[0x60 + i * NAME_LEN : 0x60 + (i + 1) * NAME_LEN].split(b"\0")[0].decode("latin-1")
        for i in range(mblock // NAME_LEN)
    ]
    p = 0x60 + mblock
    nodes: list[str] = []
    meshes: list[Mesh] = []
    # a flat tree: node header, then that node's mesh records, then the next node
    while p + NODE_SIZE <= gh and len(nodes) < 1 << 16:
        count = struct.unpack_from(">I", data, p)[0]
        name = data[p + 12 : p + NODE_SIZE].split(b"\0")[0].decode("latin-1")
        nodes.append(name)
        p += NODE_SIZE
        if p + count * MESH_SIZE > gh:
            raise GggError("GGG node claims more meshes than fit before the geometry header")
        for _ in range(count):
            f = struct.unpack_from(MESH_FMT, data, p)
            meshes.append(Mesh(f[2], f[6], f[8], f[9], f[14] & 0xFF, f[4], f[16], bool(f[14] & 0x200), len(nodes) - 1, f[11] >> 24))
            p += MESH_SIZE
    if p != gh:
        raise GggError("GGG node tree does not end at the geometry header")
    _z, total, _cx, _cy, _cz, _k, _attrs, _four, mask = struct.unpack_from(GEOM_FMT, data, gh)
    frac = struct.unpack_from(">I", data, gh + 0x34)[0] >> 16
    starts = list(struct.unpack_from(">7i", data, gh + 0x44))
    base = payload + block
    if total * 6 > len(data) - base or payload + dl_off > len(data):
        raise GggError("GGG declares more vertices than the file holds")
    return Model(materials, nodes, meshes, total, mask, frac, base, starts, payload + dl_off)


def _start(model: Model, slot: int) -> int | None:
    v = model.starts[slot]
    return None if v < 0 else model.payload + v


def arrays(data: bytes, model: Model) -> dict[str, np.ndarray]:
    n = model.total_vertices
    out: dict[str, np.ndarray] = {}
    pos = np.frombuffer(data, dtype=">i2", count=n * 3, offset=model.payload).reshape(n, 3)
    out["pos"] = pos.astype(np.float32) / float(1 << model.frac)
    at = _start(model, SLOT_NRM)
    if model.mask & BIT_NRM and at is not None and at + n * 3 <= len(data):
        out["nrm"] = np.frombuffer(data, dtype=np.int8, count=n * 3, offset=at).reshape(n, 3).astype(np.float32) / NRM_SCALE
    at = _start(model, SLOT_TEX)
    if model.mask & BIT_TEX and at is not None and at + n * 4 <= len(data):
        uv = np.frombuffer(data, dtype=">i2", count=n * 2, offset=at).reshape(n, 2).astype(np.float32)
        out["uv"] = uv / float(1 << UV_FRAC)
    at = _start(model, SLOT_CLR)
    if model.mask & BIT_CLR and at is not None and at + n * 4 <= len(data):
        out["clr"] = np.frombuffer(data, dtype=np.uint8, count=n * 4, offset=at).reshape(n, 4).copy()
    at = _start(model, SLOT_BONE)
    if model.mask & BIT_BONE and at is not None and at + n <= len(data):
        out["bone"] = np.frombuffer(data, dtype=np.uint8, count=n, offset=at).copy()
    return out


def _order(mask: int) -> list[str]:
    """Attribute order of a display-list vertex - GX order over the attributes present."""
    keys = ["pos"]
    if mask & BIT_NRM:
        keys.append("nrm")
    if mask & BIT_CLR:
        keys.append("clr")
    if mask & BIT_TEX:
        keys.append("uv")
    return keys


@dataclass
class MeshData:
    material: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None


def meshes(data: bytes, model: Model, skipped: list[Mesh] | None = None) -> list[MeshData]:
    """Every mesh that reads; meshes whose strips index past the arrays go to ``skipped``."""
    if skipped is None:
        skipped = []
    arr = arrays(data, model)
    keys = _order(model.mask)
    p = model.lists
    out = []
    for m in model.meshes:
        # strips sit at 32-byte boundaries in record order, but not back to back: skinned
        # models and multi-node models put other data (skin tables, node blocks) between
        # them, so find the next boundary that opens with this mesh's strip
        width = 2 * m.attrs + (1 if m.skinned else 0)
        p = (p + 31) // 32 * 32
        while p + 3 <= len(data):
            op = data[p]
            count = struct.unpack_from(">H", data, p + 1)[0]
            if (op & 0xF8) == STRIP and count == m.list_count and p + 3 + count * width <= len(data):
                break
            p += 32
        else:
            raise GggError(f"strip of {m.list_count} vertices not found")
        raw = data[p + 3 : p + 3 + count * width]
        p += 3 + count * width
        if m.attrs != len(keys):
            raise GggError(f"mesh has {m.attrs} attributes against {len(keys)} in the mask")
        if m.skinned:
            raw = bytes(np.frombuffer(raw, dtype=np.uint8).reshape(count, width)[:, 1:])
        idx = np.frombuffer(raw, dtype=">u2").reshape(count, m.attrs)
        if count and idx.max() + m.vertex_base >= model.total_vertices:
            # skinned bosses (Cerberus) base some meshes past the arrays - a per-bone
            # vertex block we do not follow yet; leave those out rather than misread them
            skipped.append(m)
            continue
        # a single strip per mesh; degenerate triangles are the encoder's own
        tri = []
        for i in range(count - 2):
            a, b, c = i, i + 1, i + 2
            tri.append((a, b, c) if i % 2 == 0 else (b, a, c))
        base = m.vertex_base
        cols = {k: idx[:, j] + base for j, k in enumerate(keys)}
        keep = [t for t in tri if len({t[0], t[1], t[2]}) == 3]
        if not keep:
            continue
        tris = np.asarray(keep, dtype=np.uint32)
        # drop triangles whose three corners share a position index (degenerates)
        pidx = cols["pos"]
        good = ~((pidx[tris[:, 0]] == pidx[tris[:, 1]]) | (pidx[tris[:, 1]] == pidx[tris[:, 2]]) | (pidx[tris[:, 0]] == pidx[tris[:, 2]]))
        tris = tris[good]
        if not len(tris):
            continue
        out.append(
            MeshData(
                material=m.material,
                positions=arr["pos"][cols["pos"]],
                indices=tris.reshape(-1),
                normals=arr["nrm"][cols["nrm"]] if "nrm" in cols and "nrm" in arr else None,
                uvs=arr["uv"][cols["uv"]] if "uv" in cols and "uv" in arr else None,
                colors=arr["clr"][cols["clr"]] if "clr" in cols and "clr" in arr else None,
            )
        )
    return out
