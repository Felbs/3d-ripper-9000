"""Blitz Games (BlitzTech) actors - the model resources inside ``.gcp`` packs (Bratz, Pac-Man
World 3, Fairly OddParents, SpongeBob: Creature from the Krusty Krab, Zapper, ...).

Layouts are the engine's own, read from the DWARF in Bratz: Rock Angelz's ``Bratz_NGC_M.elf``
(``_TBActor``, ``_TBActorNode``, ``_TBMesh``, ``_TBSoftSkin``, ``_TBMeshBatch``,
``_TBMeshPrim``, ``_TBPrimVertex``).  Big-endian; every pointer is an offset from the start
of the resource (``bFixupMeshData`` turns them into pointers at load time).

  _TBActor (244)     +0 _TBResourceInfo(32), +32 _TBSoftSkin(128), +160 rootNode,
                     +164 flags, +188 maxRadius, +192 bbox f32[6], +216 matrixPaletteSize,
                     +217 vertexType, +241 noofNodes
  _TBActorNode (308) +0 position track (f32 base xyz), +32 scale track, +64 orientation
                     track (f32 base xyzw at +80), +112 union { _TBMesh } for type 2,
                     +256 next, +264 parent, +268 children, +272 type, +304 name
  _TBMesh (112)      +0 noofVertices, +4 vertices, +8 noofBatches, +12 batches,
                     +16 primitives, +76 flags, +80 positionData, +84 normalData,
                     +88 textureCoordData, +92 colourData, +96 displayList,
                     +100 displayListSize
  _TBSoftSkin (128)  the same fields at +0..+16, then +48 bonesPerVertex, +56 displayList,
                     +60 displayListSize, +64 positionData, +68 normalData,
                     +72 textureCoordData, +76 colourData, +80 positions, +84 normals
  _TBMeshBatch (16)  noofPrims, textureCRC1, textureCRC2, flags
  _TBMeshPrim (8)    u8 primType, u8 flags, u16 noofVertices, u16 noofDrawPrims, pad

Two geometry encodings share the structs.  With ``displayList`` set, the mesh is a GX display
list over indexed arrays (positions f32 xyz, normals s8, texcoords f32 st, colours RGBA8);
the per-vertex layout follows ``vertexType``: 16 / 24 are ``u16 pos, u16 nrm, u16 clr,
u16 tex``; 17 is ``u16 pos, u16 nrm, RGBA8 clr0, RGBA8 clr1, u16 tex``; soft-skin types
21 / 22 lead with a u8 matrix index.  With ``displayList`` clear (``vertexType`` 1 / 2, the
lightmapped ``.lmp`` level props), the mesh is a stream of ``_TBPrimVertex`` records
(``x y z nx ny nz rgba u v``, 36 bytes; type 2 adds a lightmap ``u v``, 44 bytes) consumed in
order by the primitive list.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

ACTOR = 244
NODE = 308
MESH = 112
SOFT_AT = 32
ROOT_AT = 160
VERTEX_TYPE_AT = 217
NODE_COUNT_AT = 241
TYPE_MESH = 2
STRIP = 0x98

# display-list vertex layouts: a tuple of ("attr", width); indexed attrs are 2-byte indices,
# "clr_direct" is an RGBA8 written in the list, "mtx" a u8 matrix index
LAYOUTS = {
    8: (("pos", 2), ("nrm", 2), ("clr", 2), ("tex", 2)),
    14: (("pos", 2), ("nrm", 2), ("clr_direct", 4), ("clr1_direct", 4), ("tex", 2)),
    9: (("mtx", 1), ("pos", 2), ("nrm", 2), ("clr", 2), ("tex", 2)),
    15: (("mtx", 1), ("pos", 2), ("nrm", 2), ("clr_direct", 4), ("clr1_direct", 4), ("tex", 2)),
    6: (("pos", 2), ("nrm", 2), ("tex", 2)),
    4: (("pos", 2), ("tex", 2)),
}
PRIM_VERTEX_SIZE = {1: 36, 2: 44}


class ActorError(ValueError):
    pass


@dataclass
class Batch:
    prims: int
    texture1: int
    texture2: int
    flags: int


@dataclass
class MeshData:
    node: str
    texture: int  # CRC of the batch's first texture, 0 if none
    texture2: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    uvs2: np.ndarray | None = None
    colors: np.ndarray | None = None


@dataclass
class Node:
    name: str
    parent: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    kind: int


@dataclass
class Actor:
    vertex_type: int
    bbox: tuple[float, ...]
    nodes: list[Node] = field(default_factory=list)
    meshes: list[MeshData] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_actor(data: bytes) -> bool:
    return len(data) >= ACTOR and data[6] == 1


def _cstr(data: bytes, off: int) -> str:
    if not 0 <= off < len(data):
        return ""
    end = data.find(b"\0", off, off + 128)
    return data[off : end if end >= 0 else off + 128].decode("latin-1")


def _tile(data: bytes, dl: int, size: int) -> list[int]:
    """Strides that tile the display list exactly (NOP bytes between primitives allowed)."""
    out = []
    end = min(dl + size, len(data))
    for stride in range(2, 40):
        p = dl
        prims = 0
        ok = True
        while p < end:
            op = data[p]
            if op == 0:
                p += 1
                continue
            if op & 0x80 == 0 or (op & 0x78) > 0x38:
                ok = False
                break
            count = struct.unpack_from(">H", data, p + 1)[0]
            if count == 0 or p + 3 + count * stride > end:
                ok = False
                break
            p += 3 + count * stride
            prims += 1
        if ok and prims:
            out.append(stride)
    return out


def _prims_to_tris(op: int, verts: list[int]) -> list[tuple[int, int, int]]:
    n = len(verts)
    kind = op & 0xF8
    if kind == 0x90:
        return [(verts[i], verts[i + 1], verts[i + 2]) for i in range(0, n - n % 3, 3)]
    if kind == 0x98:
        return [((verts[i], verts[i + 1], verts[i + 2]) if i % 2 == 0 else (verts[i + 1], verts[i], verts[i + 2])) for i in range(n - 2)]
    if kind == 0xA0:
        return [(verts[0], verts[i], verts[i + 1]) for i in range(1, n - 1)]
    if kind == 0x80:
        out = []
        for i in range(0, n - n % 4, 4):
            a, b, c, d = verts[i : i + 4]
            out += [(a, b, c), (a, c, d)]
        return out
    return []


def _display_list(data: bytes, dl: int, size: int, layout) -> list[tuple[int, list[dict]]]:
    """[(opcode, [vertex attr dict])] over one display list."""
    stride = sum(w for _, w in layout)
    p = dl
    end = min(dl + size, len(data))
    out = []
    while p < end:
        op = data[p]
        if op == 0:
            p += 1
            continue
        count = struct.unpack_from(">H", data, p + 1)[0]
        p += 3
        verts = []
        for _ in range(count):
            v = {}
            q = p
            for name, w in layout:
                if w == 1:
                    v[name] = data[q]
                elif w == 2:
                    v[name] = struct.unpack_from(">H", data, q)[0]
                else:
                    v[name] = data[q : q + 4]
                q += w
            verts.append(v)
            p += stride
        out.append((op, verts))
    return out


def _arrays(data: bytes, pos_at: int, nrm_at: int, tex_at: int, clr_at: int, npos: int, nnrm: int, ntex: int, nclr: int):
    def f32(at, n, k):
        if not at or n <= 0 or at + n * k * 4 > len(data):
            return None
        return np.frombuffer(data, dtype=">f4", count=n * k, offset=at).reshape(n, k).astype(np.float32)

    pos = f32(pos_at, npos, 3)
    nrm = None
    if nrm_at and nnrm > 0 and nrm_at + nnrm * 3 <= len(data):
        nrm = np.frombuffer(data, dtype=np.int8, count=nnrm * 3, offset=nrm_at).reshape(nnrm, 3).astype(np.float32) / 64.0
    tex = f32(tex_at, ntex, 2)
    clr = None
    if clr_at and nclr > 0 and clr_at + nclr * 4 <= len(data):
        clr = np.frombuffer(data, dtype=np.uint8, count=nclr * 4, offset=clr_at).reshape(nclr, 4).copy()
    return pos, nrm, tex, clr


def _batches(data: bytes, at: int, n: int) -> list[Batch]:
    out = []
    for i in range(n):
        if at + 16 * (i + 1) > len(data):
            break
        out.append(Batch(*struct.unpack_from(">4I", data, at + 16 * i)))
    return out


def _dl_meshes(data: bytes, node: str, vertex_type: int, dl: int, dl_size: int, batches: list[Batch], prims_at: int,
               arrays, warnings: list[str]) -> list[MeshData]:
    pos, nrm, tex, clr = arrays
    if pos is None:
        warnings.append(f"{node}: mesh without positions")
        return []
    strides = _tile(data, dl, dl_size)
    layout = None
    for s in strides:
        if s in LAYOUTS:
            layout = LAYOUTS[s]
            break
    if layout is None:
        warnings.append(f"{node}: display list stride {strides} has no known layout")
        return []
    lists = _display_list(data, dl, dl_size, layout)
    # primitives are handed out to batches in order: batch k owns the next batch.prims lists
    out = []
    k = 0
    for b in batches:
        mine = lists[k : k + b.prims]
        k += b.prims
        if not mine:
            continue
        keys: dict[tuple, int] = {}
        tris = []
        for op, verts in mine:
            local = []
            for v in verts:
                key = (v.get("pos"), v.get("nrm"), v.get("tex"), v.get("clr"), v.get("clr_direct"))
                j = keys.get(key)
                if j is None:
                    j = keys[key] = len(keys)
                local.append(j)
            tris += _prims_to_tris(op, local)
        if not tris:
            continue
        order = list(keys)
        pidx = np.array([k_[0] for k_ in order], dtype=np.int64)
        if pidx.max() >= len(pos):
            warnings.append(f"{node}: position index past the array")
            continue
        md = MeshData(node, b.texture1, b.texture2, pos[pidx], np.asarray(tris, dtype=np.uint32).reshape(-1))
        if nrm is not None and all(k_[1] is not None for k_ in order):
            nidx = np.array([k_[1] for k_ in order], dtype=np.int64)
            if nidx.max() < len(nrm):
                md.normals = nrm[nidx]
        if tex is not None and all(k_[2] is not None for k_ in order):
            tidx = np.array([k_[2] for k_ in order], dtype=np.int64)
            if tidx.max() < len(tex):
                md.uvs = tex[tidx]
        if clr is not None and all(k_[3] is not None for k_ in order):
            cidx = np.array([k_[3] for k_ in order], dtype=np.int64)
            if cidx.max() < len(clr):
                md.colors = clr[cidx]
        elif all(k_[4] is not None for k_ in order):
            md.colors = np.array([list(k_[4]) for k_ in order], dtype=np.uint8)
        out.append(md)
    return out


def _stream_meshes(data: bytes, node: str, vertex_type: int, verts_at: int, nverts: int, batches: list[Batch],
                   prims_at: int, warnings: list[str]) -> list[MeshData]:
    size = PRIM_VERTEX_SIZE.get(vertex_type)
    if size is None:
        warnings.append(f"{node}: vertex type {vertex_type} has no stream layout")
        return []
    if verts_at + nverts * size > len(data):
        warnings.append(f"{node}: vertex stream past the resource")
        return []
    rows = np.frombuffer(data, dtype=np.uint8, count=nverts * size, offset=verts_at).reshape(nverts, size)
    pos = np.ascontiguousarray(rows[:, 0:12]).view(">f4").reshape(nverts, 3).astype(np.float32)
    nrm = np.ascontiguousarray(rows[:, 12:24]).view(">f4").reshape(nverts, 3).astype(np.float32)
    clr = np.ascontiguousarray(rows[:, 24:28]).copy()
    uv = np.ascontiguousarray(rows[:, 28:36]).view(">f4").reshape(nverts, 2).astype(np.float32)
    uv2 = np.ascontiguousarray(rows[:, 36:44]).view(">f4").reshape(nverts, 2).astype(np.float32) if size >= 44 else None
    out = []
    v = 0
    p = prims_at
    for b in batches:
        tris = []
        lo = v
        for _ in range(b.prims):
            if p + 8 > len(data):
                break
            ptype, _flags, n, draw = struct.unpack_from(">BBHH", data, p)
            p += 8
            ids = list(range(v, v + n))
            v += n
            if v > nverts:
                warnings.append(f"{node}: primitive stream past the vertices")
                return out
            if draw == n - 2:
                tris += _prims_to_tris(STRIP, ids)
            elif n and draw == n // 3:
                tris += _prims_to_tris(0x90, ids)
            elif n and draw == n // 4 * 2:
                tris += _prims_to_tris(0x80, ids)
            else:
                tris += _prims_to_tris(STRIP, ids)
        if not tris:
            continue
        sel = np.arange(lo, v)
        idx = np.asarray(tris, dtype=np.int64) - lo
        out.append(MeshData(node, b.texture1, b.texture2, pos[sel], idx.astype(np.uint32).reshape(-1), nrm[sel], uv[sel],
                            None if uv2 is None else uv2[sel], clr[sel]))
    return out


def parse(data: bytes) -> Actor:
    if not is_actor(data):
        raise ActorError("not a Blitz actor")
    vertex_type = data[VERTEX_TYPE_AT]
    bbox = struct.unpack_from(">6f", data, 192)
    actor = Actor(vertex_type, bbox)
    warnings = actor.warnings
    # the soft skin, if any
    s = SOFT_AT
    nverts, verts_at, nbatches, batches_at, prims_at = struct.unpack_from(">5I", data, s)
    dl, dl_size = struct.unpack_from(">II", data, s + 56)
    pos_at, nrm_at, tex_at, clr_at, npos, nnrm = struct.unpack_from(">6I", data, s + 64)
    if nverts and dl and dl_size:
        arrays = _arrays(data, pos_at, nrm_at, tex_at, clr_at, npos or nverts, nnrm or nverts, nverts, nverts)
        actor.meshes += _dl_meshes(data, "skin", vertex_type, dl, dl_size, _batches(data, batches_at, nbatches), prims_at, arrays, warnings)
    # the node tree
    root = struct.unpack_from(">I", data, ROOT_AT)[0]
    stack = [(root, -1)]
    seen = set()
    while stack:
        n, parent = stack.pop()
        if n in seen or not 0 < n <= len(data) - NODE:
            continue
        seen.add(n)
        nxt, _prev, _par, children = struct.unpack_from(">4I", data, n + 256)
        kind = data[n + 272]
        name = _cstr(data, struct.unpack_from(">I", data, n + 304)[0]) or f"node_{len(actor.nodes)}"
        position = struct.unpack_from(">3f", data, n)
        scale = struct.unpack_from(">3f", data, n + 32)
        rotation = struct.unpack_from(">4f", data, n + 80)
        index = len(actor.nodes)
        actor.nodes.append(Node(name, parent, position, rotation, scale, kind))
        if kind == TYPE_MESH:
            m = n + 112
            mverts, mverts_at, mbatches, mbatches_at, mprims_at = struct.unpack_from(">5I", data, m)
            mpos, mnrm, mtex, mclr, mdl, mdl_size = struct.unpack_from(">6I", data, m + 80)
            batches = _batches(data, mbatches_at, mbatches)
            if mdl and mdl_size and mverts:
                arrays = _arrays(data, mpos, mnrm, mtex, mclr, mverts, mverts, mverts, mverts)
                actor.meshes += _dl_meshes(data, name, vertex_type, mdl, mdl_size, batches, mprims_at, arrays, warnings)
            elif mverts and mverts_at and mprims_at:
                actor.meshes += _stream_meshes(data, name, vertex_type, mverts_at, mverts, batches, mprims_at, warnings)
        if children:
            stack.append((children, index))
        if nxt:
            stack.append((nxt, parent))
    return actor


# ---------------------------------------------------------------- textures

# _TBTexture (160): +32 xDim, +36 yDim, +40 format, +44 u16 flags, +46 u8 mipLevels,
# +47 u8 noofFrames, +108 palette, +112 frames (the pixel data of frame 0)
TEX_GX = {21: 0xE, 15: 6}  # Blitz format code -> GX texture format
TEX_C8 = {18}  # C8 indices behind a 256-entry RGB5A3 palette
MAX_DIM = 2048


class TextureError(ValueError):
    pass


def is_texture(data: bytes) -> bool:
    return len(data) >= 160 and data[6] == 0


def texture(data: bytes) -> np.ndarray:
    """Frame 0 of a Blitz texture resource as RGBA.  Format 17 (63 of Bratz 500 sampled
    textures, 8 bits a pixel behind a 512-byte block that is not an RGB5A3 palette) is
    still unread and raises."""
    from gcrip.formats import gx_texture as gx

    if not is_texture(data):
        raise TextureError("not a Blitz texture")
    w, h, fmt = struct.unpack_from(">3I", data, 32)
    palette_at, frames_at = struct.unpack_from(">II", data, 108)
    if not (0 < w <= MAX_DIM and 0 < h <= MAX_DIM):
        raise TextureError(f"texture {w}x{h}")
    if fmt in TEX_GX:
        gxf = TEX_GX[fmt]
        need = gx.encoded_size(gxf, w, h)
        if frames_at + need > len(data):
            raise TextureError("pixels past the resource")
        return gx.decode(gxf, w, h, data[frames_at : frames_at + need])
    if fmt in TEX_C8:
        if not palette_at or palette_at + 512 > len(data) or frames_at + w * h > len(data):
            raise TextureError("C8 texture without its palette")
        pal = gx.decode_palette(2, data[palette_at : palette_at + 512], 256)
        return gx.decode(9, w, h, data[frames_at : frames_at + gx.encoded_size(9, w, h)], pal)
    raise TextureError(f"Blitz texture format {fmt} unread")
