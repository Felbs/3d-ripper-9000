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
    return out


def decode_texture(m: Map, tex: Texture) -> np.ndarray | None:
    need = gx.encoded_size(tex.format, tex.width, tex.height)
    if tex.data_at + need > len(m.texture_chunk):
        return None
    return gx.decode(
        tex.format, tex.width, tex.height, m.texture_chunk[tex.data_at : tex.data_at + need]
    )
