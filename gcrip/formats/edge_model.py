"""Edge of Reality resources - ``MODL`` models, ``TXFL`` textures and ``SHDR`` shaders inside the
``index.ind`` + ``.arc`` archives (The Sims 2, The Sims 2 Pets, The Urbz, and the older Sims /
Shark Tale / Over the Hedge discs on the same engine).

Read from The Sims 2's ``u2_ngc_release_dvd.elf`` with its shipped ``.map``: ``ERModel::LoadModel``,
``ESubModel::Read``, ``ESubModelShader::Read`` and its ``ReadPositions`` .. ``ReadIndices``,
``ERTexture::LoadFromMemory`` + ``ENgcTexture::Create``, ``ERShader::CopyShedData`` and
``ENgcRenderer::InitGXVertexFormats`` for the vertex attribute formats.  Big-endian.

Every member (``EDataHeader``)::

  u32 version, char[4] tag ("MODL" / "TXFL" / "SHDR" / "DTST"), u32 -1, u32 n, name[n], u32 size,
  size bytes of payload

Model payload (versions 0x39 .. 0x3e; The Sims 2 writes 0x3a, Pets 0x3e)::

  u32, 48 bytes, u8
  u32 n, n x 64                         attachment vertices
  u32 n, n x BSplineVolume              u32 tag (non-zero: nothing else), 0x80, u32,
                                        u32 nx, ny, nz, u32 sets, sets > 1: sets*nx*ny*nz x f32[3]
  u32 n, n x ENDummy                    u32 tag, name[64], u32, u32 k, k x 0x50
  u32 n, n x ENCamera                   u32 tag, name[64], u32, u32 k, k x 0x60
  u32 n, n x 28                         SimsLightInfo
  u8 flag, f32 scale, u32 nsubmodels
  submodel: u32, u32 nshaders, shaders
  shader:   u32 flags, u32 shader hash, u32 nstrips, nstrips x u8, u32, then tokens:
            0  a strip: u32 nverts, positions (s16[4] if flags & 0x10 else f32[4]),
               UVs if flags & 2 (2 or, with 0x40, 4 components; s16/4096 if flags & 0x10 else f32),
               RGBA8 colours if flags & 4, s8[4] normals if flags & 8 (s8[3] up to version 0x39),
               u8[4] weights while skinned,
               and if flags & 0x20 a display list: u32 corners, u8, u32 size, u32, size bytes
            1  u16, u8 (bone binding)   2/4  skinned on   3/5  skinned off   6  end
  f32[4] bound sphere, f32[6] bounds, f32[6] bounds, u8[4]

A strip without a display list is a triangle strip over its vertices in order.  With one, the
display list's corners are u16 indices into the strip's arrays, one per attribute present
(position, normal, colour, texcoords).  Positions are ``s16 * scale``.

Texture payload: a 32-byte ``ETextureDef`` - ``u32, u32, u32 flags, u32, u16 w, u16 h,
u16 palette entries, u16 mips, u8 format, u8, u8 bpp, u8 palette bpp, u32`` - then the mip
chain, then the palette.  Formats: 0x81 CMPR, 0x82 RGB5A3, 0x83 C4 and 0x84 C8 over a 16-bit
palette, 0x85 / 1 RGBA8, 0x89 C4 and 0x8a C8 over a 32-bit palette.  The pixels are GX-tiled.
A 32-bit palette on disc (flags bit 7) is two IA8 TLUTs: ``(B, R)`` words then ``(A, G)``.

Shader payload (``EShaderDef``): u8 textures, u8, u16, u32 x 3, 48 bytes, 9 x u32, then 64-byte
layers whose first u32 is the texture's name hash - the same hash the index files it under
(``crc32`` of the upper-cased name).  Pets' version 0x18 starts its 48-byte layers at 0x3b.

Texture format 0x88 (Shark Tale / Over the Hedge) is a CMPR colour image followed by a CMPR
image whose grey level is the alpha.  A face template (``af_ft_chin_strong``: per-vertex
position deltas, mostly zero) is applied over its base face by ``apply_morph``.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

MODEL, TEXTURE, SHADER, DATASET = b"MODL", b"TXFL", b"SHDR", b"DTST"
MODEL_VERSIONS = range(0x39, 0x40)  # 0x3a The Sims 2, 0x3e The Sims 2 Pets
OLD_NORMALS = 0x39  # ReadNormalsOld: three bytes a normal up to this version

F_UV, F_COLOR, F_NORMAL, F_PACKED, F_DL, F_UV4 = 2, 4, 8, 0x10, 0x20, 0x40
UV_SCALE = 1.0 / 4096.0
NORMAL_SCALE = 1.0 / 64.0

TEX_FORMATS = {0x81: 0xE, 0x82: 5, 0x83: 8, 0x84: 9, 0x85: 6, 1: 6, 0x88: 0xE, 0x89: 8, 0x8A: 9}
CMPR_ALPHA = 0x88  # Shark Tale / Over the Hedge: a CMPR colour image, then a CMPR alpha image
PRE_SPLIT_PALETTE = 0x80

# EShaderDef layouts by member version: (bytes before the first layer, bytes a layer); the
# layer's first u32 is the texture's name hash.  The Sims 2 writes 0x16, Pets 0x18.
SHADER_LAYOUTS = ((0x18, (0x3B, 0x30)), (0, (0x64, 0x40)))


class EdgeError(ValueError):
    pass


@dataclass
class Header:
    version: int
    tag: bytes
    name: str
    payload: bytes


def header(data: bytes) -> Header | None:
    if len(data) < 20:
        return None
    version, tag, _rid, n = struct.unpack_from(">I4sII", data, 0)
    if tag not in (MODEL, TEXTURE, SHADER, DATASET) or n > 256 or 16 + n + 4 > len(data):
        return None
    name = data[16 : 16 + n].split(b"\0")[0].decode("latin-1")
    size = struct.unpack_from(">I", data, 16 + n)[0]
    at = 20 + n
    if at + size > len(data):
        return None
    return Header(version, tag, name, data[at : at + size])


def is_model(head: bytes) -> bool:
    return (
        len(head) >= 8
        and head[4:8] == MODEL
        and struct.unpack_from(">I", head)[0] in MODEL_VERSIONS
    )


def is_texture(head: bytes) -> bool:
    return len(head) >= 8 and head[4:8] == TEXTURE


def is_shader(head: bytes) -> bool:
    return len(head) >= 8 and head[4:8] == SHADER


def is_old_model(head: bytes) -> bool:
    """The Sims (2003) ``models.arc`` member: ``u32 0, u16 0`` then the name."""
    if len(head) < 12 or head[:4] not in (bytes(4), bytes((0, 1, 0, 0))) or head[4:6] != bytes(2):
        return False
    end = head.find(bytes(1), 6, 64)
    return end > 6 and all(32 <= c < 127 for c in head[6:end])


def any_texture(data: bytes) -> Texture:
    """A ``TXFL`` member or a dataset ``LFXT`` entry, whichever this is."""
    if is_texture(data[:8]):
        return parse_texture(data)
    return parse_entry_texture(data)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.d = data
        self.p = 0

    def need(self, n: int) -> None:
        if n < 0 or self.p + n > len(self.d):
            raise EdgeError(f"payload ends at {len(self.d)} inside a {n}-byte field at {self.p}")

    def u8(self) -> int:
        self.need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from(">I", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        self.need(4)
        v = struct.unpack_from(">f", self.d, self.p)[0]
        self.p += 4
        return v

    def raw(self, n: int) -> bytes:
        self.need(n)
        v = self.d[self.p : self.p + n]
        self.p += n
        return v


@dataclass
class Strip:
    shader: int  # name hash
    flags: int
    positions: np.ndarray  # (N,3) f32, scaled
    normals: np.ndarray | None
    colors: np.ndarray | None
    uvs: np.ndarray | None
    indices: np.ndarray  # (M,) u32 triangles
    skinned: bool
    ordinal: int = 0  # position among the model's strip tokens, in file order


@dataclass
class Model:
    name: str
    version: int
    scale: float
    strips: list[Strip] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _skip_nodes(r: _Reader) -> None:
    n = r.u32()
    r.raw(n * 64)  # attachment vertices
    for what in ("spline", "dummy", "camera"):
        for _ in range(r.u32()):
            if r.u32() != 0:
                continue
            if what == "spline":
                r.raw(0x80)
                r.u32()
                nx, ny, nz, sets = r.u32(), r.u32(), r.u32(), r.u32()
                if sets > 1:
                    r.raw(sets * nx * ny * nz * 12)
            else:
                r.raw(0x40)
                r.u32()
                k = r.u32()
                r.raw(k * (0x50 if what == "dummy" else 0x60))
    r.raw(r.u32() * 28)  # lights


def _strip_triangles(n: int) -> np.ndarray:
    i = np.arange(max(n - 2, 0))
    b = np.where(i % 2 == 0, i + 1, i + 2)
    c = np.where(i % 2 == 0, i + 2, i + 1)
    return np.stack([i, b, c], axis=1)


def _display_list(
    dl: bytes, width: int, name: str, warnings: list[str]
) -> list[tuple[int, np.ndarray]]:
    """(opcode, (count, width) u16 corner records) for every primitive in the list."""
    out = []
    p = 0
    while p + 3 <= len(dl):
        op = dl[p]
        if op == 0:
            break
        count = struct.unpack_from(">H", dl, p + 1)[0]
        if (op & 0xF8) not in (0x80, 0x90, 0x98, 0xA0) or p + 3 + count * width * 2 > len(dl):
            warnings.append(f"{name}: display list breaks at {p} (opcode {op:#x}, {count} corners)")
            break
        rec = np.frombuffer(dl[p + 3 : p + 3 + count * width * 2], dtype=">u2").reshape(
            count, width
        )
        out.append((op & 0xF8, rec.astype(np.int64)))
        p += 3 + count * width * 2
    return out


def _triangles(op: int, n: int) -> np.ndarray:
    if op == 0x98:
        return _strip_triangles(n)
    if op == 0x90:
        return np.arange(n - n % 3).reshape(-1, 3)
    if op == 0xA0:
        i = np.arange(1, max(n - 1, 1))
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    q = np.arange(n // 4) * 4
    return np.concatenate(
        [np.stack([q, q + 1, q + 2], axis=1), np.stack([q, q + 2, q + 3], axis=1)]
    )


def _read_strip(
    r: _Reader,
    flags: int,
    shader: int,
    skinned: bool,
    scale: float,
    version: int,
    name: str,
    warnings: list[str],
    keep_all: bool = False,
) -> Strip | None:
    """One strip token.  ``keep_all`` returns a Strip with no triangles where a strip holds
    none (fewer than three vertices, or degenerate joins only) instead of dropping it, so a
    morph target's per-strip deltas stay aligned with its base."""
    n = r.u32()
    if flags & F_PACKED:
        pos = (
            np.frombuffer(r.raw(n * 8), dtype=">i2").reshape(-1, 4)[:, :3].astype(np.float32)
            * scale
        )
    else:
        pos = np.frombuffer(r.raw(n * 16), dtype=">f4").reshape(-1, 4)[:, :3].astype(np.float32)
    uv = None
    if flags & F_UV:
        comps = 4 if flags & F_UV4 else 2
        if flags & F_PACKED:
            uv = (
                np.frombuffer(r.raw(n * comps * 2), dtype=">i2")
                .reshape(-1, comps)[:, :2]
                .astype(np.float32)
                * UV_SCALE
            )
        else:
            uv = (
                np.frombuffer(r.raw(n * comps * 4), dtype=">f4")
                .reshape(-1, comps)[:, :2]
                .astype(np.float32)
            )
    clr = None
    if flags & F_COLOR:
        clr = np.frombuffer(r.raw(n * 4), dtype=np.uint8).reshape(-1, 4).copy()
        clr[:, 3] = 255
    nrm = None
    if flags & F_NORMAL:
        width = 3 if version <= OLD_NORMALS else 4
        nrm = (
            np.frombuffer(r.raw(n * width), dtype=np.int8)
            .reshape(-1, width)[:, :3]
            .astype(np.float32)
            * NORMAL_SCALE
        )
    if skinned:
        r.raw(n * 4)
    if flags & F_DL:
        r.u32()  # corners
        r.u8()
        size = r.u32()
        r.u32()
        dl = r.raw(size)
        width = 1 + bool(flags & F_NORMAL) + bool(flags & F_COLOR) + bool(flags & F_UV)
        prims = _display_list(dl, width, name, warnings)
        if not prims:
            warnings.append(f"{name}: display list holds no primitive")
            return None
        # every attribute of a corner indexes the same vertex; the position column is enough
        idx = np.concatenate([rec[:, 0] for _, rec in prims])
        tris = []
        base = 0
        for op, rec in prims:
            tris.append(_triangles(op, len(rec)) + base)
            base += len(rec)
        tri = np.concatenate(tris)
        if idx.max(initial=0) >= n:
            warnings.append(f"{name}: display list indexes {int(idx.max())} of {n} vertices")
            return None
        tri = idx[tri]
    else:
        tri = _strip_triangles(n)  # fewer than three vertices: no triangle, legitimately
    # strip joins repeat a vertex by index or by position; either way it is not a triangle
    a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
    good = ~(np.all(a == b, axis=1) | np.all(b == c, axis=1) | np.all(a == c, axis=1))
    tri = tri[good]
    if not len(tri) and not keep_all:
        return None  # legitimate: a strip of degenerate joins only
    return Strip(shader, flags, pos, nrm, clr, uv, tri.reshape(-1).astype(np.uint32), skinned)


def parse_model(data: bytes) -> Model:
    """A ``MODL`` member with its EDataHeader (The Sims 2, Pets)."""
    h = header(data)
    if h is None or h.tag != MODEL:
        raise EdgeError("not an Edge of Reality model")
    if h.version not in MODEL_VERSIONS:
        raise EdgeError(f"{h.name}: model version {h.version:#x}")
    return parse_payload(h.payload, h.version, h.name)


def parse_payload(
    payload: bytes,
    version: int,
    name: str = "",
    leading_name: bool = False,
    node_arrays: bool = True,
    extra_word: bool = True,
    keep_all: bool = False,
) -> Model:
    """The model data behind a header.

    ``leading_name``: The Urbz writes the model's name as a NUL-terminated string in front
    (its dataset entries have an empty header name).  ``node_arrays``: The Sims (2003) has no
    attachment / spline / dummy / camera / light arrays and no 48-byte block, only the flag and
    the scale.  ``extra_word``: the u32 after the strip count that The Sims (2003) lacks.
    ``keep_all``: keep triangle-less strips too (see ``_read_strip``)."""
    r = _Reader(payload)
    ordinal = 0
    if leading_name:
        end = payload.find(b"\0")
        if end < 0:
            raise EdgeError("model name runs off the payload")
        name = payload[:end].decode("latin-1")
        r.p = end + 1
    if node_arrays:
        r.u32()
        r.raw(0x30)
        r.u8()
        _skip_nodes(r)
    r.u8()
    scale = r.f32() or 1.0
    model = Model(name, version, scale)
    for _ in range(r.u32()):
        r.u32()
        for _ in range(r.u32()):
            flags = r.u32()
            shader = r.u32()
            nstrips = r.u32()
            r.raw(nstrips)
            if extra_word:
                r.u32()
            skinned = False
            while True:
                op = r.u8()
                if op == 6:
                    break
                if op == 0:
                    strip = _read_strip(
                        r, flags, shader, skinned, scale, version, name, model.warnings, keep_all
                    )
                    if strip is not None:
                        strip.ordinal = ordinal
                        model.strips.append(strip)
                    ordinal += 1
                elif op == 1:
                    r.u16()
                    r.u8()
                elif op in (2, 4):
                    skinned = True
                elif op in (3, 5):
                    skinned = False
                else:
                    raise EdgeError(f"{name}: token {op} at {r.p - 1}")
    r.raw(16 + 24 + 24 + 4)
    if len(payload) - r.p > 8:
        model.warnings.append(f"{name}: {len(payload) - r.p} bytes after the bounds")
    return model


# ---------------------------------------------------------------- morph targets

MORPH_ZERO_SHARE = 0.5
MORPH_MATCH_SHARE = 0.8


def is_morph_target(model: Model) -> bool:
    """A face template (The Sims 2 / Pets ``af_ft_chin_strong``, ``d_fmt_Growl`` ...) is a
    model whose strips hold per-vertex position *deltas* over a base face: most of them are
    exactly zero.  Needs a ``keep_all`` parse so every strip is seen."""
    total = sum(len(s.positions) for s in model.strips)
    if not total:
        return False
    zero = sum(int(np.all(s.positions == 0, axis=1).sum()) for s in model.strips)
    return zero / total >= MORPH_ZERO_SHARE


def apply_morph(base: Model, morph: Model) -> Model | None:
    """``base`` with ``morph``'s deltas added strip by strip (matched by ordinal and vertex
    count), named after the morph; None when fewer than MORPH_MATCH_SHARE of the base's
    strips have a delta of the same size."""
    deltas = {s.ordinal: s.positions for s in morph.strips}
    matched = {
        s.ordinal
        for s in base.strips
        if s.ordinal in deltas and len(deltas[s.ordinal]) == len(s.positions)
    }
    if not base.strips or len(matched) < MORPH_MATCH_SHARE * len(base.strips):
        return None
    out = Model(morph.name, base.version, base.scale, warnings=list(base.warnings))
    for s in base.strips:
        pos = s.positions
        if s.ordinal in matched:
            pos = (pos + deltas[s.ordinal]).astype(np.float32)
        out.strips.append(
            Strip(
                s.shader, s.flags, pos, s.normals, s.colors, s.uvs, s.indices, s.skinned, s.ordinal
            )
        )
    out.warnings.append(f"{morph.name}: morph target applied over {base.name}")
    if len(matched) < len(base.strips):
        out.warnings.append(
            f"{morph.name}: {len(base.strips) - len(matched)} of {len(base.strips)} strips "
            f"have no matching delta in the morph"
        )
    return out


# ---------------------------------------------------------------- textures and shaders


@dataclass
class Texture:
    name: str
    width: int
    height: int
    format: int
    rgba: np.ndarray


def _palette(raw: bytes, entries: int, bpe: int, pre_split: bool) -> np.ndarray:
    if bpe == 16:
        return gx_texture.decode_palette(2, raw, entries)  # RGB5A3 TLUT
    if pre_split:
        # two IA8 TLUTs: (B, R) words then (A, G) words
        t1 = np.frombuffer(raw[: entries * 2], dtype=np.uint8).reshape(-1, 2)
        t2 = np.frombuffer(raw[entries * 2 : entries * 4], dtype=np.uint8).reshape(-1, 2)
        return np.stack([t1[:, 1], t2[:, 1], t1[:, 0], t2[:, 0]], axis=1)
    e = np.frombuffer(raw[: entries * 4], dtype=np.uint8).reshape(-1, 4)
    return np.stack([e[:, 0], e[:, 2], e[:, 1], e[:, 3]], axis=1)


def parse_texture(data: bytes) -> Texture:
    h = header(data)
    if h is None or h.tag != TEXTURE:
        raise EdgeError("not an Edge of Reality texture")
    return _texture(h.name, h.payload)


def _texture(name: str, d: bytes) -> Texture:
    """A 32-byte ETextureDef, the mip chain and the palette."""
    if len(d) < 32:
        raise EdgeError(f"{name}: texture header short")
    flags = struct.unpack_from(">I", d, 8)[0]
    w, h_, entries, _mips = struct.unpack_from(">HHHH", d, 0x10)
    fmt, _f19, bpp, bpe = d[0x18:0x1C]
    if fmt not in TEX_FORMATS:
        raise EdgeError(f"{name}: texture format {fmt:#x}")
    if fmt == 0 and bpp in (4, 8):
        fmt = 0x89 if bpp == 4 else 0x8A
    gx = TEX_FORMATS[fmt]
    pixels = d[32:]
    palette = None
    if entries:
        pal_bytes = entries * bpe // 8
        if pal_bytes > len(pixels):
            raise EdgeError(f"{name}: palette past the payload")
        palette = _palette(
            pixels[len(pixels) - pal_bytes :], entries, bpe, bool(flags & PRE_SPLIT_PALETTE)
        )
        pixels = pixels[: len(pixels) - pal_bytes]
    elif gx in (8, 9):
        raise EdgeError(f"{name}: palette texture without a palette")
    need = gx_texture.encoded_size(gx, w, h_)
    if len(pixels) * 8 < w * h_ * gx_texture.BITS_PER_PIXEL[gx]:
        raise EdgeError(f"{name}: {len(pixels)} bytes for a {w}x{h_} level")
    rgba = gx_texture.decode(gx, w, h_, pixels[:need], palette)
    if fmt == CMPR_ALPHA:
        # the second half of the payload is a second CMPR image whose (grey) texels are the
        # alpha - CMPR itself only carries one bit of it
        half = len(pixels) // 2
        if half < need:
            raise EdgeError(f"{name}: {len(pixels)} bytes for a {w}x{h_} colour + alpha pair")
        rgba = rgba.copy()
        rgba[..., 3] = gx_texture.decode(gx, w, h_, pixels[half : half + need], None)[..., 1]
    return Texture(name, w, h_, fmt, rgba)


def shader_textures(data: bytes) -> list[int]:
    """Name hashes of the textures a shader layers, first layer first.

    Takes a ``SHDR`` member or an Urbz dataset entry (a header with an empty name, then the
    shader's name as a string, then the same ``EShaderDef``)."""
    h = header(data)
    if h is not None and h.tag == SHADER:
        d = h.payload
        version = h.version
    elif len(data) > 20 and data[4:16] == bytes(12) and data[:4] != bytes(4):
        version, size = struct.unpack_from(">I", data, 0)[0], struct.unpack_from(">I", data, 16)[0]
        end = data.find(bytes(1), 20)
        if end < 0 or 20 + size > len(data):
            raise EdgeError("shader name runs off the entry")
        d = data[end + 1 : 20 + size]
    else:
        raise EdgeError("not an Edge of Reality shader")
    head, layer = next(lay for least, lay in SHADER_LAYOUTS if version >= least)
    count = d[0] if d else 0
    out = []
    for i in range(min(count, 2)):
        at = head + i * layer
        if at + 4 > len(d):
            break
        ref = struct.unpack_from(">I", d, at)[0]
        if ref:
            out.append(ref)
    return out


# ---------------------------------------------------------------- dataset entries

OLD_TEXTURE_HEADER = 20


def _scale_at(data: bytes, start: int, limit: int = 48) -> int | None:
    """Offset of the ``f32 scale, u32 submodels, u32 id, u32 shaders`` run that opens the body."""
    for q in range(start, min(len(data) - 12, start + limit)):
        scale = struct.unpack_from(">f", data, q)[0]
        if not (2.0**-20 <= scale <= 16.0) or scale != 2.0 ** round(math.log2(scale)):
            continue
        nsub, ident, nsh = struct.unpack_from(">III", data, q + 4)
        if nsub == 0 and q == start + 1:
            return q  # an empty model: nothing but its bounds follow
        if 1 <= nsub <= 64 and (ident == 0xFFFFFFFF or ident < 0x10000) and 1 <= nsh <= 256:
            return q
    return None


def parse_entry_model(payload: bytes) -> Model:
    """A ``Models`` entry of a dataset (gcrip.formats.edge_dataset)."""
    from gcrip.formats import edge_dataset

    w = edge_dataset.model_wrapper(payload)
    if w is None:
        raise EdgeError("not a dataset model entry")
    name, at, version = w
    if version:
        size = struct.unpack_from(">I", payload, 16)[0]
        return parse_payload(payload[20 : 20 + size], version, leading_name=True)
    q = _scale_at(payload, at)
    if q is None:
        raise EdgeError(f"{name}: no scale / submodel count after the name")
    # Shark Tale / Over the Hedge open the shader record with the name hash, The Sims with
    # a small flags word
    first = struct.unpack_from(">I", payload, q + 16)[0] if q + 20 <= len(payload) else 0
    if first >= 0x10000:
        return parse_hedge_payload(payload, name, q - 1)
    # the older exporters: no node arrays, the flag byte right before the scale, and Bustin'
    # Out (first word 0x00010000) writes the u32 after the strip count that The Sims lacks
    extra = payload[:4] != bytes(4)
    return parse_payload(payload[q - 1 :], version, name, node_arrays=False, extra_word=extra)


def parse_entry_texture(payload: bytes) -> Texture:
    """A ``Textures`` entry of a dataset: ``LFXT``, a name, the header and the pixels."""
    from gcrip.formats import edge_dataset

    w = edge_dataset.texture_wrapper(payload)
    if w is None:
        raise EdgeError("not a dataset texture entry")
    name, at = w
    if payload[4:8] == edge_dataset.URBZ_TEXTURE:
        return _texture(name, payload[at:])
    if at + OLD_TEXTURE_HEADER > len(payload):
        raise EdgeError(f"{name}: texture header short")
    fmt, bpp, width, height, _f19, bpe, entries, flags, _x, mips = struct.unpack_from(
        ">BBHHBBHIIH", payload, at
    )
    # rebuild the 32-byte header the newer discs write and share the decoder
    hdr = struct.pack(">IIII", 0, 0, flags, 0) + struct.pack(">HHHH", width, height, entries, mips)
    hdr += bytes([fmt, 0, bpp, bpe]) + bytes(4)
    return _texture(name, hdr + payload[at + OLD_TEXTURE_HEADER :])


# ---------------------------------------------------------------- Shark Tale / Over the Hedge

# The record's five array offsets: position (always 0), texcoords, colour, colour 1, and the
# two-bone skin weights (u8 pairs summing to 256; not exported).  The CP stride registers in
# the first chunk give the element widths (0xB2 colour, 0xB4 texcoord).
HEDGE_ARRAY_REG = {"clr": 0xB2, "clr1": 0xB3, "tex": 0xB4}
HEDGE_SLOTS = ((1, "tex"), (2, "clr"), (3, "clr1"))
HEDGE_TOKENS = {0x45: 8, 0x46: 12, 0x50: 16, 0x51: 0, 0x52: 0}  # bytes after each token


def _hedge_positions(seg: bytes, stride: int, scale: float) -> tuple[np.ndarray, np.ndarray | None]:
    """(positions, normals) of the position array.  A 12-byte record is ``s16 xyz`` and then
    an ``s16`` unit vector quantised like the positions (its length is ``1 / scale``): the
    vertex normal, which is why the corners' normal index equals their position index."""
    if stride == 6:
        return np.frombuffer(seg, dtype=">i2").reshape(-1, 3).astype(np.float32) * scale, None
    if stride == 12:
        rec = np.frombuffer(seg, dtype=">i2").reshape(-1, 6).astype(np.float32)
        nrm = rec[:, 3:6] * scale
        length = np.linalg.norm(nrm, axis=1, keepdims=True)
        return rec[:, :3] * scale, nrm / np.where(length > 0, length, 1.0)
    raise EdgeError(f"position stride {stride}")


def _hedge_array(key: str, seg: bytes, stride: int) -> np.ndarray:
    if key in ("clr", "clr1"):
        if stride == 2:
            return gx_texture._rgb565_to_rgba(np.frombuffer(seg, dtype=">u2").astype(np.uint16))
        if stride == 3:
            rgb = np.frombuffer(seg, dtype=np.uint8).reshape(-1, 3)
            return np.concatenate([rgb, np.full((len(rgb), 1), 255, np.uint8)], axis=1)
        if stride == 4:
            return np.frombuffer(seg, dtype=np.uint8).reshape(-1, 4).copy()
        raise EdgeError(f"colour stride {stride}")
    if stride == 4:
        return np.frombuffer(seg, dtype=">i2").reshape(-1, 2).astype(np.float32) * UV_SCALE
    if stride == 8:
        return np.frombuffer(seg, dtype=">f4").reshape(-1, 2).astype(np.float32)
    raise EdgeError(f"texcoord stride {stride}")


def _hedge_arrays(
    block: bytes, offsets: tuple[int, ...], strides: dict[int, int]
) -> dict[str, np.ndarray]:
    """The texcoord and colour arrays of a strip at their offsets, each running to the next
    offset (or the block's end), decoded by the CP stride register."""
    order = [
        (key, offsets[slot], strides.get(HEDGE_ARRAY_REG[key], 0))
        for slot, key in HEDGE_SLOTS
        if offsets[slot]
    ]
    ends = sorted(o for o in offsets[1:] if o) + [len(block)]
    arrays: dict[str, np.ndarray] = {}
    for key, at, stride in order:
        end = next(e for e in ends if e > at)
        if not stride:
            continue
        n = len(block[at:end]) // stride
        arrays[key] = _hedge_array(key, block[at : at + n * stride], stride)
    return arrays


def _hedge_display_list(dl: bytes):
    """(CP registers, VCD lo, VCD hi, [(opcode, corner records)]) of one display-list chunk."""
    regs: dict[int, int] = {}
    lo = hi = 0
    prims = []
    p = 0
    while p < len(dl):
        op = dl[p]
        if op == 0:
            p += 1
        elif op == 0x08 and p + 6 <= len(dl):
            reg = dl[p + 1]
            val = struct.unpack_from(">I", dl, p + 2)[0]
            regs[reg] = val
            if reg == 0x50:
                lo = val
            elif reg == 0x60:
                hi = val
            p += 6
        elif op == 0x10 and p + 5 <= len(dl):
            n = struct.unpack_from(">H", dl, p + 1)[0] + 1
            p += 5 + 4 * n
        elif (op & 0xF8) in (0x80, 0x90, 0x98, 0xA0) and p + 3 <= len(dl):
            count = struct.unpack_from(">H", dl, p + 1)[0]
            kinds = [(lo >> s) & 3 for s in (9, 11, 13, 15)] + [
                (hi >> s) & 3 for s in range(0, 16, 2)
            ]
            width = sum(1 if k == 2 else 2 if k == 3 else 0 for k in kinds)
            if width == 0 or p + 3 + count * width > len(dl):
                break
            rec = np.frombuffer(dl[p + 3 : p + 3 + count * width], dtype=np.uint8)
            prims.append((op & 0xF8, rec.reshape(count, width), lo, hi))
            p += 3 + count * width
        else:
            break
    return regs, lo, hi, prims


def _hedge_columns(prims: list) -> dict[str, np.ndarray]:
    """Corner columns over every primitive, in VCD order: position, normal, colour 0,
    colour 1, texcoords 0..7.  The VCD can change between primitives of one chunk (Shark
    Tale's HUD characters drop the normal mid-chunk), so each primitive is split under the
    descriptor that was live when it was drawn."""
    parts: dict[str, list[np.ndarray]] = {}
    for _op, rec, lo, hi in prims:
        keys = [
            (key, (lo >> s) & 3) for key, s in (("pos", 9), ("nrm", 11), ("clr", 13), ("clr1", 15))
        ]
        keys += [(f"tex{t}", (hi >> (2 * t)) & 3) for t in range(8)]
        at = 0
        for key, kind in keys:
            if kind == 3:
                parts.setdefault(key, []).append(rec[:, at].astype(np.int64) << 8 | rec[:, at + 1])
                at += 2
            elif kind == 2:
                parts.setdefault(key, []).append(rec[:, at].astype(np.int64))
                at += 1
    n = sum(len(rec) for _op, rec, _lo, _hi in prims)
    # an attribute a primitive lacks cannot be indexed for it: only columns present on every
    # primitive line up with the corners
    return {k: np.concatenate(v) for k, v in parts.items() if sum(map(len, v)) == n}


def parse_hedge_payload(payload: bytes, name: str, start: int) -> Model:
    """Shark Tale / Over the Hedge: each shader record is a name hash, nine words (flags,
    vertices, strips, block size, five array offsets), the arrays, a display-list chunk that
    sets the CP array pointers, an attribute table, a second chunk with the primitives, 6."""
    r = _Reader(payload)
    r.p = start
    r.u8()
    scale = r.f32() or 1.0
    model = Model(name, 0, scale)
    for _ in range(r.u32()):
        r.u32()
        for _ in range(r.u32()):
            shader = r.u32()
            words = struct.unpack(">9I", r.raw(36))
            nverts, block_size = words[1], words[3]
            block = r.raw(block_size)
            chunk1 = r.raw(r.u32())
            for _ in range(r.u8()):
                r.raw(5)
            n2 = r.u32()
            r.u32()  # corners in total
            chunk2 = r.raw(n2)
            r.raw(words[2])  # a byte a strip
            # then tokens to the 6: 0x45 (two words), 0x46 (three), 0x50 (four, the whale),
            # 0x51 / 0x52 (none)
            while True:
                token = r.u8()
                if token == 6:
                    break
                if token not in HEDGE_TOKENS:
                    raise EdgeError(f"{name}: token {token:#x} after a shader record")
                r.raw(HEDGE_TOKENS[token])
            regs, _lo, _hi, _prims = _hedge_display_list(chunk1)
            _regs, lo, hi, prims = _hedge_display_list(chunk2)
            if not prims:
                model.warnings.append(f"{name}: display list holds no primitive")
                continue
            stride = regs.get(0xB0, 6)
            positions, normals = _hedge_positions(block[: nverts * stride], stride, scale)
            arrays = _hedge_arrays(block, words[4:9], regs)
            cols = _hedge_columns(prims)
            pidx = cols.get("pos")
            if pidx is None or pidx.max(initial=0) >= len(positions):
                model.warnings.append(f"{name}: position index past the array")
                continue
            tris = []
            base = 0
            for op, prim, _lo, _hi in prims:
                tris.append(_triangles(op, len(prim)) + base)
                base += len(prim)
            tri = np.concatenate(tris)
            pos = positions[pidx]
            a, b, c = pos[tri[:, 0]], pos[tri[:, 1]], pos[tri[:, 2]]
            good = ~(np.all(a == b, axis=1) | np.all(b == c, axis=1) | np.all(a == c, axis=1))
            tri = tri[good]
            if not len(tri):
                model.warnings.append(f"{name}: every triangle is degenerate")
                continue

            def gather(key: str, col: str, arrays=arrays, cols=cols) -> np.ndarray | None:
                arr = arrays.get(key)
                idx = cols.get(col)
                if arr is None or idx is None or idx.max(initial=0) >= len(arr):
                    return None
                return arr[idx]

            clr = gather("clr", "clr")
            model.strips.append(
                Strip(
                    shader,
                    words[0],
                    pos.astype(np.float32),
                    None if normals is None else normals[pidx].astype(np.float32),
                    None if clr is None else clr.astype(np.uint8),
                    gather("tex", "tex0"),
                    tri.reshape(-1).astype(np.uint32),
                    False,
                )
            )
    return model
