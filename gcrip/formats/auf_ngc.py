"""007: Agent Under Fire ``maps/*.ngc`` - EA Redwood Shores' Quake III derivative, read
against the symtab of the shipped ``Bond.elf`` (``RSRC_Load``, ``BOA_ExpandInplace``,
``R_InitSurfaces``, ``R_DrawSurf``, ``SHDR_FixupShaderTable``, ``R_InitVtxDesc``).

A map is a stream of chunks at 32-byte alignment, each a 32-byte header then its bytes::

    +0   char tag[8]     stored reversed (b".bla_dns" is "snd_alb")
    +8   u32 size        unpacked bytes
    +16  u32 compressed  1 = BOA
    +24  u32 stored      bytes on disc
    +28  u32 unpacked      the size rounded up to the buffer the game allocates

BOA is a byte LZ: a flags byte, LSB first; a set bit copies a literal, a clear bit reads
``b0, b1`` and copies ``(b0 & 0xf) + 2`` bytes from ``(b0 >> 4) | (b1 << 4)`` back (0 = skip).

Chunks: ``snd_alb``, ``sndbank``, ``restxtrs`` (textures), ``shaders``, ``bspfile`` (itself
a chunk stream of the Quake III lumps - ``planes``, ``brushes``, ``bspnodes``, ``entities``,
``ligtmaps``, ``ngcsurfs`` ...), ``shockprf``, ``restable`` (the level's models).

``ngcsurfs``: ``f32 1.15``, then ``(ptr, count)`` pairs from +8 - vertices (14 bytes: ``s16
x, y, z, s16 s, t, s16 lightmap s, t``), ``u8`` strip indices, 28-byte surfaces (``u8 type,
u8 lightmap, u16 0x400, u16 shader, u8 4, u8 vertices, u32, ptr vertices, u16 first index,
...``), 0x70-byte groups, shader ids - and a 3x4 matrix at +0xc0 that the game loads as the
position matrix, so world = ``M * (x, y, z)``; uv = ``s / 256``, lightmap uv = ``/ 32768``
(the GX formats ``R_InitVtxDesc`` sets).  A type-0 surface draws one ``GX_TRIANGLESTRIP`` of
its ``vertices`` ``u8`` indices from ``first``.

``shaders``: ``f32``, then ``(ptr, count)`` pairs - 16-byte shaders (``u32 id, ...,
ptr body``), 20-byte bodies (``ptr stages, u8, u8 stages, ...``), 20-byte stages (``u16
flags, u16, u32 texture id, ...``; ``0xccddccdd`` is the lightmap).  A surface's shader
index goes straight into the shader array (``SHDR_GetIDX``).

``restxtrs``: ``f32 1.2, u32 count, u32 16, u32 headers`` then ``count`` texture ids and
68-byte headers (``u32 GX format, u16 width, u16 height, u32, u32, u32 data offset, u32
bytes, ..., u32 mip levels``) - the pixels are as the hardware wants them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture as gx

CHUNK = 32
ALIGN = 32
MAX_CHUNKS = 256
SURFACE = 28
VERTEX = 14
SHADER = 16
BODY = 20
STAGE = 20
TEXTURE_HEADER = 68
LIGHTMAP_ID = 0xCCDDCCDD
UV_SCALE = 1.0 / 256.0
LM_SCALE = 1.0 / 32768.0
MAX_TEXTURES = 4096
MAX_SURFACES = 1 << 20


@dataclass
class Chunk:
    tag: str
    at: int  # of the header
    size: int
    compressed: bool
    stored: int
    unpacked: int


@dataclass
class Surface:
    shader: int
    lightmap: int
    positions: np.ndarray
    uvs: np.ndarray
    lightmap_uvs: np.ndarray
    indices: np.ndarray


@dataclass
class Texture:
    ident: int
    format: int
    width: int
    height: int
    data_at: int
    size: int


@dataclass
class Map:
    surfaces: list[Surface] = field(default_factory=list)
    shader_textures: dict[int, int] = field(default_factory=dict)  # shader index -> texture id
    shader_ids: dict[int, int] = field(default_factory=dict)  # shader hash -> index
    resource_chunk: bytes = b""
    textures: dict[int, Texture] = field(default_factory=dict)  # texture id -> header
    texture_chunk: bytes = b""
    chunks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def boa_expand(src: bytes, size: int) -> bytes:
    out = bytearray()
    p = 0
    n = len(src)
    while len(out) < size and p < n:
        flags = src[p]
        p += 1
        for bit in range(8):
            if len(out) >= size or p >= n:
                break
            if flags & (1 << bit):
                out.append(src[p])
                p += 1
                continue
            if p + 2 > n:
                return bytes(out)
            b0, b1 = src[p], src[p + 1]
            p += 2
            length = (b0 & 0xF) + 2
            back = ((b0 >> 4) | (b1 << 4)) & 0xFFF
            if back == 0:
                continue
            start = len(out) - back
            if start < 0:
                return bytes(out)
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)


def _tag(raw: bytes) -> str:
    return raw[::-1].rstrip(b"\0").decode("latin-1")


def chunk_header(data: bytes, at: int) -> Chunk | None:
    if at + CHUNK > len(data):
        return None
    tag = _tag(data[at : at + 8])
    size, _x, comp, _y, stored, unpacked = struct.unpack_from(">6I", data, at + 8)
    if comp not in (0, 1) or not tag or not all(32 <= ord(c) < 127 for c in tag):
        return None
    body = stored if comp else size
    if body == 0 or at + CHUNK + body > len(data) or (comp and unpacked < size):
        return None
    return Chunk(tag, at, size, bool(comp), body, unpacked if comp else size)


def is_map(head: bytes, size: int) -> bool:
    """The first chunk header checks out and the file is one of the known first tags."""
    if len(head) < CHUNK or size < CHUNK * 2:
        return False
    tag = _tag(head[:8])
    if tag not in ("snd_alb", "sndbank", "restxtrs", "shaders", "bspfile", "restable"):
        return False
    _size, _x, comp, _y, stored, unpacked = struct.unpack_from(">6I", head, 8)
    body = stored if comp else _size
    return comp in (0, 1) and 0 < body <= size and (not comp or unpacked >= _size)


def chunks(data: bytes) -> list[tuple[Chunk, bytes]]:
    out: list[tuple[Chunk, bytes]] = []
    p = 0
    while len(out) < MAX_CHUNKS:
        c = chunk_header(data, p)
        if c is None:
            break
        raw = data[p + CHUNK : p + CHUNK + c.stored]
        out.append((c, boa_expand(raw, c.unpacked) if c.compressed else raw))
        p += CHUNK + c.stored
        p = (p + ALIGN - 1) & ~(ALIGN - 1)
    return out


def _world(s: bytes, out: Map) -> None:
    if len(s) < 0xF0:
        out.warnings.append("ngcsurfs too short")
        return
    hdr = struct.unpack_from(">7I", s, 8)
    verts_at, _nverts, idx_at, nidx, surf_at, nsurf = hdr[:6]
    if surf_at + nsurf * SURFACE > len(s) or nsurf > MAX_SURFACES:
        out.warnings.append("ngcsurfs surface table past the chunk")
        return
    m = np.frombuffer(s, ">f4", 12, 0xC0).reshape(3, 4)
    for i in range(nsurf):
        r = surf_at + i * SURFACE
        kind, lightmap, _flags, shader, _four, count = struct.unpack_from(">BBHHBB", s, r)
        vptr = struct.unpack_from(">I", s, r + 0xC)[0]
        first = struct.unpack_from(">H", s, r + 0x10)[0]
        if kind != 0 or count < 3:
            continue  # patches (bicubic) are not read yet
        if idx_at + first + count > len(s):
            out.warnings.append(f"surface {i}: indices past the chunk")
            continue
        idx = np.frombuffer(s, np.uint8, count, idx_at + first).astype(np.int64)
        nv = int(idx.max()) + 1
        if vptr + nv * VERTEX > len(s):
            out.warnings.append(f"surface {i}: vertices past the chunk")
            continue
        v = np.frombuffer(s, ">i2", nv * 7, vptr).reshape(nv, 7).astype(np.float32)
        pos = (v[:, :3] @ m[:, :3].T + m[:, 3]).astype(np.float32)
        tris = []
        for k in range(count - 2):
            a, b, c = idx[k], idx[k + 1], idx[k + 2]
            if len({a, b, c}) < 3:
                continue
            tris.append((a, b, c) if k % 2 == 0 else (b, a, c))
        if not tris:
            continue
        out.surfaces.append(
            Surface(
                shader,
                lightmap,
                pos,
                np.ascontiguousarray(v[:, 3:5] * UV_SCALE, np.float32),
                np.ascontiguousarray(v[:, 5:7] * LM_SCALE, np.float32),
                np.array(tris, np.uint32).reshape(-1),
            )
        )


def _shaders(s: bytes, out: Map) -> None:
    if len(s) < 0x5C:
        return
    shaders_at, nshaders = struct.unpack_from(">2I", s, 4)
    for i in range(min(nshaders, MAX_TEXTURES)):
        r = shaders_at + i * SHADER
        if r + SHADER > len(s):
            break
        out.shader_ids[struct.unpack_from(">I", s, r)[0]] = i
        body = struct.unpack_from(">I", s, r + 0xC)[0]
        if body + BODY > len(s):
            continue
        stages_at = struct.unpack_from(">I", s, body)[0]
        nstages = s[body + 5]
        for k in range(nstages):
            st = stages_at + k * STAGE
            if st + STAGE > len(s):
                break
            tex = struct.unpack_from(">I", s, st + 4)[0]
            if tex and tex != LIGHTMAP_ID:
                out.shader_textures[i] = tex
                break


def _textures(t: bytes, out: Map) -> None:
    if len(t) < 16:
        return
    _ver, count, _x, headers = struct.unpack_from(">fIII", t, 0)
    if count > MAX_TEXTURES or headers + count * TEXTURE_HEADER > len(t):
        return
    ids = struct.unpack_from(f">{count}I", t, 16)
    for i, ident in enumerate(ids):
        h = headers + i * TEXTURE_HEADER
        fmt, w, hgt, _a, _b, data_at, size = struct.unpack_from(">IHHIIII", t, h)
        if fmt in gx.TILE_DIMS and 0 < w <= 4096 and 0 < hgt <= 4096 and data_at + size <= len(t):
            out.textures[ident] = Texture(ident, fmt, w, hgt, data_at, size)
    out.texture_chunk = t


def parse(data: bytes) -> Map | None:
    if not is_map(data[:CHUNK], len(data)):
        return None
    out = Map()
    for c, blob in chunks(data):
        out.chunks.append(c.tag)
        if c.tag == "bspfile":
            for lump, body in chunks(blob):
                if lump.tag == "ngcsurfs":
                    _world(body, out)
        elif c.tag == "shaders":
            _shaders(blob, out)
        elif c.tag == "restxtrs":
            _textures(blob, out)
        elif c.tag == "restable":
            out.resource_chunk = blob
    return out


def decode_texture(m: Map, tex: Texture) -> np.ndarray | None:
    need = gx.encoded_size(tex.format, tex.width, tex.height)
    if tex.data_at + need > len(m.texture_chunk):
        return None
    return gx.decode(
        tex.format, tex.width, tex.height, m.texture_chunk[tex.data_at : tex.data_at + need]
    )


# -- the models in restable: .gcm NGCObject3D images ---------------------------------------------

MODEL_MAGIC = 0x484  # bits 20..31 of the first word
ENTVTX = 6
STRIP_REC = 8
GROUP_REC = 8
SECTION_REC = 16
NRM_SCALE = 1.0 / 128.0
ST_SCALE = 1.0 / 2048.0


@dataclass
class ModelBatch:
    shader_id: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


@dataclass
class Model:
    name: str
    batches: list[ModelBatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resources(table: bytes) -> list[tuple[str, int, int]]:
    """(name, offset, size) of every member of a ``restable`` chunk (``FS_UseResourceTable``:
    ``u32 count, u32[3]``, then 16-byte entries ``ptr name, ptr data, u32 size, u32 hash``)."""
    if len(table) < 16:
        return []
    count = struct.unpack_from(">I", table, 0)[0]
    out = []
    for i in range(min(count, MAX_TEXTURES * 4)):
        e = 16 + 16 * i
        if e + 16 > len(table):
            break
        name_at, data_at, size, _h = struct.unpack_from(">4I", table, e)
        if name_at >= len(table) or data_at + size > len(table):
            continue
        end = table.find(b"\0", name_at)
        name = table[name_at : end if end > 0 else name_at + 64].decode("latin-1", "replace")
        out.append((name, data_at, size))
    return out


def _block(data: bytes, at: int) -> int | None:
    """A sub-block's header start: ``at + 8 + byte 7`` (``FixupHeaderOff``)."""
    if at + 8 > len(data):
        return None
    return at + 8 + data[at + 7]


def model(data: bytes, name: str = "") -> Model | None:
    """One ``.gcm``: the ``C_Object3D`` header's +0x80 block is the NGC geometry - a 3x4
    matrix, then ``(ptr, count)`` pairs from +0x34: positions (s16 x3), normals (s8 x3),
    uvs (s16 x2), 6-byte vertices (position / normal / uv indices), the u16 index stream,
    the per-vertex matrix bytes, 8-byte strips (``u16 first, u16 count, u16 matrix bytes,
    u8, u8 slot``), matrix map, 8-byte groups (``u16 first map, u16 maps, u16 first strip,
    u16 strips``) and 16-byte sections (``u32, u32 shader id, u16 first group, u16 groups,
    u16 triangles, u16 indices``) - ``R_DrawGeomSection``."""
    if len(data) < 0x20 or (struct.unpack_from(">I", data, 0)[0] >> 20) & 0xFFF != MODEL_MAGIC:
        return None
    hdr = _block(data, 0)
    if hdr is None or hdr + 0x98 > len(data):
        return None
    ngc_at = struct.unpack_from(">I", data, hdr + 0x80)[0]
    base = _block(data, ngc_at) if ngc_at else None
    if base is None or base + 0x9C > len(data):
        return None
    out = Model(name)
    m = np.frombuffer(data, ">f4", 12, base).reshape(3, 4)
    pairs = [struct.unpack_from(">2I", data, base + 0x34 + 8 * k) for k in range(10)]
    (pos_p, npos), (nrm_p, nnrm), (st_p, nst), (ev_p, nev), (idx_p, nidx) = pairs[:5]
    (_mtx_p, _nmtx), (strip_p, nstrip), (_mm_p, _nmm), (grp_p, ngrp), (sec_p, nsec) = pairs[5:10]
    n = len(data)
    if not (npos and nev and nidx and nstrip and nsec):
        return out
    ends = (
        base + pos_p + npos * 6,
        base + nrm_p + nnrm * 3,
        base + st_p + nst * 4,
        base + ev_p + nev * ENTVTX,
        base + idx_p + nidx * 2,
        base + strip_p + nstrip * STRIP_REC,
        base + grp_p + ngrp * GROUP_REC,
        base + sec_p + nsec * SECTION_REC,
    )
    if max(ends) > n:
        out.warnings.append("arrays past the file")
        return out
    pos = np.frombuffer(data, ">i2", npos * 3, base + pos_p).reshape(npos, 3).astype(np.float32)
    positions = (pos @ m[:, :3].T + m[:, 3]).astype(np.float32)
    normals = np.frombuffer(data, np.int8, nnrm * 3, base + nrm_p).reshape(nnrm, 3)
    normals = (normals.astype(np.float32) * NRM_SCALE).astype(np.float32)
    uvs = np.frombuffer(data, ">i2", nst * 2, base + st_p).reshape(nst, 2).astype(np.float32)
    uvs = (uvs * ST_SCALE).astype(np.float32)
    ev = np.frombuffer(data, ">u2", nev * 3, base + ev_p).reshape(nev, 3).astype(np.int64)
    if int(ev[:, 0].max()) >= npos or int(ev[:, 1].max()) >= nnrm or int(ev[:, 2].max()) >= nst:
        out.warnings.append("vertex records index past their arrays")
        return out
    stream = np.frombuffer(data, ">u2", nidx, base + idx_p).astype(np.int64)
    if int(stream.max()) >= nev:
        out.warnings.append("index stream past the vertex records")
        return out
    for s in range(nsec):
        r = base + sec_p + s * SECTION_REC
        _owner, shader_id, first_group, ngroups = struct.unpack_from(">IIHH", data, r)
        used: list[np.ndarray] = []
        tris: list[tuple[int, int, int]] = []
        corner_base = 0
        for g in range(first_group, min(first_group + ngroups, ngrp)):
            _fm, _nm, first_strip, nstrips = struct.unpack_from(">4H", data, base + grp_p + g * 8)
            for t in range(first_strip, min(first_strip + nstrips, nstrip)):
                first, count = struct.unpack_from(">2H", data, base + strip_p + t * STRIP_REC)
                if count < 3 or first + count > nidx:
                    continue
                used.append(stream[first : first + count])
                for k in range(count - 2):
                    a, b, c = corner_base + k, corner_base + k + 1, corner_base + k + 2
                    # the models wind their strips the other way round from the world
                    tris.append((b, a, c) if k % 2 == 0 else (a, b, c))
                corner_base += count
        if not tris:
            continue
        corners = np.concatenate(used)
        uniq, inverse = np.unique(corners, return_inverse=True)
        tri = inverse.reshape(-1)[np.array(tris, np.int64)]
        keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
        tri = tri[keep]
        if not len(tri):
            continue
        v = ev[uniq]
        out.batches.append(
            ModelBatch(
                shader_id,
                np.ascontiguousarray(positions[v[:, 0]]),
                np.ascontiguousarray(normals[v[:, 1]]),
                np.ascontiguousarray(uvs[v[:, 2]]),
                tri.ravel().astype(np.uint32),
            )
        )
    return out


def shader_by_id(m: Map, shader_id: int) -> int | None:
    """The texture id a shader (by its hash) binds, through ``Map.shader_ids``."""
    idx = m.shader_ids.get(shader_id)
    return None if idx is None else m.shader_textures.get(idx)
