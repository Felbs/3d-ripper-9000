"""HAL Laboratory sysdolphin (HSD) archives - the .dat files of Super Smash Bros. Melee,
Kirby Air Ride and other HAL GameCube titles. Layout checked byte-by-byte against Melee's
PlFxNr.dat / GrOp.dat and the melee decompilation's sysdolphin headers.

File (big endian):
  0x00 u32 file size            0x04 u32 data block size (relocation table follows it)
  0x08 u32 relocation count     0x0C u32 root node count    0x10 u32 reference node count
  0x14 char[4] version ("001B" or zeros)   0x18 pad
  0x20 data block; then reloc table (u32 offsets, into the data block, of every pointer
  field); then roots and references (u32 data offset, u32 string offset); then the string
  table. Every pointer inside the data block is relative to the data block start.

Structures (offsets inside the data block):
  JOBJ 0x40: 0x00 class 0x04 flags 0x08 child 0x0C next 0x10 dobj (spline/ptcl by flags)
             0x14 f32 rot[3] (radians, X then Y then Z) 0x20 scale[3] 0x2C pos[3]
             0x38 inverse bind matrix ptr (f32[3][4]) 0x3C robj
  DOBJ 0x10: 0x00 class 0x04 next 0x08 mobj 0x0C pobj
  POBJ 0x18: 0x00 class 0x04 next 0x08 vertex attribute list 0x0C u16 flags
             0x0E u16 display list size / 32  0x10 display list  0x14 jobj / shape set /
             envelope list (flags bits 12-13: 0 skin, 1 shape anim, 2 envelope)
  VtxAttr 0x18: attr, attr_type (1 direct 2 idx8 3 idx16), comp_cnt, comp_type, u8 frac,
             u16 stride @0x12, data ptr @0x14; the list ends with attr 0xFF
  Envelope list: null-terminated array of pointers, each to a null-terminated array of
             (jobj ptr, f32 weight); PNMTXIDX / 3 picks the entry
  MOBJ: 0x04 rendermode 0x08 tobj 0x0C material (ambient, diffuse, specular GXColor,
             f32 alpha, f32 shininess)
  TOBJ 0x5C: 0x04 next 0x08 texmap id 0x0C texgen src (4 = TEX0) 0x10 rot[3] 0x1C scale[3]
             0x28 trans[3] 0x34 wrap_s 0x38 wrap_t 0x3C u8 repeat_s/t 0x40 flags
             0x44 blending 0x48 magfilt 0x4C imagedesc 0x50 tlut 0x54 lod 0x58 tev
  ImageDesc: data ptr, u16 w, u16 h, u32 GX format, u32 mipmap, f32 minLOD/maxLOD
  Tlut: data ptr, u32 GX tlut format, u32 name, u16 entries
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

HEADER = 0x20

# JOBJ flags
JOBJ_SKELETON = 1 << 0
JOBJ_SKELETON_ROOT = 1 << 1
JOBJ_ENVELOPE_MODEL = 1 << 2
JOBJ_CLASSICAL_SCALE = 1 << 3
JOBJ_HIDDEN = 1 << 4
JOBJ_PTCL = 1 << 5
JOBJ_INSTANCE = 1 << 12
JOBJ_SPLINE = 1 << 14

# POBJ flags
POBJ_TYPE_MASK = 3 << 12
POBJ_SKIN = 0
POBJ_SHAPEANIM = 1 << 12
POBJ_ENVELOPE = 2 << 12
POBJ_CULL_MASK = 3 << 14

# MOBJ rendermode
RENDER_CONSTANT = 1 << 0
RENDER_VERTEX = 1 << 1
RENDER_DIFFUSE = 1 << 2
RENDER_TEX0 = 1 << 4
RENDER_XLU = 1 << 30

# TOBJ flags
TEX_COORD_MASK = 0xF
TEX_COORD_UV = 0
TEX_LIGHTMAP_MASK = 0x1F << 4
TEX_LIGHTMAP_DIFFUSE = 1 << 4
TEX_COLORMAP_MASK = 0xF << 16
TEX_COLORMAP_NONE = 0
TEX_COLORMAP_ALPHA_MASK = 1 << 16
TEX_COLORMAP_PASS = 6 << 16

# GX vertex attributes
VA_PNMTXIDX = 0
VA_TEX0MTXIDX = 1
VA_TEX7MTXIDX = 8
VA_POS = 9
VA_NRM = 10
VA_CLR0 = 11
VA_CLR1 = 12
VA_TEX0 = 13
VA_TEX7 = 20
VA_NBT = 25
VA_NULL = 0xFF

GX_DIRECT, GX_INDEX8, GX_INDEX16 = 1, 2, 3
_COMP_DTYPE = {0: ">u1", 1: ">i1", 2: ">u2", 3: ">i2", 4: ">f4"}
_COLOR_BYTES = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}

PRIM_QUADS = 0x80
PRIM_TRIANGLES = 0x90
PRIM_TRISTRIP = 0x98
PRIM_TRIFAN = 0xA0


class HsdError(ValueError):
    pass


# -- raw file -----------------------------------------------------------------------


@dataclass
class Root:
    name: str
    offset: int
    reference: bool = False


class DatFile:
    """The archive: header, data block, relocation set, named roots."""

    def __init__(self, data: bytes) -> None:
        if len(data) < HEADER:
            raise HsdError("too short for a DAT header")
        fsz, dsz, nrel, nroot, nref = struct.unpack_from(">IIIII", data, 0)
        if fsz != len(data):
            raise HsdError(f"header file size {fsz:#x} != {len(data):#x}")
        reloc_off = HEADER + dsz
        root_off = reloc_off + nrel * 4
        str_off = root_off + (nroot + nref) * 8
        if str_off > len(data):
            raise HsdError("tables run past the end of the file")
        self.data = data
        self.size = dsz
        self.version = data[0x14:0x18].rstrip(b"\0").decode("ascii", "replace")
        self.relocs: set[int] = set(struct.unpack_from(f">{nrel}I", data, reloc_off))
        self.roots: list[Root] = []
        for i in range(nroot + nref):
            do, so = struct.unpack_from(">II", data, root_off + i * 8)
            end = data.find(b"\0", str_off + so)
            name = data[str_off + so : end if end >= 0 else len(data)].decode("ascii", "replace")
            self.roots.append(Root(name, do, i >= nroot))
        self.pointers: set[int] = set()
        for r in self.relocs:
            if r + 4 <= dsz:
                self.pointers.add(self.u32(r))

    # all offsets are data-block relative
    def u8(self, off: int) -> int:
        return self.data[HEADER + off]

    def u16(self, off: int) -> int:
        return struct.unpack_from(">H", self.data, HEADER + off)[0]

    def u32(self, off: int) -> int:
        return struct.unpack_from(">I", self.data, HEADER + off)[0]

    def f32(self, off: int) -> float:
        return struct.unpack_from(">f", self.data, HEADER + off)[0]

    def f32s(self, off: int, n: int) -> tuple[float, ...]:
        return struct.unpack_from(f">{n}f", self.data, HEADER + off)

    def bytes(self, off: int, n: int) -> bytes:
        return self.data[HEADER + off : HEADER + off + n]

    def valid(self, off: int, size: int = 4) -> bool:
        return off >= 0 and off + size <= self.size

    def is_ptr_field(self, off: int) -> bool:
        return off in self.relocs


# -- model structures ---------------------------------------------------------------


@dataclass
class VtxAttr:
    attr: int
    attr_type: int
    comp_cnt: int
    comp_type: int
    frac: int
    stride: int
    data: int


@dataclass
class Envelope:
    entries: list[tuple[int, float]]  # (jobj offset, weight)


@dataclass
class Pobj:
    offset: int
    flags: int
    attrs: list[VtxAttr]
    display: bytes
    ptype: int
    skin_jobj: int = 0
    envelopes: list[Envelope] = field(default_factory=list)


@dataclass
class ImageDesc:
    offset: int
    data: int
    width: int
    height: int
    fmt: int


@dataclass
class Tlut:
    offset: int
    data: int
    fmt: int
    count: int


@dataclass
class Tobj:
    offset: int
    texmap: int
    src: int
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    translation: tuple[float, float, float]
    wrap_s: int
    wrap_t: int
    repeat_s: int
    repeat_t: int
    flags: int
    image: ImageDesc | None
    tlut: Tlut | None


@dataclass
class Mobj:
    offset: int
    rendermode: int
    tobjs: list[Tobj]
    ambient: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0)
    diffuse: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    alpha: float = 1.0


@dataclass
class Dobj:
    offset: int
    mobj: Mobj | None
    pobjs: list[Pobj]


@dataclass
class Jobj:
    offset: int
    flags: int
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    position: tuple[float, float, float]
    inv_bind: np.ndarray | None
    dobjs: list[Dobj]
    children: list[Jobj]
    index: int = -1
    parent: int | None = None

    @property
    def hidden(self) -> bool:
        return bool(self.flags & JOBJ_HIDDEN)

    def walk(self):
        """Depth-first, children before siblings.

        Iterative on purpose: recursing here costs one Python frame per joint, and these trees
        come from disc data that may be damaged or simply not be a skeleton at all.
        """
        stack = [self]
        while stack:
            j = stack.pop()
            yield j
            stack.extend(reversed(j.children))


@dataclass
class Model:
    name: str
    roots: list[Jobj]  # one or more trees drawn together
    warnings: list[str] = field(default_factory=list)


# -- parsing --------------------------------------------------------------------------


#: a real skeleton is tens of joints deep; beyond this the chain is not a skeleton
MAX_JOBJ_DEPTH = 256


class Parser:
    def __init__(self, dat: DatFile) -> None:
        self.dat = dat
        self.jobjs: dict[int, Jobj] = {}
        self.mobjs: dict[int, Mobj] = {}
        self.warnings: list[str] = []
        self._jobj_stack: set[int] = set()

    def jobj(self, off: int, depth: int = 0) -> Jobj | None:
        d = self.dat
        if off in self.jobjs:
            return self.jobjs[off]
        if not d.valid(off, 0x40) or off in self._jobj_stack:
            return None
        # The cycle guards above catch a tree that points back at itself, but not one that is
        # merely absurdly deep - and a `child` chain read out of arbitrary bytes can be.  That
        # raised RecursionError on 8 discs (30 recorded failures), killing the whole file rather
        # than the one bad branch.  A real skeleton is tens of joints deep, not hundreds.
        if depth > MAX_JOBJ_DEPTH:
            self.warnings.append(f"jobj tree deeper than {MAX_JOBJ_DEPTH} at {off:#x}; truncated")
            return None
        self._jobj_stack.add(off)
        flags, child, nxt, u = struct.unpack_from(">IIII", d.data, HEADER + off + 4)
        rot = d.f32s(off + 0x14, 3)
        scl = d.f32s(off + 0x20, 3)
        pos = d.f32s(off + 0x2C, 3)
        mtx_ptr = d.u32(off + 0x38)
        inv = None
        if mtx_ptr and d.valid(mtx_ptr, 48):
            inv = np.eye(4)
            inv[:3, :] = np.array(d.f32s(mtx_ptr, 12)).reshape(3, 4)
        dobjs: list[Dobj] = []
        if u and not flags & (JOBJ_SPLINE | JOBJ_PTCL):
            seen: set[int] = set()
            while u and d.valid(u, 0x10) and u not in seen:
                seen.add(u)
                dobjs.append(self.dobj(u))
                u = d.u32(u + 4)
        j = Jobj(off, flags, rot, scl, pos, inv, dobjs, [])
        self.jobjs[off] = j
        seen_c: set[int] = set()
        while child and child not in seen_c:
            seen_c.add(child)
            c = self.jobj(child, depth + 1)
            if c is None:
                break
            j.children.append(c)
            child = d.u32(child + 0x0C)
        self._jobj_stack.discard(off)
        # `next` siblings are handled by the parent loop above; a root's next is a sibling
        # root, which the caller walks
        return j

    def jobj_chain(self, off: int) -> list[Jobj]:
        """A JOBJ and its `next` siblings (used for roots)."""
        out = []
        seen: set[int] = set()
        while off and off not in seen:
            seen.add(off)
            j = self.jobj(off)
            if j is None:
                break
            out.append(j)
            off = self.dat.u32(off + 0x0C)
        return out

    def dobj(self, off: int) -> Dobj:
        d = self.dat
        mobj_off, pobj_off = d.u32(off + 8), d.u32(off + 0x0C)
        mobj = self.mobj(mobj_off) if mobj_off and d.valid(mobj_off, 0x10) else None
        pobjs: list[Pobj] = []
        seen: set[int] = set()
        while pobj_off and d.valid(pobj_off, 0x18) and pobj_off not in seen:
            seen.add(pobj_off)
            p = self.pobj(pobj_off)
            if p is not None:
                pobjs.append(p)
            pobj_off = d.u32(pobj_off + 4)
        return Dobj(off, mobj, pobjs)

    def pobj(self, off: int) -> Pobj | None:
        d = self.dat
        verts, flags, n_disp, disp, u = struct.unpack_from(">IHHII", d.data, HEADER + off + 8)
        attrs: list[VtxAttr] = []
        a = verts
        while d.valid(a, 0x18):
            attr, atype, cnt, ctype, frac, _pad, stride, ptr = struct.unpack_from(
                ">IIIIBBHI", d.data, HEADER + a
            )
            if attr == VA_NULL:
                break
            attrs.append(VtxAttr(attr, atype, cnt, ctype, frac, stride, ptr))
            a += 0x18
            if len(attrs) > 32:
                break
        size = n_disp * 32
        if not d.valid(disp, size):
            self.warnings.append(f"pobj {off:#x}: display list out of range")
            return None
        ptype = flags & POBJ_TYPE_MASK
        p = Pobj(off, flags, attrs, d.bytes(disp, size), ptype)
        if ptype == POBJ_SKIN:
            p.skin_jobj = u
        elif ptype == POBJ_ENVELOPE and u:
            k = 0
            while d.valid(u + k * 4):
                e = d.u32(u + k * 4)
                if not e:
                    break
                entries = []
                m = 0
                while d.valid(e + m * 8, 8):
                    jo, w = struct.unpack_from(">If", d.data, HEADER + e + m * 8)
                    if not jo:
                        break
                    entries.append((jo, w))
                    m += 1
                    if m > 64:
                        break
                p.envelopes.append(Envelope(entries))
                k += 1
                if k > 4096:
                    break
        return p

    def mobj(self, off: int) -> Mobj:
        if off in self.mobjs:
            return self.mobjs[off]
        d = self.dat
        rendermode, tobj_off, mat_off = struct.unpack_from(">III", d.data, HEADER + off + 4)
        tobjs: list[Tobj] = []
        seen: set[int] = set()
        while tobj_off and d.valid(tobj_off, 0x5C) and tobj_off not in seen:
            seen.add(tobj_off)
            tobjs.append(self.tobj(tobj_off))
            tobj_off = d.u32(tobj_off + 4)
        m = Mobj(off, rendermode, tobjs)
        if mat_off and d.valid(mat_off, 0x14):
            amb, dif, _spec = struct.unpack_from(">III", d.data, HEADER + mat_off)
            m.ambient = _rgba(amb)
            m.diffuse = _rgba(dif)
            m.alpha = d.f32(mat_off + 0x0C)
        self.mobjs[off] = m
        return m

    def tobj(self, off: int) -> Tobj:
        d = self.dat
        texmap, src = struct.unpack_from(">II", d.data, HEADER + off + 8)
        rot = d.f32s(off + 0x10, 3)
        scl = d.f32s(off + 0x1C, 3)
        trn = d.f32s(off + 0x28, 3)
        wrap_s, wrap_t, rep_s, rep_t, _p, flags = struct.unpack_from(
            ">IIBBHI", d.data, HEADER + off + 0x34
        )
        img_off, tlut_off = struct.unpack_from(">II", d.data, HEADER + off + 0x4C)
        img = None
        if img_off and d.valid(img_off, 0x18):
            ptr, w, h, fmt = struct.unpack_from(">IHHI", d.data, HEADER + img_off)
            img = ImageDesc(img_off, ptr, w, h, fmt)
        tlut = None
        if tlut_off and d.valid(tlut_off, 0x10):
            ptr, fmt, _name, n = struct.unpack_from(">IIIH", d.data, HEADER + tlut_off)
            tlut = Tlut(tlut_off, ptr, fmt, n)
        return Tobj(off, texmap, src, rot, scl, trn, wrap_s, wrap_t, rep_s, rep_t, flags, img, tlut)

    # -- structural JOBJ discovery ---------------------------------------------------

    def looks_like_dobj(self, off: int) -> bool:
        d = self.dat
        if not d.valid(off, 0x10) or d.u32(off) != 0:
            return False
        nxt, mobj, pobj = struct.unpack_from(">III", d.data, HEADER + off + 4)
        for f, v in ((4, nxt), (8, mobj), (12, pobj)):
            if v and not d.is_ptr_field(off + f):
                return False
        if not (mobj or pobj):
            return False
        if pobj and not (d.valid(pobj, 0x18) and d.u32(pobj) == 0 and d.is_ptr_field(pobj + 8)):
            return False
        return not (mobj and not (d.valid(mobj, 0x10) and d.u32(mobj) == 0))

    def looks_like_jobj(self, off: int) -> bool:
        d = self.dat
        if not d.valid(off, 0x40) or d.u32(off) != 0:
            return False
        flags, child, nxt, u = struct.unpack_from(">IIII", d.data, HEADER + off + 4)
        for f, v in ((8, child), (12, nxt), (16, u), (0x38, d.u32(off + 0x38))):
            if v and not d.is_ptr_field(off + f):
                return False
        # the flags word and the nine SRT floats are never pointers
        if any(d.is_ptr_field(off + f) for f in range(4, 0x38, 4) if f not in (8, 12, 16)):
            return False
        vals = d.f32s(off + 0x14, 9)
        if not all(math.isfinite(v) and abs(v) < 1e7 for v in vals):
            return False
        if not all(1e-6 < abs(v) < 1e6 for v in vals[3:6]):
            return False
        if flags & (JOBJ_SPLINE | JOBJ_PTCL):
            return False
        if u and not self.looks_like_dobj(u):
            return False
        if child and not self.looks_like_jobj_shallow(child):
            return False
        return bool(u or child)

    def looks_like_jobj_shallow(self, off: int) -> bool:
        d = self.dat
        if not d.valid(off, 0x40) or d.u32(off) != 0:
            return False
        if any(d.u32(off + f) and not d.is_ptr_field(off + f) for f in (8, 12, 16, 0x38)):
            return False
        if any(d.is_ptr_field(off + f) for f in range(4, 0x38, 4) if f not in (8, 12, 16)):
            return False
        return all(math.isfinite(v) for v in d.f32s(off + 0x14, 9))

    def discover_jobj_roots(self, known: set[int]) -> list[int]:
        """JOBJs reachable only through unknown structures: every pointer target that
        looks like a JOBJ and is not somebody's child/next."""
        cands = {p for p in self.dat.pointers if p not in known and self.looks_like_jobj(p)}
        referenced: set[int] = set()
        for c in cands:
            referenced.add(self.dat.u32(c + 8))
            referenced.add(self.dat.u32(c + 12))
        return sorted(c for c in cands if c not in referenced)


def _rgba(v: int) -> tuple[float, float, float, float]:
    return ((v >> 24) / 255, ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255)


# -- root-type dispatch ----------------------------------------------------------------


def _modelset_joint(d: DatFile, off: int) -> int:
    """HSD_ModelSet: joint, animjoints, matanimjoints, shapeanimjoints."""
    return d.u32(off) if d.valid(off, 0x10) else 0


def _ptr_list(d: DatFile, off: int, limit: int = 4096) -> list[int]:
    out = []
    k = 0
    while d.valid(off + k * 4) and k < limit:
        p = d.u32(off + k * 4)
        if not p:
            break
        out.append(p)
        k += 1
    return out


def models(dat: DatFile, parser: Parser | None = None) -> list[Model]:
    """Every drawable model in the archive, grouped the way the game groups them."""
    p = parser or Parser(dat)
    d = dat
    out: list[Model] = []
    handled: set[int] = set()

    def add(name: str, roots: list[int]) -> None:
        trees: list[Jobj] = []
        for r in roots:
            if r in handled or not r:
                continue
            for j in p.jobj_chain(r):
                if j.offset in handled:
                    continue
                trees.append(j)
                handled.update(x.offset for x in j.walk())
        if trees:
            out.append(Model(name, trees))

    for root in d.roots:
        if root.reference:
            continue
        n, off = root.name, root.offset
        if (
            n.endswith("_joint")
            and not n.endswith(("_matanim_joint", "_animjoint"))
            and not n.endswith("_shapeanim_joint")
        ):
            add(n[: -len("_joint")], [off])
        elif n.endswith("_head") and d.valid(off, 0x10):
            grp, count = d.u32(off + 8), d.u32(off + 12)
            joints = []
            for i in range(min(count, 4096)):
                g = grp + i * 0x34
                if d.valid(g, 0x34):
                    joints.append(d.u32(g))
            add(n, joints)
        elif n.endswith("_model_set"):
            add(n[: -len("_model_set")], [_modelset_joint(d, off)])
        elif n.endswith("_scene_data") and d.valid(off, 0x10):
            sets = _ptr_list(d, d.u32(off))
            add(n[: -len("_scene_data")], [_modelset_joint(d, s) for s in sets])
        elif n.endswith("_scene_models"):
            add(n[: -len("_scene_models")], [_modelset_joint(d, s) for s in _ptr_list(d, off)])
    # models buried in game-specific tables (items, trophies, menus): structural search
    for off in p.discover_jobj_roots(handled):
        if off not in handled:
            add(f"jobj_{off:06x}", [off])
    for m in out:
        m.warnings = list(p.warnings)
    return out


# -- geometry evaluation -----------------------------------------------------------------


def rotation_matrix(rot: tuple[float, float, float]) -> np.ndarray:
    rx, ry, rz = rot
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx  # HSD_MtxSRT: X, then Y, then Z


def quat_from_matrix(m: np.ndarray) -> tuple[float, float, float, float]:
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
    if i == 0:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if i == 1:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


def local_matrix(j: Jobj, parent: Jobj | None) -> np.ndarray:
    """HSD_MtxSRT with the parent's scale compensated the way HSD does when the parent is
    not flagged CLASSICAL_SCALE (rows / columns scaled by parent scale ratios)."""
    m = np.eye(4)
    rs = rotation_matrix(j.rotation) @ np.diag(j.scale)
    if parent is not None and not parent.flags & JOBJ_CLASSICAL_SCALE:
        ps = np.array(parent.scale, dtype=np.float64)
        if np.all(np.abs(ps) > 1e-8) and not np.allclose(ps, 1.0):
            rs = np.diag(1.0 / ps) @ rs @ np.diag(ps)
    m[:3, :3] = rs
    m[:3, 3] = j.position
    return m


def world_matrices(trees: list[Jobj]) -> tuple[list[Jobj], list[np.ndarray]]:
    """Number joints in HSD traversal order (depth first, children before siblings) and
    return their world matrices."""
    order: list[Jobj] = []
    world: list[np.ndarray] = []

    def visit(j: Jobj, parent: Jobj | None) -> None:
        j.index = len(order)
        j.parent = parent.index if parent is not None else None
        order.append(j)
        lm = local_matrix(j, parent)
        world.append((world[parent.index] @ lm) if parent is not None else lm)
        for c in j.children:
            visit(c, j)

    for t in trees:
        visit(t, None)
    return order, world


def decode_colors(raw: bytes, comp_type: int) -> np.ndarray:
    """GX colour components -> (N,4) float32."""
    if comp_type == 0:  # RGB565
        v = np.frombuffer(raw, ">u2").astype(np.uint32)
        r, g, b = ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31
        a = np.full_like(r, 255)
    elif comp_type in (1, 2):  # RGB8 / RGBX8
        k = 3 if comp_type == 1 else 4
        n = len(raw) // k
        v = np.frombuffer(raw, np.uint8, n * k).reshape(n, k).astype(np.uint32)
        r, g, b = v[:, 0], v[:, 1], v[:, 2]
        a = np.full_like(r, 255)
    elif comp_type == 3:  # RGBA4
        v = np.frombuffer(raw, ">u2").astype(np.uint32)
        r, g, b, a = (((v >> s) & 15) * 17 for s in (12, 8, 4, 0))
    elif comp_type == 4:  # RGBA6
        n = len(raw) // 3
        v = np.frombuffer(raw, np.uint8, n * 3).reshape(n, 3).astype(np.uint32)
        packed = (v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]
        r, g, b, a = (((packed >> s) & 63) * 255 // 63 for s in (18, 12, 6, 0))
    elif comp_type == 5:  # RGBA8
        n = len(raw) // 4
        v = np.frombuffer(raw, np.uint8, n * 4).reshape(n, 4).astype(np.uint32)
        r, g, b, a = v[:, 0], v[:, 1], v[:, 2], v[:, 3]
    else:
        raise HsdError(f"bad colour type {comp_type}")
    return (np.stack([r, g, b, a], axis=1).astype(np.float32) / 255.0).astype(np.float32)


def _comp_count(attr: int, cnt: int) -> int:
    if attr == VA_POS:
        return 2 if cnt == 0 else 3
    if attr == VA_NRM:
        return 3 if cnt == 0 else 9
    if attr == VA_NBT:
        return 9
    if attr in (VA_CLR0, VA_CLR1):
        return 3 if cnt == 0 else 4
    if VA_TEX0 <= attr <= VA_TEX7:
        return 1 if cnt == 0 else 2
    return 1


def _direct_bytes(a: VtxAttr) -> int:
    if a.attr <= VA_TEX7MTXIDX:
        return 1
    if a.attr in (VA_CLR0, VA_CLR1):
        return _COLOR_BYTES.get(a.comp_type, 4)
    return _comp_count(a.attr, a.comp_cnt) * np.dtype(_COMP_DTYPE.get(a.comp_type, ">f4")).itemsize


@dataclass
class DrawCall:
    """One GX primitive: per-corner attribute values (indices for indexed attributes,
    values for direct ones) plus the triangulated corner order."""

    opcode: int
    count: int
    fields: dict[int, np.ndarray]  # attr -> (count,) int for indexed / (count,k) for direct


def parse_display_list(dl: bytes, attrs: list[VtxAttr]) -> list[DrawCall]:
    fields = []
    for a in attrs:
        name = f"a{a.attr}"
        if a.attr_type == GX_INDEX8:
            fields.append((name, ">u1"))
        elif a.attr_type == GX_INDEX16:
            fields.append((name, ">u2"))
        elif a.attr_type == GX_DIRECT:
            fields.append((name, "u1", (_direct_bytes(a),)))
        # attr_type 0 (GX_NONE): nothing in the stream
    if not fields:
        return []
    vdt = np.dtype(fields)
    stride = vdt.itemsize
    out: list[DrawCall] = []
    pos = 0
    n = len(dl)
    while pos + 3 <= n:
        op = dl[pos]
        if op == 0:
            break
        count = dl[pos + 1] << 8 | dl[pos + 2]
        pos += 3
        end = pos + count * stride
        if end > n:
            break
        arr = np.frombuffer(dl, dtype=vdt, count=count, offset=pos)
        pos = end
        vals: dict[int, np.ndarray] = {}
        for a in attrs:
            if a.attr_type == 0:
                continue
            col = arr[f"a{a.attr}"]
            vals[a.attr] = col.astype(np.int64) if a.attr_type != GX_DIRECT else col
        out.append(DrawCall(op & 0xF8, count, vals))
    return out


def triangulate(opcode: int, n: int) -> np.ndarray:
    """(T,3) local corner indices for a primitive of n corners."""
    if n < 3:
        return np.zeros((0, 3), np.int64)
    if opcode == PRIM_TRIANGLES:
        return np.arange(n - n % 3).reshape(-1, 3)
    if opcode == PRIM_TRISTRIP:
        i = np.arange(n - 2)
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        return np.stack([i, b, c], axis=1)
    if opcode == PRIM_TRIFAN:
        i = np.arange(1, n - 1)
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    if opcode == PRIM_QUADS:
        q = np.arange(n // 4) * 4
        return np.concatenate(
            [np.stack([q, q + 1, q + 2], axis=1), np.stack([q, q + 2, q + 3], axis=1)]
        )
    return np.zeros((0, 3), np.int64)


class AttrReader:
    """Resolves an attribute's per-corner values (indexed or direct) to float arrays."""

    def __init__(self, dat: DatFile) -> None:
        self.dat = dat
        self._cache: dict[tuple, np.ndarray] = {}

    def array(self, a: VtxAttr, n: int) -> np.ndarray:
        """First n entries of an indexed attribute's array as (n,k) float32.

        `n` is one past the largest index a display list used, and a mis-read display list can
        make that enormous.  The array is padded to `n` so an out-of-range index still lands
        somewhere, but the padding has to be bounded by what the file could hold: a `.dat`
        whose header happens to reconcile can otherwise ask for gigabytes and the reader dies
        with a bare `MemoryError` - or, worse, spends an hour in the allocator.  Seen live on
        Dragon Drive's `sd12_000.dat`, where it stalled a whole shard of the library pass.
        """
        if n > self.dat.size:
            raise HsdError(
                f"a display list indexes {n} vertices in a {self.dat.size}-byte file"
            )
        key = (a.data, a.stride, a.comp_type, a.comp_cnt, a.frac, a.attr, n)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        k = _comp_count(a.attr, a.comp_cnt)
        avail = max(0, min(n, (self.dat.size - a.data) // max(a.stride, 1)))
        if a.attr in (VA_CLR0, VA_CLR1):
            w = _COLOR_BYTES.get(a.comp_type, 4)
            out = np.ones((n, 4), np.float32)
            if avail:
                raw = self.dat.bytes(a.data, avail * a.stride)
                rows = np.frombuffer(raw, np.uint8).reshape(avail, a.stride)[:, :w]
                out[:avail] = decode_colors(rows.tobytes(), a.comp_type)
        else:
            dt = np.dtype(_COMP_DTYPE.get(a.comp_type, ">f4"))
            out = np.zeros((n, k), np.float32)
            if avail:
                raw = self.dat.bytes(a.data, avail * a.stride)
                need = k * dt.itemsize
                if a.stride < need:
                    avail = 0
                else:
                    rows = np.frombuffer(raw, np.uint8).reshape(avail, a.stride)[:, :need]
                    vals = np.frombuffer(np.ascontiguousarray(rows).tobytes(), dt).reshape(avail, k)
                    out[:avail] = vals.astype(np.float32)
                    if a.comp_type != 4 and a.frac:
                        out[:avail] /= float(1 << a.frac)
        self._cache[key] = out
        return out

    def direct(self, a: VtxAttr, raw: np.ndarray) -> np.ndarray:
        """Direct attribute bytes (count, bytes) -> (count,k) float32."""
        if a.attr <= VA_TEX7MTXIDX:
            return raw[:, 0].astype(np.float32).reshape(-1, 1)
        if a.attr in (VA_CLR0, VA_CLR1):
            return decode_colors(np.ascontiguousarray(raw).tobytes(), a.comp_type)
        k = _comp_count(a.attr, a.comp_cnt)
        dt = np.dtype(_COMP_DTYPE.get(a.comp_type, ">f4"))
        vals = np.frombuffer(np.ascontiguousarray(raw).tobytes(), dt).reshape(-1, k)
        vals = vals.astype(np.float32)
        if a.comp_type != 4 and a.frac:
            vals = vals / float(1 << a.frac)
        return vals


# -- textures -------------------------------------------------------------------------------


def decode_texture(dat: DatFile, img: ImageDesc, tlut: Tlut | None) -> np.ndarray:
    if img.fmt not in gx_texture.TILE_DIMS:
        raise HsdError(f"texture format {img.fmt} unsupported")
    if img.width == 0 or img.height == 0 or img.width > 2048 or img.height > 2048:
        raise HsdError(f"bad texture size {img.width}x{img.height}")
    size = gx_texture.encoded_size(img.fmt, img.width, img.height)
    if not dat.valid(img.data, 1):
        raise HsdError("texture data out of range")
    raw = dat.bytes(img.data, size)
    palette = None
    if img.fmt in (8, 9, 10):
        if tlut is None or not dat.valid(tlut.data, 2):
            raise HsdError("paletted texture without a tlut")
        entries = {8: 16, 9: 256, 10: 16384}[img.fmt]
        count = max(1, min(tlut.count, entries, (dat.size - tlut.data) // 2))
        palette = gx_texture.decode_palette(tlut.fmt, dat.bytes(tlut.data, count * 2), count)
        if len(palette) < entries:  # pad so every index the format can produce resolves
            pad = np.zeros((entries - len(palette), 4), np.uint8)
            palette = np.concatenate([palette, pad])
    return gx_texture.decode(img.fmt, img.width, img.height, raw, palette)
