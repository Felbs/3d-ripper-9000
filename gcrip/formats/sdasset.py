"""Silicon Dreams / Gusto Games "Proteus" asset files (``SDASSETF``): Freestyle Street
Soccer (GUVE51) ``*_models.ast`` / ``*_textures.ast``.

The magic is two u32 words, so it reads ``SDASSETF`` in the big-endian texture files and
``SADSFTES`` in the little-endian model files; every chunk tag is byte-swapped the same
way (``LRTM`` on disk is ``MTRL``).  ``.ast`` is also Nintendo's audio-stream extension,
which is why the classifier called these "audio" and the ``gx`` fallback scanned them
into two-position noise meshes before this reader existed.

Layout (all sizes exclude the 16-byte chunk header ``tag, u32 version, u32 arg, u32 size``):

- file: magic(8), u32 version, u32 top-level chunk count, chunks.  A team file is several
  files concatenated back to back (``thestreet-kai_models.ast`` = Ryu + Shuko + Takashi +
  Tetsuo, byte for byte), so parsing loops on the magic.
- **container** chunks (``MTRL``, ``SKEL``, ``MDL``, ``BMAP``): a NUL-terminated name
  padded to 4, then ``arg`` bytes of body, then ``size`` bytes of children.  The version
  word's top byte carries flags in the LE files (0x09 / 0x06 / 0x0F) and nothing in the BE
  ones, so container-ness is decided by tag, not flags.
- **leaf** chunks: ``arg`` is the chunk's index, ``size`` the payload.
- ``MTRL`` > ``EFCT``: effect path (``\\\\Proteus\\TEXTURED``, ``SHADOW`` lightmap,
  ``SPECULARMASKDUP``), u32, texture name.  The material's picture is its TEXTURED effect.
- ``SKEL``: u32 bone count, u32 names size, NUL-separated names, i32 parents,
  f32[16] per bone (row-vector world bind matrices, translation in row 3), f32 per bone.
- ``MDL`` > ``BND`` (6 f32 bbox), ``DATA``, ``WGHT``, ``WDGE``, ``MESH``, ``LOD``, ``INFO``.
- ``DATA``: u32, u32 id, u32 stride, u32 count, u8 attribute codes ending in 0x80
  (1 position f32x3, 2 normal f32x3, 3 colour u8x4, 4 uv f32x2), 8 pad, the vertices; then
  u32 block count and per block ``u32 n, u32 bone[n], u32 nv, nv vertices`` followed by
  ``nv * (n-1)`` bone-space copies of the same stride (the software-skinning palette).
  The block vertices continue the buffer's numbering, so a buffer's real length is the
  matching ``WGHT`` count.
- ``WGHT``: u32 count, per vertex ``u32 n, u32 bone[n], f32 weight[n]``.
- ``WDGE``: u32 vertex count, u32 n, u32[n] - the exporter's original wedge order; not
  needed to draw.
- ``MESH`` (version 5): name, 6 f32 bbox, u32 id, u32 index count, u32 strip count, 0, 0,
  u32, u32, u32 data id, 4 x (u32 attribute word, u32) whose byte 2 is the index width
  (1, 2 or 4), 96 reserved bytes, then strips: ``u32 n, n x (one index per attribute)``
  padded to 4, ``u32 trailer``.  Version 3 (``intro_models``) puts id / counts before the
  bbox.  The per-attribute indices are always equal (one interleaved buffer).
- ``LOD``: f32 distance, skeleton name, u32 n, u32 mesh id[n], per-mesh counts.  The
  smallest distance is the full-detail set (a player's LOD 4 at 25 has 770 triangles in
  the top where LOD 1 at 100 has 231).
- ``LGHT``: stadium lights (name + body), not read.
- ``BMAP`` > ``IMAG``: u16 w, u16 h, u16 w, u16 h, u32, u8 log2w, u8 log2h, u8 1,
  u8 compressed(7), u8 bits per pixel, u8 kind, ..., child ``IMAG`` = ``GC\0\0`` + GX tiles
  (CMPR when compressed, else I4 / I8 / RGB5A3 / RGBA8 by bit depth).
"""

from __future__ import annotations

import contextlib
import math
import re
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

MAGIC_BE = b"SDASSETF"
MAGIC_LE = b"SADSFTES"
CONTAINERS = {"MTRL", "SKEL", "MDL", "BMAP", "LGHT"}
ATTR_SIZES = {1: 12, 2: 12, 3: 4, 4: 8}
_TAG_RE = re.compile(rb"^[A-Z0-9]{3}[A-Z0-9\0]$")
MAX_BONES_PER_BLOCK = 64
MAX_BONES = 1024


class SdassetError(ValueError):
    pass


def is_sdasset(head: bytes) -> bool:
    return head[:8] in (MAGIC_BE, MAGIC_LE)


@dataclass
class Chunk:
    tag: str
    version: int
    flags: int
    arg: int
    size: int
    offset: int  # of the tag
    body: int  # payload start (after the name for containers)
    end: int  # one past the last byte the chunk covers
    name: str | None = None
    children: list[Chunk] = field(default_factory=list)


def _tag_at(data: bytes, off: int, le: bool) -> str | None:
    t = data[off : off + 4]
    if len(t) < 4:
        return None
    if le:
        t = t[::-1]
    return t.rstrip(b"\0").decode("latin1") if _TAG_RE.match(t) else None


def _cstr(data: bytes, off: int, limit: int | None = None) -> tuple[str, int]:
    """NUL-terminated string at *off* and its size padded to a 4-byte multiple."""
    end = data.find(b"\0", off, limit)
    if end < 0:
        raise SdassetError(f"unterminated string at {off:#x}")
    return data[off:end].decode("latin1"), (end - off + 1 + 3) // 4 * 4


def _walk(data: bytes, off: int, end: int, le: bool, depth: int = 0) -> list[Chunk]:
    e = "<" if le else ">"
    out: list[Chunk] = []
    while off + 16 <= end:
        tag = _tag_at(data, off, le)
        if tag is None:
            raise SdassetError(f"no chunk tag at {off:#x}")
        ver, arg, size = struct.unpack_from(e + "III", data, off + 4)
        flags, ver = ver >> 24, ver & 0xFFFFFF
        if tag in CONTAINERS or (le and flags):
            name, nlen = _cstr(data, off + 16, end)
            body = off + 16 + nlen
            kids = body + arg
            if kids + size > end:
                raise SdassetError(f"{tag} at {off:#x} overruns its parent")
            c = Chunk(tag, ver, flags, arg, size, off, body, kids + size, name)
            c.children = _walk(data, kids, kids + size, le, depth + 1)
            out.append(c)
        else:
            if off + 16 + size > end:
                raise SdassetError(f"{tag} at {off:#x} overruns its parent")
            out.append(Chunk(tag, ver, flags, arg, size, off, off + 16, off + 16 + size))
        off = out[-1].end
    if off != end:
        raise SdassetError(f"chunks end at {off:#x}, parent at {end:#x}")
    return out


@dataclass
class Segment:
    """One SDASSETF file (a team file holds several back to back)."""

    le: bool
    start: int
    end: int
    version: int
    chunks: list[Chunk]

    @property
    def endian(self) -> str:
        return "<" if self.le else ">"


def parse(data: bytes) -> list[Segment]:
    """Every SDASSETF segment in *data*, each tiled exactly by its chunks."""
    segs: list[Segment] = []
    off = 0
    n = len(data)
    while off + 16 <= n and data[off : off + 8] in (MAGIC_BE, MAGIC_LE):
        le = data[off : off + 8] == MAGIC_LE
        e = "<" if le else ">"
        ver, count = struct.unpack_from(e + "II", data, off + 8)
        # the header counts top-level chunks; walk that many, then look for the next file
        chunks: list[Chunk] = []
        p = off + 16
        for _ in range(count):
            got = _walk_one(data, p, n, le)
            chunks.append(got)
            p = got.end
        segs.append(Segment(le, off, p, ver, chunks))
        off = p
    if not segs:
        raise SdassetError("not an SDASSETF file")
    return segs


def _walk_one(data: bytes, off: int, end: int, le: bool) -> Chunk:
    """A single top-level chunk (its own span is decided by its header)."""
    tag = _tag_at(data, off, le)
    if tag is None:
        raise SdassetError(f"no chunk tag at {off:#x}")
    e = "<" if le else ">"
    ver, arg, size = struct.unpack_from(e + "III", data, off + 4)
    if tag in CONTAINERS or (le and ver >> 24):
        name, nlen = _cstr(data, off + 16, end)
        stop = off + 16 + nlen + arg + size
    else:
        stop = off + 16 + size
    if stop > end:
        raise SdassetError(f"{tag} at {off:#x} runs past the end of the file")
    return _walk(data, off, stop, le)[0]


def tiles(data: bytes) -> bool:
    """True when the chunk walk covers the file exactly (the identity check)."""
    try:
        segs = parse(data)
    except SdassetError:
        return False
    return segs[-1].end == len(data)


def iter_chunks(chunks: list[Chunk]):
    for c in chunks:
        yield c
        yield from iter_chunks(c.children)


# --- materials ---------------------------------------------------------------------------


@dataclass
class Material:
    name: str
    texture: str | None
    effects: list[tuple[str, str | None]]


def read_material(data: bytes, seg: Segment, c: Chunk) -> Material:
    effects: list[tuple[str, str | None]] = []
    for k in c.children:
        if k.tag != "EFCT":
            continue
        path, plen = _cstr(data, k.body, k.end)
        tex = None
        p = k.body + plen + 4
        if p < k.end and data[p] != 0:
            tex = _cstr(data, p, k.end)[0]
        effects.append((path, tex))
    texture = None
    for path, tex in effects:
        if tex and path.upper().endswith("TEXTURED"):
            texture = tex
            break
    if texture is None:
        for path, tex in effects:
            if tex and "SHADOW" not in path.upper():
                texture = tex
                break
    return Material(c.name or "", texture, effects)


# --- skeleton ----------------------------------------------------------------------------


@dataclass
class Skeleton:
    names: list[str]
    parents: list[int]
    world: np.ndarray  # (n, 4, 4) column-vector world bind matrices

    def locals(self) -> list[tuple[tuple, tuple, tuple]]:
        """(translation, quaternion xyzw, scale) per bone, parent-relative."""
        out = []
        for i, p in enumerate(self.parents):
            m = self.world[i]
            if 0 <= p < len(self.parents):
                with contextlib.suppress(np.linalg.LinAlgError):
                    m = np.linalg.inv(self.world[p]) @ m
            r = m[:3, :3]
            scale = np.linalg.norm(r, axis=0)
            scale[scale == 0] = 1.0
            rot = r / scale
            if np.linalg.det(rot) < 0:
                rot[:, 0] *= -1
                scale[0] *= -1
            out.append(
                (tuple(float(x) for x in m[:3, 3]), _quat(rot), tuple(float(x) for x in scale))
            )
        return out


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    t = float(np.trace(m))
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    else:
        i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
        if i == 0:
            s = math.sqrt(max(1.0 + m[0, 0] - m[1, 1] - m[2, 2], 0.0)) * 2 or 1.0
            q = (
                0.25 * s,
                (m[0, 1] + m[1, 0]) / s,
                (m[0, 2] + m[2, 0]) / s,
                (m[2, 1] - m[1, 2]) / s,
            )
        elif i == 1:
            s = math.sqrt(max(1.0 + m[1, 1] - m[0, 0] - m[2, 2], 0.0)) * 2 or 1.0
            q = (
                (m[0, 1] + m[1, 0]) / s,
                0.25 * s,
                (m[1, 2] + m[2, 1]) / s,
                (m[0, 2] - m[2, 0]) / s,
            )
        else:
            s = math.sqrt(max(1.0 + m[2, 2] - m[0, 0] - m[1, 1], 0.0)) * 2 or 1.0
            q = (
                (m[0, 2] + m[2, 0]) / s,
                (m[1, 2] + m[2, 1]) / s,
                0.25 * s,
                (m[1, 0] - m[0, 1]) / s,
            )
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return tuple(float(x / n) for x in q)


def read_skeleton(data: bytes, seg: Segment, c: Chunk) -> Skeleton:
    e = seg.endian
    n, names_size = struct.unpack_from(e + "II", data, c.body)
    if n > MAX_BONES or c.body + 8 + names_size + 72 * n > c.end:
        raise SdassetError(f"SKEL claims {n} bones in {c.size} bytes")
    p = c.body + 8
    blob = data[p : p + names_size]
    names = [s.decode("latin1") for s in blob.split(b"\0") if s][:n]
    names += [f"bone{i}" for i in range(len(names), n)]
    p += names_size
    parents = [int(x) for x in struct.unpack_from(e + f"{n}i", data, p)]
    p += 4 * n
    rows = np.frombuffer(data, e + "f4", 16 * n, p).reshape(n, 4, 4).astype(np.float64)
    # row-vector convention on disk: v' = v @ M, translation in the last row
    return Skeleton(names, parents, rows.transpose(0, 2, 1).copy())


# --- geometry ----------------------------------------------------------------------------


@dataclass
class VertexBuffer:
    ident: int
    stride: int
    attrs: list[int]
    positions: np.ndarray  # (N, 3) f32
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None  # (N, 4) u8
    blocks: list[tuple[list[int], int]]  # (bone palette, vertex count) per skinning block
    complete: bool  # every block found where expected


def _block_header(data: bytes, e: str, p: int, end: int) -> tuple[list[int], int, int] | None:
    if p + 8 > end:
        return None
    n = struct.unpack_from(e + "I", data, p)[0]
    if not 1 <= n <= MAX_BONES_PER_BLOCK or p + 8 + 4 * n > end:
        return None
    bones = list(struct.unpack_from(e + f"{n}I", data, p + 4))
    if any(b >= 4096 for b in bones) or bones != sorted(set(bones)):
        return None
    nv = struct.unpack_from(e + "I", data, p + 4 + 4 * n)[0]
    if not 0 < nv < 1 << 20:
        return None
    return bones, nv, p + 8 + 4 * n


def read_data(data: bytes, seg: Segment, c: Chunk, expect: int | None = None) -> VertexBuffer:
    """*expect* is the matching WGHT count: the true vertex total once skinning blocks
    are appended.  Blocks are located by their headers; the ``nv * (n-1)`` bone-space copies
    that follow a block are skipped, and when that arithmetic does not land on the next
    header (seen once on a 79-vertex mouth block) the header is searched for instead."""
    e = seg.endian
    _, ident, stride, count = struct.unpack_from(e + "IIII", data, c.body)
    attrs: list[int] = []
    for b in data[c.body + 16 : c.body + 24]:
        if b == 0x80 or b == 0:
            break
        attrs.append(b)
    if stride <= 0 or count < 0:
        raise SdassetError(f"DATA {ident}: stride {stride} count {count}")
    p = c.body + 32
    if p + count * stride > c.end:
        raise SdassetError(f"DATA {ident}: {count} x {stride} does not fit")
    raw = [np.frombuffer(data, np.uint8, count * stride, p).reshape(count, stride)]
    p += count * stride
    blocks: list[tuple[list[int], int]] = []
    complete = True
    nblocks = struct.unpack_from(e + "I", data, p)[0] if p + 4 <= c.end else 0
    p += 4
    scan_from = p
    remaining = None if expect is None else expect - count
    for _ in range(nblocks):
        hdr = _block_header(data, e, p, c.end)
        if hdr is None or (remaining is not None and hdr[1] > remaining):
            # the copies did not measure up: the header lies somewhere after the last
            # block's vertices, and the WGHT count says how big it must be
            hdr = None
            q = scan_from
            while q + 8 <= c.end:
                got = _block_header(data, e, q, c.end)
                if got is not None and (remaining is None or got[1] <= remaining):
                    hdr = got
                    break
                q += 4
            if hdr is None:
                complete = False
                break
        bones, nv, vp = hdr
        if vp + nv * stride > c.end:
            complete = False
            break
        raw.append(np.frombuffer(data, np.uint8, nv * stride, vp).reshape(nv, stride))
        blocks.append((bones, nv))
        if remaining is not None:
            remaining -= nv
        scan_from = vp + nv * stride
        p = scan_from + nv * (len(bones) - 1) * stride
    vb = np.concatenate(raw)
    if expect is not None and len(vb) != expect:
        complete = False
        if len(vb) > expect:
            vb = vb[:expect]
    return VertexBuffer(ident, stride, attrs, *_split_attrs(vb, attrs, stride, e), blocks, complete)


def _split_attrs(vb: np.ndarray, attrs: list[int], stride: int, e: str):
    n = len(vb)
    if sum(ATTR_SIZES.get(a, 0) for a in attrs) != stride or 1 not in attrs:
        attrs = [1]  # unknown layout: positions lead, the rest is left alone
    positions = normals = uvs = colors = None
    off = 0
    for a in attrs:
        size = ATTR_SIZES.get(a)
        if size is None or off + size > stride:
            break
        col = np.ascontiguousarray(vb[:, off : off + size])
        if a == 1:
            positions = col.view(e + "f4").reshape(n, 3).astype(np.float32)
        elif a == 2 and normals is None:
            normals = col.view(e + "f4").reshape(n, 3).astype(np.float32)
        elif a == 4 and uvs is None:
            uvs = col.view(e + "f4").reshape(n, 2).astype(np.float32)
        elif a == 3 and colors is None:
            colors = col.reshape(n, 4).copy()
        off += size
    if positions is None:
        positions = np.zeros((n, 3), np.float32)
    return positions, normals, uvs, colors


def read_weights(data: bytes, seg: Segment, c: Chunk) -> list[tuple[list[int], list[float]]]:
    e = seg.endian
    n = struct.unpack_from(e + "I", data, c.body)[0]
    p = c.body + 4
    out = []
    for _ in range(n):
        if p + 4 > c.end:
            break
        k = struct.unpack_from(e + "I", data, p)[0]
        if k > 64 or p + 4 + 8 * k > c.end:
            break
        bones = list(struct.unpack_from(e + f"{k}I", data, p + 4))
        w = list(struct.unpack_from(e + f"{k}f", data, p + 4 + 4 * k))
        out.append((bones, w))
        p += 4 + 8 * k
    return out


@dataclass
class Mesh:
    ident: int
    name: str
    data_id: int
    bbox: tuple
    strips: list[np.ndarray]  # index arrays into the vertex buffer
    trailers: list[int]
    complete: bool


def read_mesh(data: bytes, seg: Segment, c: Chunk) -> Mesh:
    """Version 5 (the players and stadiums) puts the bbox first, version 3 (``intro``
    props) the id / index count / strip count first; both keep the 4 attribute words and
    96 reserved bytes before the strips.  Each strip's index block is padded to 4 bytes
    before its trailer word (0, or 1 on the last strip of a run)."""
    e = seg.endian
    name, nlen = _cstr(data, c.body, c.end)
    q = c.body + nlen
    if c.version >= 5:
        bbox = struct.unpack_from(e + "6f", data, q)
        w = struct.unpack_from(e + "8I", data, q + 24)
        ident, data_id = w[0], w[7]
        q += 56
    else:
        ident = struct.unpack_from(e + "I", data, q)[0]
        bbox = struct.unpack_from(e + "6f", data, q + 12)
        data_id = struct.unpack_from(e + "I", data, q + 44)[0]
        q += 48
    descs = struct.unpack_from(e + "8I", data, q)
    nattr = sum(1 for i in range(0, 8, 2) if descs[i]) or 1
    width = (descs[0] >> 16) & 0xFF
    if width not in (1, 2, 4):
        width = 2
    dt = e + {1: "u1", 2: "u2", 4: "u4"}[width]
    p = q + 32 + 96
    strips: list[np.ndarray] = []
    trailers: list[int] = []
    complete = True
    while p + 4 <= c.end:
        n = struct.unpack_from(e + "I", data, p)[0]
        p += 4
        need = n * nattr * width
        if n == 0 or p + need > c.end:
            complete = False
            break
        idx = np.frombuffer(data, dt, n * nattr, p).reshape(n, nattr)[:, 0].astype(np.uint32)
        strips.append(idx)
        p += (need + 3) // 4 * 4
        if p + 4 <= c.end:
            trailers.append(struct.unpack_from(e + "I", data, p)[0])
            p += 4
        else:
            trailers.append(0)
    if p != c.end:
        complete = False
    return Mesh(ident, name, data_id, bbox, strips, trailers, complete)


def triangulate(strips: list[np.ndarray], flip: bool = False) -> np.ndarray:
    """Triangle strips -> (M, 3) uint32, degenerate triangles dropped."""
    out = []
    for s in strips:
        n = len(s)
        if n < 3:
            continue
        a, b, c = s[:-2], s[1:-1], s[2:]
        tri = np.stack([a, b, c], axis=1).astype(np.uint32)
        odd = np.arange(n - 2) % 2 == (0 if flip else 1)
        tri[odd, 0], tri[odd, 1] = tri[odd, 1].copy(), tri[odd, 0].copy()
        keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
        out.append(tri[keep])
    return np.concatenate(out) if out else np.zeros((0, 3), np.uint32)


@dataclass
class Model:
    name: str
    buffers: dict[int, VertexBuffer]
    weights: dict[int, list]
    meshes: list[Mesh]
    lods: list[tuple[float, list[int]]]

    def detail_meshes(self) -> list[Mesh]:
        """The full-detail LOD's meshes (every mesh when the model has no LOD table)."""
        if not self.lods:
            return self.meshes
        dist, ids = min(self.lods, key=lambda t: (t[0], -len(t[1])))
        keep = set(ids)
        picked = [m for m in self.meshes if m.ident in keep]
        return picked or self.meshes


def read_model(data: bytes, seg: Segment, c: Chunk) -> Model:
    e = seg.endian
    weights: dict[int, list] = {}
    for k in c.children:
        if k.tag == "WGHT":
            weights[k.arg] = read_weights(data, seg, k)
    buffers: dict[int, VertexBuffer] = {}
    meshes: list[Mesh] = []
    lods: list[tuple[float, list[int]]] = []
    for k in c.children:
        if k.tag == "DATA":
            # MESH refers to the chunk index (the body id is 0 on rigid / older files)
            wg = weights.get(k.arg)
            vb = read_data(data, seg, k, len(wg) if wg else None)
            vb.ident = k.arg
            buffers[k.arg] = vb
        elif k.tag == "MESH":
            meshes.append(read_mesh(data, seg, k))
        elif k.tag == "LOD":
            # f32 distance, skeleton name (empty on rigid models), u32 n, mesh ids, then
            # per-mesh vertex/bone counts this reader does not need
            dist = struct.unpack_from(e + "f", data, k.body)[0]
            _, nlen = _cstr(data, k.body + 4, k.end)
            p = k.body + 4 + nlen
            n = struct.unpack_from(e + "I", data, p)[0] if p + 4 <= k.end else 0
            n = min(n, max(0, (k.end - p - 4) // 4))
            ids = list(struct.unpack_from(e + f"{n}I", data, p + 4))
            lods.append((float(dist), ids))
    return Model(c.name or "", buffers, weights, meshes, lods)


# --- textures ----------------------------------------------------------------------------


@dataclass
class Bitmap:
    name: str
    width: int
    height: int
    fmt: int  # GX texture format
    pixels: bytes


def read_bitmap(data: bytes, seg: Segment, c: Chunk) -> Bitmap | None:
    e = seg.endian
    if c.arg < 20:
        return None
    w, h = struct.unpack_from(e + "HH", data, c.body)
    compressed = data[c.body + 15]
    bpp = data[c.body + 16]
    if compressed == 7 or bpp == 32 and data[c.body + 17] == 1:
        fmt = 14
    else:
        fmt = {4: 0, 8: 1, 16: 5, 32: 6}.get(bpp)
    if fmt is None:
        return None
    for k in c.children:
        if k.tag == "IMAG" and data[k.body : k.body + 2] == b"GC":
            return Bitmap(c.name or "", w, h, fmt, data[k.body + 4 : k.end])
    return None


def decode_bitmap(bm: Bitmap) -> np.ndarray | None:
    try:
        return gx_texture.decode(bm.fmt, bm.width, bm.height, bm.pixels)
    except ValueError:
        return None


# --- whole files -------------------------------------------------------------------------


@dataclass
class Asset:
    segment: Segment
    materials: list[Material]
    skeleton: Skeleton | None
    models: list[Model]
    bitmaps: list[Bitmap]

    @property
    def name(self) -> str:
        if len(self.models) == 1:
            return self.models[0].name
        return ""

    def material(self, name: str) -> Material | None:
        best = None
        for m in self.materials:
            if m.name == name:
                if m.texture:
                    return m
                best = best or m
        return best


def read(data: bytes) -> list[Asset]:
    """Every asset file in *data* (one per SDASSETF segment)."""
    out = []
    for seg in parse(data):
        materials: list[Material] = []
        skeleton = None
        models: list[Model] = []
        bitmaps: list[Bitmap] = []
        for c in seg.chunks:
            if c.tag == "MTRL":
                materials.append(read_material(data, seg, c))
            elif c.tag == "SKEL":
                skeleton = read_skeleton(data, seg, c)
            elif c.tag == "MDL":
                models.append(read_model(data, seg, c))
            elif c.tag == "BMAP":
                bm = read_bitmap(data, seg, c)
                if bm is not None:
                    bitmaps.append(bm)
        out.append(Asset(seg, materials, skeleton, models, bitmaps))
    return out
