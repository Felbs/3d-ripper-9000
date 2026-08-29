"""RenderWare 3.x binary streams (Criterion) as shipped on GameCube discs: chunk reader plus the
Clump (DFF), World (BSP) and Texture Dictionary (TXD) structures. Layouts checked byte-by-byte on
Sonic Heroes (RW 3.3 - 3.5) and SpongeBob SquarePants: Battle for Bikini Bottom (RW 3.4 - 3.5).

Chunk header = (u32 type, u32 size, u32 library id), LITTLE-endian even on GameCube, and so are the
generic structs (frames, materials, atomics, platform-independent geometry, worlds). Only the
platform payloads are big-endian: Native Data PLG (0x510) vertex arrays / GX display lists, the
GameCube skin (Skin PLG wrapped in a Struct, RW >= 3.5) and texture rasters - decoded in rwgc.py.

Library id -> version: 0x0800FFFF = 3.2, 0x0C02FFFF = 3.3, 0x1003FFFF..0x1005FFFF = 3.4.x,
0x1400FFFF = 3.5.  Geometry structs before 3.4 carry three lighting floats after the header;
texture natives before 3.3 use the short GameCube header (see rwgc.parse_txd).

Clump (0x10): Struct(numAtomics[, numLights, numCameras]) FrameList(0x0E: Struct(count,
count x (f32 rot[9], f32 pos[3], u32 parent, u32 flags)) + one Extension per frame holding HAnim
0x11E (version, node id, numBones[, flags, keyframeSize, bones (id, index, flags)]) or Frame-name
0x253F2FE) GeometryList(0x1A: Struct(count) Geometry...) Atomic(0x14: Struct(frame, geometry,
flags[, unused])) ...
Geometry (0x0F): Struct(flags, numTriangles, numVertices, numMorphTargets[, 3 x f32 lighting
if < 3.4]; when not native: prelit u8 RGBA[nv] if flags&8, uv sets f32[nv][2], triangles
(u16 v1, v0, material, v2), then per morph target sphere f32[4], hasVerts, hasNormals, verts,
normals) MaterialList(0x08: Struct(count, s32[count] reuse index or -1) Material(0x07:
Struct(flags, RGBA, unused, textured[, ambient, specular, diffuse]) Texture(0x06: Struct(filter |
addrU<<8 | addrV<<12) String(name) String(mask)))) Extension(BinMesh 0x50E: flags, numMeshes,
totalIndices, per mesh (numIndices, material[, u32 indices when not native]); NativeData 0x510;
Skin 0x116).
World (0x0B): Struct(rootIsWorldSector, invOrigin[3], numTriangles, numVertices, numPlaneSectors,
numAtomicSectors, colSectorSize, flags, bbox[6]) MaterialList, then the sector tree: PlaneSector
0x0A (Struct + two child sectors) / AtomicSector 0x09 (Struct(matListWindowBase, numTriangles,
numVertices, bbox[6], unused[2], vertices f32[nv][3], normals, prelit, uvs, triangles
(u16 material, v0, v1, v2)) Extension).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

# chunk ids
STRUCT = 0x01
STRING = 0x02
EXTENSION = 0x03
TEXTURE = 0x06
MATERIAL = 0x07
MATLIST = 0x08
ATOMIC_SECTOR = 0x09
PLANE_SECTOR = 0x0A
WORLD = 0x0B
FRAMELIST = 0x0E
GEOMETRY = 0x0F
CLUMP = 0x10
ATOMIC = 0x14
TEXNATIVE = 0x15
TEXDICT = 0x16
GEOMLIST = 0x1A
SKIN = 0x116
HANIM = 0x11E
BINMESH = 0x50E
NATIVEDATA = 0x510
FRAMENAME = 0x253F2FE

GEOM_TRISTRIP = 0x01
GEOM_POSITIONS = 0x02
GEOM_TEXTURED = 0x04
GEOM_PRELIT = 0x08
GEOM_NORMALS = 0x10
GEOM_TEXTURED2 = 0x80
GEOM_NATIVE = 0x01000000

PLATFORM_GAMECUBE = 6


class RwError(Exception):
    pass


def rw_version(libid: int) -> int:
    """Library id stamp -> packed version (0x35000 = 3.5.0.0)."""
    if libid & 0xFFFF0000 == 0:
        return libid << 8
    return (((libid >> 14) & 0x3FF00) + 0x30000) | ((libid >> 16) & 0x3F)


def looks_like_stream(
    head: bytes, size: int, types: tuple[int, ...] = (CLUMP, WORLD, TEXDICT)
) -> bool:
    """Cheap sniff: a little-endian chunk header of one of `types` whose size fits the file."""
    if len(head) < 12:
        return False
    t, sz, lib = struct.unpack_from("<3I", head, 0)
    if t not in types:
        return False
    # new-style stamps carry 0xffff build bits; RW 3.2-3.7 builds without them (Bloody
    # Roar: 0x1c02002d) still decode through rw_version
    old_style = 0x1800_0000 <= lib < 0x1C10_0000
    if not old_style and (lib & 0xFFFF != 0xFFFF or lib >> 16 > 0x3FFF):
        return False
    return 12 + sz <= size and sz >= 4


@dataclass
class Chunk:
    type: int
    size: int
    libid: int
    off: int  # body offset

    @property
    def end(self) -> int:
        return self.off + self.size

    @property
    def version(self) -> int:
        return rw_version(self.libid)


def chunks(data: bytes, off: int, end: int):
    """Iterate sibling chunks in data[off:end]; a truncated tail ends the iteration."""
    while off + 12 <= end:
        t, sz, lib = struct.unpack_from("<3I", data, off)
        if off + 12 + sz > end:
            sz = end - off - 12
        yield Chunk(t, sz, lib, off + 12)
        off += 12 + sz


def children(data: bytes, c: Chunk) -> list[Chunk]:
    return list(chunks(data, c.off, c.end))


def child(data: bytes, c: Chunk, ctype: int) -> Chunk | None:
    for k in chunks(data, c.off, c.end):
        if k.type == ctype:
            return k
    return None


def read_string(data: bytes, c: Chunk) -> str:
    return data[c.off : c.end].split(b"\0")[0].decode("latin-1")


def top(data: bytes) -> Chunk:
    if len(data) < 12:
        raise RwError("not a RenderWare stream")
    return next(chunks(data, 0, len(data)))


# ---------------------------------------------------------------------------
# structures
# ---------------------------------------------------------------------------


@dataclass
class Frame:
    rotation: np.ndarray  # (3,3) rows = RW right/up/at vectors
    position: np.ndarray  # (3,)
    parent: int | None
    name: str = ""
    hanim_id: int | None = None


@dataclass
class Material:
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    texture: str | None = None
    mask: str | None = None
    filter_addr: int = (
        0  # filter | addrU << 8 | addrV << 12 (RW addressing 1 wrap 2 mirror 3 clamp)
    )


@dataclass
class Skin:
    num_bones: int
    max_weights: int
    used_bones: list[int]
    # per-vertex (nv, k) bone indices and weights, or None for direct-matrix-index skins where the
    # display list carries a PNMTXIDX per vertex (rwgc) that indexes `used_bones`
    indices: np.ndarray | None
    weights: np.ndarray | None
    inverse_bind: np.ndarray  # (num_bones, 4, 4) row-major RW matrices (rows = basis vectors)
    gamecube: bool  # True for the RW >= 3.5 GameCube packaging


@dataclass
class BinMesh:
    tristrip: bool
    meshes: list[tuple[int, np.ndarray | None]]  # (material index, indices or None if native)


@dataclass
class Geometry:
    flags: int
    num_triangles: int
    num_vertices: int
    materials: list[Material]
    version: int
    positions: np.ndarray | None = None  # (nv,3) plain geometry
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None  # (nv,4) u8
    uvs: list[np.ndarray] = field(default_factory=list)  # each (nv,2)
    triangles: np.ndarray | None = None  # (nt,4) = v0, v1, v2, material
    native: bytes | None = None  # Native Data PLG struct body (GameCube)
    binmesh: BinMesh | None = None
    skin: Skin | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_native(self) -> bool:
        return self.native is not None


@dataclass
class Atomic:
    frame: int
    geometry: int


@dataclass
class Clump:
    frames: list[Frame]
    geometries: list[Geometry]
    atomics: list[Atomic]
    bones: list[tuple[int, int, int]]  # HAnim hierarchy (node id, index, flags), or []
    version: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class Sector:
    material_base: int
    positions: np.ndarray | None = None
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: list[np.ndarray] = field(default_factory=list)
    triangles: np.ndarray | None = None  # (nt,4) v0,v1,v2,material (world index)
    native: bytes | None = None
    binmesh: BinMesh | None = None
    num_vertices: int = 0


@dataclass
class World:
    flags: int
    materials: list[Material]
    sectors: list[Sector]
    version: int
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------


def _parse_material(data: bytes, c: Chunk) -> Material:
    st = child(data, c, STRUCT)
    if st is None or st.size < 16:
        raise RwError("material without struct")
    r, g, b, a = struct.unpack_from("<4B", data, st.off + 4)
    textured = struct.unpack_from("<I", data, st.off + 12)[0]
    m = Material(color=(r, g, b, a))
    if textured:
        t = child(data, c, TEXTURE)
        if t is not None:
            tst = child(data, t, STRUCT)
            if tst is not None and tst.size >= 4:
                m.filter_addr = struct.unpack_from("<I", data, tst.off)[0] & 0xFFFF
            names = [read_string(data, k) for k in chunks(data, t.off, t.end) if k.type == STRING]
            if names:
                m.texture = names[0] or None
            if len(names) > 1 and names[1]:
                m.mask = names[1]
    return m


def _parse_matlist(data: bytes, c: Chunk) -> list[Material]:
    st = child(data, c, STRUCT)
    if st is None:
        return []
    count = struct.unpack_from("<I", data, st.off)[0]
    reuse = (
        list(struct.unpack_from(f"<{count}i", data, st.off + 4))
        if st.size >= 4 + 4 * count
        else [-1] * count
    )
    mats_in = [k for k in chunks(data, c.off, c.end) if k.type == MATERIAL]
    out: list[Material] = []
    it = iter(mats_in)
    for r in reuse:
        if r >= 0 and r < len(out):
            out.append(out[r])
            continue
        k = next(it, None)
        out.append(_parse_material(data, k) if k is not None else Material())
    return out


def _parse_binmesh(data: bytes, c: Chunk, native: bool) -> BinMesh | None:
    if c.size < 12:
        return None
    flags, nmesh, _total = struct.unpack_from("<3I", data, c.off)
    p = c.off + 12
    meshes = []
    for _ in range(nmesh):
        if p + 8 > c.end:
            break
        nidx, mat = struct.unpack_from("<2I", data, p)
        p += 8
        idx = None
        if not native:
            if p + 4 * nidx > c.end:
                break
            idx = np.frombuffer(data, "<u4", nidx, p).astype(np.uint32)
            p += 4 * nidx
        meshes.append((mat, idx))
    return BinMesh(tristrip=bool(flags & 1), meshes=meshes)


def _parse_skin(data: bytes, c: Chunk, nverts: int, version: int) -> Skin | None:
    """Skin PLG. GameCube RW >= 3.5 wraps it in a Struct: u32 platform (6), u8 numBones,
    numUsed, maxWeights, pad, u8 used[numUsed], then unless maxWeights == 1 (display list carries
    the matrix index) u8 boneIndex[nv][maxWeights] and u8 weight[nv][maxWeights] in 1/128 units,
    then f32 BE inverse bind 4x4[numBones], then u32 boneLimit, numMeshes, numRLE (+ split data).
    Otherwise the generic layout: u8 header, used[], u8 index[nv][4], f32 LE weight[nv][4],
    4x4 f32 LE per bone (with a 4-byte prefix on some old streams), then the 3 u32 tail."""
    st = child(data, c, STRUCT)
    gc = (
        st is not None
        and st.size >= 8
        and struct.unpack_from("<I", data, st.off)[0] == PLATFORM_GAMECUBE
    )
    if gc:
        body = st.off
        end = st.end
        nb, nu, mw, _pad = struct.unpack_from("<4B", data, body + 4)
        p = body + 8
        used = list(data[p : p + nu])
        p += nu
        indices = weights = None
        per_vertex = mw >= 2 and p + 2 * nverts * mw + nb * 64 <= end
        if per_vertex:
            indices = (
                np.frombuffer(data, np.uint8, nverts * mw, p).reshape(nverts, mw).astype(np.uint16)
            )
            p += nverts * mw
            weights = (
                np.frombuffer(data, np.uint8, nverts * mw, p).reshape(nverts, mw).astype(np.float32)
                / 128.0
            )
            p += nverts * mw
        if p + nb * 64 > end:
            raise RwError("skin: truncated bone matrices")
        mats = np.frombuffer(data, ">f4", nb * 16, p).reshape(nb, 4, 4).astype(np.float32)
        return Skin(nb, mw, used, indices, weights, mats, True)
    body, end = c.off, c.end
    if st is not None and st.size >= 4:  # non-GameCube packaging with a struct: use it
        body, end = st.off, st.end
    if end - body < 4:
        return None
    nb, nu, mw, _pad = struct.unpack_from("<4B", data, body)
    p = body + 4
    used = list(data[p : p + nu]) if nu <= nb else []
    p += len(used)
    need = nverts * 20
    if p + need > end:
        raise RwError("skin: truncated vertex weights")
    indices = np.frombuffer(data, np.uint8, nverts * 4, p).reshape(nverts, 4).astype(np.uint16)
    p += nverts * 4
    weights = np.frombuffer(data, "<f4", nverts * 4, p).reshape(nverts, 4).astype(np.float32)
    p += nverts * 16
    rest = end - p
    stride = 64
    if nb:
        per_bone = (rest - 12) // nb if rest - 12 >= nb * 64 else rest // nb
        if per_bone == 68:
            stride = 68  # old streams: u32 prefix before every matrix
    if p + nb * stride > end:
        raise RwError("skin: truncated bone matrices")
    mats = (
        np.stack(
            [
                np.frombuffer(data, "<f4", 16, p + i * stride + (stride - 64)).reshape(4, 4)
                for i in range(nb)
            ]
        ).astype(np.float32)
        if nb
        else np.zeros((0, 4, 4), np.float32)
    )
    return Skin(nb, max(mw, 1), used, indices, weights, mats, False)


def _parse_geometry(data: bytes, c: Chunk) -> Geometry:
    st = child(data, c, STRUCT)
    if st is None or st.size < 16:
        raise RwError("geometry without struct")
    flags, ntri, nvert, nmorph = struct.unpack_from("<4I", data, st.off)
    ver = c.version
    p = st.off + 16
    if ver < 0x34000:
        p += 12  # ambient, specular, diffuse
    ml = child(data, c, MATLIST)
    g = Geometry(flags, ntri, nvert, _parse_matlist(data, ml) if ml else [], ver)
    native = bool(flags & GEOM_NATIVE)
    if not native:
        ntex = (flags >> 16) & 0xFF
        if ntex == 0:
            ntex = 2 if flags & GEOM_TEXTURED2 else 1 if flags & GEOM_TEXTURED else 0
        if flags & GEOM_PRELIT:
            g.colors = np.frombuffer(data, np.uint8, nvert * 4, p).reshape(nvert, 4).copy()
            p += nvert * 4
        for _ in range(ntex):
            g.uvs.append(
                np.frombuffer(data, "<f4", nvert * 2, p).reshape(nvert, 2).astype(np.float32)
            )
            p += nvert * 8
        tri = np.frombuffer(data, "<u2", ntri * 4, p).reshape(ntri, 4).astype(np.uint32)
        g.triangles = np.stack([tri[:, 1], tri[:, 0], tri[:, 3], tri[:, 2]], axis=1)
        p += ntri * 8
        if nmorph >= 1 and p + 24 <= st.end:
            has_v, has_n = struct.unpack_from("<2I", data, p + 16)
            p += 24
            if has_v:
                g.positions = (
                    np.frombuffer(data, "<f4", nvert * 3, p).reshape(nvert, 3).astype(np.float32)
                )
                p += nvert * 12
            if has_n:
                g.normals = (
                    np.frombuffer(data, "<f4", nvert * 3, p).reshape(nvert, 3).astype(np.float32)
                )
                p += nvert * 12
    ext = child(data, c, EXTENSION)
    if ext is not None:
        for k in chunks(data, ext.off, ext.end):
            try:
                if k.type == NATIVEDATA:
                    nst = child(data, k, STRUCT)
                    g.native = data[nst.off : nst.end] if nst is not None else data[k.off : k.end]
                elif k.type == BINMESH:
                    g.binmesh = _parse_binmesh(data, k, native)
                elif k.type == SKIN:
                    g.skin = _parse_skin(data, k, nvert, ver)
            except (RwError, ValueError, struct.error) as e:
                g.warnings.append(f"geometry plugin {k.type:#x}: {e}")
    return g


def _parse_frames(data: bytes, c: Chunk) -> list[Frame]:
    st = child(data, c, STRUCT)
    if st is None:
        return []
    count = struct.unpack_from("<I", data, st.off)[0]
    frames = []
    p = st.off + 4
    for _ in range(count):
        if p + 56 > st.end:
            break
        vals = struct.unpack_from("<12fiI", data, p)
        rot = np.array(vals[:9], np.float32).reshape(3, 3)
        pos = np.array(vals[9:12], np.float32)
        parent = vals[12]
        frames.append(Frame(rot, pos, parent if 0 <= parent < count else None))
        p += 56
    exts = [k for k in chunks(data, st.end, c.end) if k.type == EXTENSION]
    for f, ext in zip(frames, exts, strict=False):
        for k in chunks(data, ext.off, ext.end):
            if k.type == HANIM and k.size >= 12:
                f.hanim_id = struct.unpack_from("<I", data, k.off + 4)[0]
            elif k.type == FRAMENAME:
                f.name = read_string(data, k)
    return frames


def _hanim_bones(data: bytes, c: Chunk) -> list[tuple[int, int, int]]:
    st = child(data, c, STRUCT)
    if st is None:
        return []
    for k in chunks(data, st.end, c.end):
        if k.type != EXTENSION:
            continue
        for h in chunks(data, k.off, k.end):
            if h.type == HANIM and h.size >= 20:
                nbones = struct.unpack_from("<I", data, h.off + 8)[0]
                if nbones:
                    p = h.off + 20
                    bones = []
                    for _ in range(nbones):
                        if p + 12 > h.end:
                            break
                        bones.append(struct.unpack_from("<3I", data, p))
                        p += 12
                    return bones
    return []


def parse_clump(data: bytes) -> Clump:
    c = top(data)
    if c.type != CLUMP:
        raise RwError(f"not a clump (chunk {c.type:#x})")
    clump = Clump([], [], [], [], c.version)
    for k in chunks(data, c.off, c.end):
        if k.type == FRAMELIST:
            clump.frames = _parse_frames(data, k)
            clump.bones = _hanim_bones(data, k)
        elif k.type == GEOMLIST:
            for g in chunks(data, k.off, k.end):
                if g.type == GEOMETRY:
                    try:
                        clump.geometries.append(_parse_geometry(data, g))
                    except (RwError, ValueError, struct.error) as e:
                        clump.warnings.append(f"geometry {len(clump.geometries)}: {e}")
                        clump.geometries.append(Geometry(0, 0, 0, [], c.version))
        elif k.type == ATOMIC:
            st = child(data, k, STRUCT)
            if st is not None and st.size >= 8:
                fi, gi = struct.unpack_from("<2I", data, st.off)
                clump.atomics.append(Atomic(fi, gi))
    return clump


def _parse_sector(
    data: bytes, c: Chunk, world_flags: int, version: int, warnings: list[str]
) -> Sector | None:
    st = child(data, c, STRUCT)
    if st is None or st.size < 44:
        return None
    base, ntri, nvert = struct.unpack_from("<3I", data, st.off)
    s = Sector(base, num_vertices=nvert)
    ext = child(data, c, EXTENSION)
    native = None
    if ext is not None:
        for k in chunks(data, ext.off, ext.end):
            if k.type == NATIVEDATA:
                nst = child(data, k, STRUCT)
                native = data[nst.off : nst.end] if nst is not None else data[k.off : k.end]
            elif k.type == BINMESH:
                s.binmesh = _parse_binmesh(data, k, native is not None or st.size <= 44)
    s.native = native
    if native is not None or nvert == 0:
        return s
    p = st.off + 44
    s.positions = np.frombuffer(data, "<f4", nvert * 3, p).reshape(nvert, 3).astype(np.float32)
    p += nvert * 12
    ntex = (world_flags >> 16) & 0xFF
    if ntex == 0:
        ntex = 2 if world_flags & GEOM_TEXTURED2 else 1 if world_flags & GEOM_TEXTURED else 0
    fixed = (4 * nvert if world_flags & GEOM_PRELIT else 0) + ntex * 8 * nvert + ntri * 8
    if world_flags & GEOM_NORMALS:
        rest = st.end - p - fixed
        if rest >= nvert * 12:
            s.normals = (
                np.frombuffer(data, "<f4", nvert * 3, p).reshape(nvert, 3).astype(np.float32)
            )
            p += nvert * 12
        elif rest >= nvert * 4:
            n = np.frombuffer(data, np.int8, nvert * 4, p).reshape(nvert, 4)[:, :3]
            s.normals = n.astype(np.float32) / 127.0
            p += nvert * 4
    if world_flags & GEOM_PRELIT:
        s.colors = np.frombuffer(data, np.uint8, nvert * 4, p).reshape(nvert, 4).copy()
        p += nvert * 4
    for _ in range(ntex):
        s.uvs.append(np.frombuffer(data, "<f4", nvert * 2, p).reshape(nvert, 2).astype(np.float32))
        p += nvert * 8
    if p + ntri * 8 <= st.end:
        tri = np.frombuffer(data, "<u2", ntri * 4, p).reshape(ntri, 4).astype(np.uint32)
        s.triangles = np.stack([tri[:, 1], tri[:, 2], tri[:, 3], tri[:, 0] + base], axis=1)
    else:
        warnings.append("atomic sector: truncated triangle list")
    return s


def parse_world(data: bytes) -> World:
    c = top(data)
    if c.type != WORLD:
        raise RwError(f"not a world (chunk {c.type:#x})")
    st = child(data, c, STRUCT)
    if st is None or st.size < 36:
        raise RwError("world without struct")
    # flags sit right before the 6-float bounding box; RW 3.2 worlds (52-byte struct: origin,
    # 3 lighting floats, 5 counts, flags) have no box, so count from the end either way
    flags_off = st.size - 28 if st.size >= 64 else st.size - 4
    flags = struct.unpack_from("<I", data, st.off + flags_off)[0]
    ml = child(data, c, MATLIST)
    w = World(flags, _parse_matlist(data, ml) if ml else [], [], c.version)

    def walk(ch: Chunk) -> None:
        for k in chunks(data, ch.off, ch.end):
            if k.type == ATOMIC_SECTOR:
                s = _parse_sector(data, k, flags, w.version, w.warnings)
                if s is not None:
                    w.sectors.append(s)
            elif k.type == PLANE_SECTOR:
                walk(k)

    walk(c)
    return w
