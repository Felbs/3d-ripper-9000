"""Acclaim ``.SKN`` skinned characters - All-Star Baseball 2002/2003/2004 player bodies,
hands and mascots.

``docs/formats/acclaim-gdf.md`` recorded these as declined: read with the ``.GDF`` shape the
bone names land where the mesh records belong.  The real layout, all big-endian::

    +0x00 char name[36]
    +0x24 u32 materials
    +0x28 u32 bones
    +0x2c u32 objects
    +0x30 u32 geoms
    +0x34 u32 0
    +0x38 u32 tail_pad            # zero bytes between the geom records and section A
    +0x3c u32 0, u32 0
    +0x44 u32 sizeA               # attribute arrays
    +0x48 u32 sizeB               # display lists
    +0x4c materials x char[32]
          bones     x char[32]    # ROOT, L_UP_LEG, ... - names only, no transforms
          objects   x 76 { char name[64]; u32 1; u16 first_geom; u16 geoms; u32 0 }
          geoms     x 52 { u32 flags; u32 dl_size; u32 blend_dl_size;
                           u16 verts, w1, w2, w3; s32 offs[8] }
          tail_pad  x 0x00
    A     the attribute arrays        (A = file size - sizeA - sizeB)
    B     the display lists           (B = A + sizeA)

and the header tiles the file to the byte: ``0x4c + materials*32 + bones*32 + objects*76 +
geoms*52 + tail_pad == A`` on 17 of 17 samples.

Each geom is up to **two copies of the same piece of the model**, both with vertices already
in MODEL SPACE (the runtime XF matrices must be ``boneWorld x inverseBind`` - nothing here is
bone-local, which is what defeated the flat scans):

* the *rigid* copy - ``offs[0]``: a GX display list of 7-byte vertices ``{u8 pnmtx, u16 pos,
  u16 nrm, u16 uv}`` (indices unified: pos == nrm == uv, max == verts-1), pos/nrm indexed
  into a 12-byte ``{s16 pos[3]; s16 nrm[3]}`` array at ``offs[2]``, uv into the u16 pair
  array at ``offs[5]``.  ``0x20``/``0x28`` loads name the bone each PNMTX slot carries
  (slot = vertex byte / 3), so every vertex has one bone.  ``flags & 1`` inserts a texmtx
  byte after the pnmtx byte (8-byte vertices, plus ``0x30`` texture-matrix loads - the
  env-mapped heads and helmets); a geom whose loads all name bone ``0xffff`` is a
  placeholder whose indices are garbage.
* the *blended* copy - ``offs[1]``: a display list of 6-byte vertices ``{u16 pos, u16 nrm,
  u16 uv}`` (pos == nrm, uv == pos + verts), pos/nrm indexed into a 16-byte
  ``{s16 pos[3]; s16 nrm_zxy[3]; u8 w0, w1; u16 aux}`` array at ``offs[3]`` whose rows are
  sorted by weight count - the u16 triple ``w1/w2/w3`` counts its 1-, 2- and 3-weight
  vertices (w1+w2+w3 == rows, and the max pos index == rows-1).  Its normal is stored
  z-first.  Which bones those weights blend is NOT in the file (the CPU-skinning tables
  live with the animation data), so the blended copy is a baked bind pose.
* geoms with ``offs[4] >= 0`` are position-only (the ``shadow`` material): a display list of
  4-byte vertices ``{u8 pnmtx, u16 pos, u8 0}`` over a 6-byte ``{s16 pos[3]}`` array.

``offs[7]`` is the geom's material index.  A ``-1`` offset means the copy is absent; every
present display list parses to exactly its declared size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

HEADER = 0x4C
NAME_LEN = 36
MATERIAL_NAME = 32
BONE_NAME = 32
OBJECT_RECORD = 76
GEOM_RECORD = 52
#: GX display-list opcodes: indexed XF loads and the primitives these files use
LOAD_POS, LOAD_NRM, LOAD_TEX = 0x20, 0x28, 0x30
STRIP, TRIANGLES, FAN, QUADS = 0x98, 0x90, 0xA0, 0x80
MAX_COUNT = 1 << 16
#: fixed-point scales: positions are 8.8, normals 2.14, uvs 4.12
POS_SCALE, NRM_SCALE, UV_SCALE = 256.0, 16384.0, 4096.0


class SknError(ValueError):
    """The file does not read as an Acclaim skinned model."""


@dataclass(frozen=True)
class Obj:
    name: str
    first_geom: int
    geoms: int


@dataclass(frozen=True)
class Geom:
    flags: int
    dl_size: int
    blend_dl_size: int
    verts: int
    weight1: int
    weight2: int
    weight3: int
    offs: tuple  # (rigid_dl, blend_dl, rigid_arr, blend_arr, shadow_arr, uv_arr, unused, material)

    @property
    def material(self) -> int:
        return self.offs[7]

    @property
    def blend_verts(self) -> int:
        return self.weight1 + self.weight2 + self.weight3


@dataclass(frozen=True)
class Model:
    name: str
    materials: list
    bones: list
    objects: list
    geoms: list
    a: int  # section A offset
    b: int  # section B offset
    size_a: int
    size_b: int
    tail_pad: int

    def geom_object(self, gi: int) -> str:
        for o in self.objects:
            if o.first_geom <= gi < o.first_geom + o.geoms:
                return o.name
        return ""


def _cstr(raw: bytes) -> str:
    return raw.split(bytes(1))[0].decode("latin-1", "replace")


def _structural(head: bytes):
    """The part of the header a 64-byte sniff can see: name, counts, two zero words and the
    tail pad (the third zero word at +0x40 runs past byte 64 and is left to ``model``)."""
    if len(head) < 0x40:
        return None
    nm = head[:NAME_LEN]
    if not nm[:1].isalnum() or 0 not in nm:
        return None
    mats, bones, objects, geoms = struct.unpack_from(">4I", head, 0x24)
    z0, tail_pad, z1 = struct.unpack_from(">3I", head, 0x34)
    if not (0 < mats <= MAX_COUNT and 0 < bones <= MAX_COUNT):
        return None
    if not (0 < objects <= MAX_COUNT and 0 < geoms <= MAX_COUNT):
        return None
    if z0 or z1 or tail_pad > 1 << 12:
        return None
    return mats, bones, objects, geoms, tail_pad


def _counts(head: bytes):
    got = _structural(head)
    if got is None or len(head) < HEADER:
        return None
    size_a, size_b = struct.unpack_from(">2I", head, 0x44)
    if not (0 < size_a <= 1 << 28 and 0 < size_b <= 1 << 28):
        return None
    return (*got, size_a, size_b)


def is_skn(head: bytes, size: int | None = None) -> bool:
    """Sniff: the counts read, the reserved words are zero and, when the head reaches the
    two block sizes at +0x44 and the file size is known, the header tiles to it.

    The rip hands detect() only 64 bytes, which covers everything but the sizes - the
    structural check decides there and ``model()`` still enforces the exact tiling.  A
    `.GDF` fails either way: its 32-byte material names start at +44, so this header's
    count and zero words land inside name text.
    """
    if len(head) < HEADER:
        return _structural(head) is not None
    got = _counts(head)
    if got is None:
        return False
    mats, bones, objects, geoms, tail_pad, size_a, size_b = got
    end = HEADER + mats * MATERIAL_NAME + bones * BONE_NAME
    end += objects * OBJECT_RECORD + geoms * GEOM_RECORD + tail_pad
    if size is None:
        return True
    return end + size_a + size_b == size


def model(data: bytes) -> Model:
    got = _counts(data[:HEADER])
    if got is None:
        raise SknError("not an Acclaim .SKN header")
    mats, bones, objects, geoms, tail_pad, size_a, size_b = got
    a = len(data) - size_a - size_b
    at = HEADER
    material_names = [_cstr(data[at + i * MATERIAL_NAME :][:MATERIAL_NAME]) for i in range(mats)]
    at += mats * MATERIAL_NAME
    bone_names = [_cstr(data[at + i * BONE_NAME :][:BONE_NAME]) for i in range(bones)]
    at += bones * BONE_NAME
    objs = []
    for _ in range(objects):
        nm = _cstr(data[at : at + 64])
        first, count = struct.unpack_from(">2H", data, at + 68)
        objs.append(Obj(nm, first, count))
        at += OBJECT_RECORD
    gs = []
    for _ in range(geoms):
        flags, dl, blend_dl = struct.unpack_from(">3I", data, at)
        verts, w1, w2, w3 = struct.unpack_from(">4H", data, at + 12)
        offs = struct.unpack_from(">8i", data, at + 20)
        gs.append(Geom(flags, dl, blend_dl, verts, w1, w2, w3, offs))
        at += GEOM_RECORD
    at += tail_pad
    if at != a:
        raise SknError(f"the header does not tile to section A ({at:#x} != {a:#x})")
    name = _cstr(data[:NAME_LEN])
    b = a + size_a
    return Model(name, material_names, bone_names, objs, gs, a, b, size_a, size_b, tail_pad)


# -- display lists -----------------------------------------------------------------------


def _strip_tris(base: int, n: int, op: int, out: list) -> None:
    if op == STRIP:
        for i in range(n - 2):
            a, b, c = base + i, base + i + 1, base + i + 2
            out.append((a, b, c) if i % 2 == 0 else (b, a, c))
    elif op == FAN:
        for i in range(1, n - 1):
            out.append((base, base + i, base + i + 1))
    elif op == TRIANGLES:
        for i in range(0, n - 2, 3):
            out.append((base + i, base + i + 1, base + i + 2))
    else:  # QUADS
        for i in range(0, n - 3, 4):
            out.append((base + i, base + i + 1, base + i + 2))
            out.append((base + i, base + i + 2, base + i + 3))


def rigid_dl(data: bytes, at: int, end: int, vert_size: int = 7):
    """The rigid copy: XF matrix loads plus strips of ``{u8 pnmtx, [u8 texmtx,] u16 pos,
    [u16 nrm, u16 uv]}`` - 7 bytes normally, 8 with the ``flags & 1`` texmtx byte (env-mapped
    heads, which also carry ``0x30`` texture-matrix loads), 4 for the position-only geoms.

    Returns ``(verts, tris, ok, real)`` - verts as ``(bone, pos_index)`` with the bone
    resolved through the ``0x20`` loads in effect, tris indexing that vert list, ok = the
    list parsed to exactly its size (trailing NOPs allowed), real = at least one load named
    an actual bone (placeholder geoms load ``0xffff`` and hold garbage indices).
    """
    slot2bone: dict[int, int] = {}
    verts: list = []
    tris: list = []
    real = False
    p_off = 2 if vert_size == 8 else 1
    pos = at
    while pos < end:
        op = data[pos]
        if op == 0:
            pos += 1
            continue
        if op in (LOAD_POS, LOAD_NRM, LOAD_TEX, 0x38):
            if pos + 5 > end:
                return verts, tris, False, real
            idx, addr = struct.unpack_from(">2H", data, pos + 1)
            if op == LOAD_POS:
                slot2bone[(addr & 0xFFF) // 12] = idx
                real = real or idx != 0xFFFF
            pos += 5
            continue
        if op in (STRIP, TRIANGLES, FAN, QUADS):
            n = struct.unpack_from(">H", data, pos + 1)[0]
            pos += 3
            if pos + n * vert_size > end:
                return verts, tris, False, real
            _strip_tris(len(verts), n, op, tris)
            for _ in range(n):
                slot = data[pos] // 3
                p = struct.unpack_from(">H", data, pos + p_off)[0]
                verts.append((slot2bone.get(slot, -1), p))
                pos += vert_size
            continue
        return verts, tris, False, real
    return verts, tris, True, real


def blend_dl(data: bytes, at: int, end: int):
    """The blended copy: strips of ``{u16 pos, u16 nrm, u16 uv}`` (no matrix loads).

    Returns ``(verts, tris, ok)`` - verts as pos indices into the blended array.
    """
    verts: list = []
    tris: list = []
    pos = at
    while pos < end:
        op = data[pos]
        if op == 0:
            pos += 1
            continue
        if op in (STRIP, TRIANGLES, FAN, QUADS):
            n = struct.unpack_from(">H", data, pos + 1)[0]
            pos += 3
            if pos + n * 6 > end:
                return verts, tris, False
            _strip_tris(len(verts), n, op, tris)
            for _ in range(n):
                verts.append(struct.unpack_from(">H", data, pos)[0])
                pos += 6
            continue
        return verts, tris, False
    return verts, tris, True


# -- meshes ------------------------------------------------------------------------------


@dataclass
class Mesh:
    kind: str  # "blended" | "rigid" | "shadow"
    material: int
    object_name: str
    positions: object  # (N,3) f32
    normals: object | None
    uvs: object | None
    indices: list  # triangles as vert-list index triples
    bones: list  # per-vertex bone index (rigid/shadow) or [] (blended)


def meshes(data: bytes, m: Model) -> list:
    """Every geom's best copy, positions in model space.

    The blended copy is preferred (it is the smooth, seam-free tessellation); the rigid copy
    stands in where a geom has no blended one; position-only geoms come out bare.  A geom
    whose display list does not parse is skipped - the caller can compare counts.
    """
    import numpy as np

    out = []
    for gi, g in enumerate(m.geoms):
        o = g.offs
        obj = m.geom_object(gi)
        uv16 = None
        if o[5] >= 0:
            after = [x for x in (o[2], o[3], o[4]) if x >= 0 and x > o[5]]
            n_uv = (min(after) - o[5]) // 4 if after else 0
            if n_uv > 0:
                uv16 = np.frombuffer(data, ">i2", n_uv * 2, m.a + o[5]).reshape(-1, 2)
        if o[1] >= 0 and g.blend_dl_size:
            verts, tris, ok = blend_dl(data, m.b + o[1], m.b + o[1] + g.blend_dl_size)
            n_rows = g.blend_verts
            if ok and verts and o[3] >= 0 and n_rows and max(verts) < n_rows:
                arr = np.frombuffer(data, ">i2", n_rows * 8, m.a + o[3]).reshape(-1, 8)
                vi = np.asarray(verts, np.int64)
                pos = arr[vi, :3].astype(np.float32) / POS_SCALE
                nrm = arr[vi][:, (4, 5, 3)].astype(np.float32) / NRM_SCALE
                uv = None
                if uv16 is not None:
                    ui = np.minimum(vi + g.verts, len(uv16) - 1)
                    uv = uv16[ui].astype(np.float32) / UV_SCALE
                out.append(Mesh("blended", g.material, obj, pos, nrm, uv, tris, []))
                continue
        if o[0] >= 0 and g.dl_size and o[4] >= 0:  # position-only (shadow)
            verts, tris, ok, real = rigid_dl(data, m.b + o[0], m.b + o[0] + g.dl_size, vert_size=4)
            if ok and real and verts:
                n = max(p for _, p in verts) + 1
                if m.a + o[4] + n * 6 > m.b:
                    continue
                arr = np.frombuffer(data, ">i2", n * 3, m.a + o[4]).reshape(-1, 3)
                vi = np.asarray([p for _, p in verts], np.int64)
                pos = arr[vi].astype(np.float32) / POS_SCALE
                bones = [b for b, _ in verts]
                out.append(Mesh("shadow", g.material, obj, pos, None, None, tris, bones))
            continue
        if o[0] >= 0 and g.dl_size and o[2] >= 0:
            size = 8 if g.flags & 1 else 7
            end = m.b + o[0] + g.dl_size
            verts, tris, ok, real = rigid_dl(data, m.b + o[0], end, vert_size=size)
            if ok and real and verts and g.verts and max(p for _, p in verts) < g.verts:
                arr = np.frombuffer(data, ">i2", g.verts * 6, m.a + o[2]).reshape(-1, 6)
                vi = np.asarray([p for _, p in verts], np.int64)
                pos = arr[vi, :3].astype(np.float32) / POS_SCALE
                nrm = arr[vi, 3:6].astype(np.float32) / NRM_SCALE
                uv = None
                if uv16 is not None:
                    ui = np.minimum(vi, len(uv16) - 1)
                    uv = uv16[ui].astype(np.float32) / UV_SCALE
                bones = [b for b, _ in verts]
                out.append(Mesh("rigid", g.material, obj, pos, nrm, uv, tris, bones))
    return out


# -- identities --------------------------------------------------------------------------


def _tiling(data: bytes):
    try:
        m = model(data)
    except (SknError, struct.error) as exc:
        return None, str(exc)
    end = HEADER + len(m.materials) * MATERIAL_NAME + len(m.bones) * BONE_NAME
    end += len(m.objects) * OBJECT_RECORD + len(m.geoms) * GEOM_RECORD + m.tail_pad
    held = end == m.a and m.b + m.size_b == len(data)
    return held, f"header tiles to {end:#x} against section A at {m.a:#x}, A+B end the file"


def _lists_parse(data: bytes):
    try:
        m = model(data)
    except (SknError, struct.error) as exc:
        return None, str(exc)
    held = total = 0
    for g in m.geoms:
        o = g.offs
        if o[0] >= 0 and g.dl_size:
            total += 1
            size = 4 if o[4] >= 0 else (8 if g.flags & 1 else 7)
            _, _, ok, _ = rigid_dl(data, m.b + o[0], m.b + o[0] + g.dl_size, vert_size=size)
            held += ok
        if o[1] >= 0 and g.blend_dl_size:
            total += 1
            _, _, ok = blend_dl(data, m.b + o[1], m.b + o[1] + g.blend_dl_size)
            held += ok
    if not total:
        return None, "no display lists"
    return held == total, f"{held} of {total} display lists parse to exactly their size"


def _index_identities(data: bytes):
    try:
        m = model(data)
    except (SknError, struct.error) as exc:
        return None, str(exc)
    held = total = 0
    for g in m.geoms:
        o = g.offs
        if o[0] >= 0 and g.dl_size and o[4] < 0 and g.verts:
            size = 8 if g.flags & 1 else 7
            verts, _, ok, real = rigid_dl(data, m.b + o[0], m.b + o[0] + g.dl_size, vert_size=size)
            if not real:
                continue  # placeholder geom - its indices are garbage by construction
            total += 1
            held += ok and bool(verts) and max(p for _, p in verts) == g.verts - 1
        if o[1] >= 0 and g.blend_dl_size and g.blend_verts:
            total += 1
            verts, _, ok = blend_dl(data, m.b + o[1], m.b + o[1] + g.blend_dl_size)
            held += ok and bool(verts) and max(verts) == g.blend_verts - 1
    if not total:
        return None, "no indexed display lists"
    return held == total, f"{held} of {total} lists use exactly their declared vertex count"


def _weight_sentinel(data: bytes):
    try:
        m = model(data)
    except (SknError, struct.error) as exc:
        return None, str(exc)
    held = total = 0
    for g in m.geoms:
        if g.offs[3] < 0 or not g.weight1:
            continue
        total += 1
        rows = [
            struct.unpack_from(">2s", data, m.a + g.offs[3] + i * 16 + 12)[0]
            for i in range(g.weight1)
        ]
        held += all(r == b"\xff\x00" for r in rows)
    if not total:
        return None, "no single-weight blended vertices"
    return held == total, f"{held} of {total} geoms mark all 1-weight rows with the ff 00 sentinel"


IDENTITIES = [
    Identity(
        "the header tiles the file",
        "0x4c + mats*32 + bones*32 + objects*76 + geoms*52 + pad == size - sizeA - sizeB",
        _tiling,
    ),
    Identity(
        "every display list parses to its size",
        "opcode walk over each list consumes exactly the declared bytes",
        _lists_parse,
    ),
    Identity(
        "the lists use their declared vertex counts",
        "max rigid pos index == verts-1; max blended pos index == w1+w2+w3-1",
        _index_identities,
    ),
    Identity(
        "single-weight rows carry the ff 00 sentinel",
        "blended rows [0, w1) have byte pair ff 00 at +12",
        _weight_sentinel,
    ),
]
