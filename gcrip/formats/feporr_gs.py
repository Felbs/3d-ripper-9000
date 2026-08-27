"""Fire Emblem: Path of Radiance ``.gs`` geometry -> Model.

Intelligent Systems' GameCube shape format (reverse-engineered here from GFEE01: weapons in
``xwp``, map props and terrain in ``zmap``/``zbg``, characters in ``zu``).  Big-endian; every
pointer is relative to 0x20 and listed in a relocation table at the end of the file.

  0x00 u32 file size        0x04 u32 relocation table (rel)   0x08 u32 relocation count
  0x20 u32 model name       0x24 u32 build date (BCD yyyymmdd)  0x28 u32 hash?
  0x2C f32[6] bounding box
  0x44 u32 positions        0x48 u32 normals    0x4C u32 texcoords   0x50 u32 colours
  0x54 u32 materials        0x58 u32 shapes     0x5C u32 draw records (table)
  0x60 u32 draw records (linked list, map props)   0x68 u32 skin table (characters only)
  0x6C u16[8] counts: positions, normals, texcoords, colours, materials, shapes, records, 0
  0x7C u8 position shift, u8 normal shift, u8 texcoord shift

  positions s16 xyz, normals s8 xyz, texcoords s16 st (fixed point by the shifts),
  colours RGBA8
  material (0x20): u32 name, u32 flags (0x100 = textured?), RGBA8 diffuse, RGBA8 ambient?,
        RGBA8 specular?, u32 sampler pointer, u32 0, u32 0
  sampler (0x1C): u16 count, u16 0, u8 0, u8 TPL image index, u8 wrap S, u8 wrap T, ...,
        f32 scale S @0x10, f32 scale T @0x14
  shape (0x24): u32 name, f32[6] bbox, u16 id, u16 0, u32 0
  draw record (0x20): u32 shape, u32 next record, u8 flags (0x30/0x34/0x38: bit 2 = ?),
        u8 ?, u8 ?, u8 material, u16 shape index, u16 0, u32 vertex format,
        u32 display list, u32 display list size, u32 0
  vertex format bits: 0x4000 POS, 0x0400 NRM, 0x1000 CLR0, 0x0200 TEX0, 0x8000 TEX1 (all
        INDEX16 in GX attribute order), 0x800000 = skinned (positions live in the skin table)
  display lists: standard GX primitives (0x98 triangle strips seen) over the arrays above

Skinned characters (``zu``) have no position/normal arrays; the skin block at 0x68 holds:
  u32 header size (0x10), u32 table size, u16 envelope count, u16 vertex slots, u16 ?, u16 ?
  envelopes (0x18): u16 bone[4] (0xFFFF unused, indices into the ``.g`` node tree),
        u8 weight[4] (sum 256), u32 byte offset, u16 byte size, u8 ?, u8 bone count, u16
        vertex count, u16 0
  then, at the block start + table size, vertex rows of 12 bytes: s16 xyz position and
        s16 xyz normal, both /256, in model space (bind pose).  Display-list POS/NRM indices
        select a row (index * 12); rows outside any envelope's [offset, offset + size) are
        unused padding.  A vertex belongs to the envelope whose byte range holds it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats.j3d import triangulate

BASE = 0x20
VF_POS = 0x4000
VF_CLR0 = 0x1000
VF_NRM = 0x0400
VF_TEX0 = 0x0200
VF_TEX1 = 0x8000
VF_SKIN = 0x800000


class GSError(Exception):
    pass


@dataclass
class Sampler:
    image: int
    wrap_s: int
    wrap_t: int
    scale_s: float = 1.0
    scale_t: float = 1.0


@dataclass
class Material:
    name: str
    flags: int
    diffuse: tuple[int, int, int, int]
    sampler: Sampler | None


@dataclass
class Shape:
    name: str
    bbox: tuple[float, ...]
    id: int


@dataclass
class Record:
    shape: int
    material: int
    flags: int
    vformat: int
    positions: np.ndarray  # (N,3) f32
    triangles: np.ndarray  # (T,3)
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: np.ndarray | None = None
    bones: np.ndarray | None = None  # (N,4) u16 .g node indices (skinned only)
    weights: np.ndarray | None = None  # (N,4) f32


@dataclass
class Skin:
    bones: np.ndarray  # (E,4) u16
    weights: np.ndarray  # (E,4) f32
    positions: np.ndarray  # (S,3) f32 per vertex slot
    normals: np.ndarray  # (S,3)
    envelope: np.ndarray  # (S,) int64 envelope per slot, -1 for padding


@dataclass
class Model:
    name: str
    materials: list[Material]
    shapes: list[Shape]
    records: list[Record]
    skinned: int = 0  # records drawn from the skin block
    bone_count: int = 0  # highest bone index + 1 seen in the envelopes
    warnings: list[str] = field(default_factory=list)


_ENVELOPE = np.dtype(
    [
        ("bone", ">u2", 4),
        ("w", "u1", 4),
        ("off", ">u4"),
        ("size", ">u2"),
        ("f1", "u1"),
        ("nbones", "u1"),
        ("count", ">u2"),
        ("pad", ">u2"),
    ]
)


def _skin(data: bytes, rel: int, warnings: list[str]) -> Skin | None:
    off = BASE + rel
    if not rel or off + 0x10 > len(data):
        return None
    hsize, tsize, n_env, n_slot = struct.unpack_from(">IIHH", data, off)
    if hsize < 0x10 or off + tsize > len(data) or not n_env:
        warnings.append("skin block header out of range")
        return None
    n_env = min(n_env, (tsize - hsize) // _ENVELOPE.itemsize)
    env = np.frombuffer(data, _ENVELOPE, n_env, off + hsize)
    vt = off + tsize
    n_slot = max(0, min(n_slot, (len(data) - vt) // 12))
    rows = np.frombuffer(data, ">i2", n_slot * 6, vt).reshape(n_slot, 6).astype(np.float32) / 256.0
    envelope = np.full(n_slot, -1, np.int64)
    starts = env["off"].astype(np.int64)
    ends = starts + env["size"].astype(np.int64)
    slot_bytes = np.arange(n_slot, dtype=np.int64) * 12
    order = np.argsort(starts)
    idx = np.searchsorted(starts[order], slot_bytes, side="right") - 1
    ok = idx >= 0
    cand = order[np.where(ok, idx, 0)]
    inside = ok & (slot_bytes < ends[cand])
    envelope[inside] = cand[inside]
    weights = env["w"].astype(np.float32) / 256.0
    bones = env["bone"].astype(np.uint16).copy()
    bones[bones == 0xFFFF] = 0
    return Skin(bones, weights, rows[:, :3], rows[:, 3:], envelope)


def looks_like_gs(head: bytes, size: int) -> bool:
    if len(head) < 0x10 or size < 0x90:
        return False
    fs, reloc, count = struct.unpack_from(">III", head, 0)
    return fs == size and BASE + reloc + count * 4 <= size and reloc >= 0x60


def _cstr(data: bytes, rel: int, limit: int = 0x80) -> str:
    off = BASE + rel
    end = data.find(b"\0", off, off + limit)
    if end < 0:
        end = min(off + limit, len(data))
    return data[off:end].decode("shift_jis", "replace")


def _array(data: bytes, rel: int, count: int, dtype: str, cols: int) -> np.ndarray:
    if not count:
        return np.zeros((0, cols), np.float32)
    off = BASE + rel
    item = np.dtype(dtype).itemsize * cols
    count = max(0, min(count, (len(data) - off) // item))
    return np.frombuffer(data, dtype, count * cols, off).reshape(count, cols)


def _display_list(dl: bytes, vformat: int) -> tuple[np.ndarray, np.ndarray]:
    """(records (V,5) int64 [pos nrm clr tex tex1] with -1 for absent, triangles (T,3))."""
    fields = []
    attrs = (VF_POS, "pos"), (VF_NRM, "nrm"), (VF_CLR0, "clr"), (VF_TEX0, "tex"), (VF_TEX1, "tex1")
    for bit, name in attrs:
        if vformat & bit:
            fields.append((name, ">u2"))
    if not fields:
        raise GSError(f"vertex format {vformat:#x} has no attributes")
    vdt = np.dtype(fields)
    stride = vdt.itemsize
    rows, tris = [], []
    base = 0
    pos = 0
    while pos + 3 <= len(dl):
        op = dl[pos]
        if op == 0:
            break
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        end = pos + count * stride
        if end > len(dl):
            break
        arr = np.frombuffer(dl, vdt, count, pos)
        pos = end
        t = triangulate(op, count)
        if len(t):
            rows.append(arr)
            tris.append(t + base)
            base += count
    if not rows:
        return np.zeros((0, 5), np.int64), np.zeros((0, 3), np.int64)
    verts = np.concatenate(rows)
    out = np.full((len(verts), 5), -1, np.int64)
    for i, name in enumerate(("pos", "nrm", "clr", "tex", "tex1")):
        if name in vdt.names:
            out[:, i] = verts[name]
    return out, np.concatenate(tris)


def parse(data: bytes) -> Model:
    if len(data) < 0x90:
        raise GSError("too small")
    fs, _reloc, _nreloc = struct.unpack_from(">III", data, 0)
    if fs != len(data):
        raise GSError(f"size field {fs} != {len(data)}")
    warnings: list[str] = []
    (name_rel,) = struct.unpack_from(">I", data, 0x20)
    name = _cstr(data, name_rel, 0x40)
    p_pos, p_nrm, p_tex, p_clr, p_mat, p_shape, p_rec, p_rec2 = struct.unpack_from(
        ">8I", data, 0x44
    )
    n_pos, n_nrm, n_tex, n_clr, n_mat, n_shape, n_rec, _ = struct.unpack_from(">8H", data, 0x6C)
    pos_shift, nrm_shift, tex_shift = data[0x7C], data[0x7D], data[0x7E]

    positions = _array(data, p_pos, n_pos, ">i2", 3).astype(np.float32) / float(1 << pos_shift)
    normals = _array(data, p_nrm, n_nrm, "i1", 3).astype(np.float32) / float(1 << (nrm_shift or 6))
    texcoords = _array(data, p_tex, n_tex, ">i2", 2).astype(np.float32) / float(1 << tex_shift)
    colors = _array(data, p_clr, n_clr, "u1", 4).astype(np.float32) / 255.0

    (p_skin,) = struct.unpack_from(">I", data, 0x68)
    skin = _skin(data, p_skin, warnings) if p_skin else None

    materials: list[Material] = []
    for i in range(n_mat):
        off = BASE + p_mat + i * 0x20
        if off + 0x20 > len(data):
            break
        mname_rel, flags = struct.unpack_from(">II", data, off)
        r, g, b, a = struct.unpack_from(">4B", data, off + 8)
        (samp_rel,) = struct.unpack_from(">I", data, off + 0x14)
        sampler = None
        if samp_rel and BASE + samp_rel + 0x18 <= len(data):
            so = BASE + samp_rel
            image, wrap_s, wrap_t = data[so + 5], data[so + 6], data[so + 7]
            scale_s, scale_t = struct.unpack_from(">ff", data, so + 0x10)
            if not (0.01 < abs(scale_s) < 100) or not (0.01 < abs(scale_t) < 100):
                scale_s = scale_t = 1.0
            sampler = Sampler(image, wrap_s, wrap_t, scale_s, scale_t)
        materials.append(Material(_cstr(data, mname_rel), flags, (r, g, b, a), sampler))

    shapes: list[Shape] = []
    shape_index: dict[int, int] = {}
    for i in range(n_shape):
        off = BASE + p_shape + i * 0x24
        if off + 0x24 > len(data):
            break
        (sname_rel,) = struct.unpack_from(">I", data, off)
        bbox = struct.unpack_from(">6f", data, off + 4)
        (sid,) = struct.unpack_from(">H", data, off + 0x1C)
        shape_index[off - BASE] = i
        shapes.append(Shape(_cstr(data, sname_rel), bbox, sid))

    rec_offsets = [BASE + p_rec + i * 0x20 for i in range(n_rec)] if p_rec else []
    nxt = BASE + p_rec2 if p_rec2 else 0
    seen: set[int] = set()
    while nxt and nxt + 0x20 <= len(data) and nxt not in seen and len(seen) < 4096:
        seen.add(nxt)
        rec_offsets.append(nxt)
        (link,) = struct.unpack_from(">I", data, nxt + 4)
        nxt = BASE + link if link else 0

    records: list[Record] = []
    skinned = 0
    unsupported = 0
    for i, off in enumerate(rec_offsets):
        if off + 0x20 > len(data):
            break
        shape_rel, _next = struct.unpack_from(">II", data, off)
        flags, mat = data[off + 8], data[off + 11]
        (shape_i,) = struct.unpack_from(">H", data, off + 0xC)
        vformat, dl_rel, dl_size = struct.unpack_from(">III", data, off + 0x10)
        use_skin = bool(vformat & VF_SKIN) or not len(positions)
        if use_skin:
            if skin is None:
                unsupported += 1
                continue
            skinned += 1
        if not vformat & VF_POS:
            warnings.append(f"record {i}: vertex format {vformat:#x} without positions")
            continue
        dl = data[BASE + dl_rel : BASE + dl_rel + dl_size]
        try:
            verts, tris = _display_list(dl, vformat)
        except GSError as ex:
            warnings.append(f"record {i}: {ex}")
            continue
        if not len(tris):
            continue
        uniq, inverse = np.unique(verts, axis=0, return_inverse=True)
        tri = inverse.reshape(-1)[tris]
        src_pos = skin.positions if use_skin and skin is not None else positions
        if not len(src_pos):
            continue
        pi = np.minimum(uniq[:, 0], len(src_pos) - 1)
        rec = Record(
            shape_index.get(shape_rel, shape_i if shape_i < len(shapes) else 0),
            mat if mat < len(materials) else 0,
            flags,
            vformat,
            src_pos[pi],
            tri,
        )
        if use_skin and skin is not None:
            if vformat & VF_NRM:
                rec.normals = skin.normals[np.minimum(uniq[:, 1], len(skin.normals) - 1)]
            env = skin.envelope[pi]
            rec.bones = skin.bones[np.where(env >= 0, env, 0)]
            rec.weights = skin.weights[np.where(env >= 0, env, 0)].copy()
            rec.weights[env < 0] = 0.0
            rec.weights[env < 0, 0] = 1.0
        elif vformat & VF_NRM and len(normals):
            rec.normals = normals[np.minimum(uniq[:, 1], len(normals) - 1)]
        if vformat & VF_CLR0 and len(colors):
            rec.colors = colors[np.minimum(uniq[:, 2], len(colors) - 1)]
        if vformat & VF_TEX0 and len(texcoords):
            rec.uvs = texcoords[np.minimum(uniq[:, 3], len(texcoords) - 1)]
        records.append(rec)
    if unsupported:
        warnings.append(f"{unsupported} draw records without vertex data")
    bone_count = int(skin.bones.max()) + 1 if skin is not None and len(skin.bones) else 0
    return Model(name, materials, shapes, records, skinned, bone_count, warnings)
