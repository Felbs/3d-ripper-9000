"""Ninja (Sega Dreamcast SDK) models: NJ files = NJTL texture list + NJCM chunk model, and
NMDM motions. Layout checked byte-by-byte against Phantasy Star Online's .nj/.njm files.

File: sequence of ("magic", u32 size, payload) blocks: NJTL, POF0 (pointer table, ignored),
NJCM (chunk model), NMDM (motion). Pointers inside a payload are relative to its start.

NJTL: u32 names_ptr, u32 count; count x (u32 name_ptr, u32 attr, u32 texaddr); C strings.

NJCM object (NJS_CNK_OBJECT, 52 bytes):
  u32 evalflags   bit0 no-translate, bit1 no-rotate, bit2 no-scale, bit3 hide, bit4 break
                  (no children), bit5 ZXY rotation order, bit6 skip, bit7 shape-skip
  u32 model_ptr   NJS_CNK_MODEL or 0
  f32 pos[3]      s32 rot[3] (0x10000 = 360 degrees)   f32 scale[3]
  u32 child_ptr   u32 sibling_ptr
NJS_CNK_MODEL: u32 vlist_ptr (0 = none), u32 plist_ptr, f32 center[3], f32 radius.

Vertex list: chunks of (u8 type, u8 flags, u16 size_in_u32) then (u16 index_offset,
u16 count) and `count` vertices. Types 0x20-0x32 pick the per-vertex layout (see _VTX).
flags & 3 is the weight status (0 plain, 1 first, 2 middle, 3 last): weighted vertices land
in a cache shared by the whole object tree; the *_NF layouts carry (cache index | weight<<16).
Draw-only objects have no vertex list and reference the cache.

Polygon list: chunks of (u8 type, u8 flags) and, for types >= 0x10, u16 size_in_u16:
  0x00 null, 0xFF end, 0x01-0x05 bits (2 bytes), 0x08/0x09 texture id (4 bytes),
  0x11-0x17 material colours (D/A/S by bits 0/1/2, one ARGB u32 each), 0x38 bump,
  0x40-0x4B triangle strips: u16 (strip count | userflag count << 14), then per strip an
  s16 length (negative = reversed winding) and per vertex u16 index [+ s16 u, s16 v]
  [+ normal] [+ u32 colour]; user flags (u16 each) follow every triangle from the 3rd vertex.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np

NJ_ANGLE = 360.0 / 65536.0

# vertex chunk type -> (bytes per vertex, has_normal, normal_kind, extra_kind)
# extra_kind: None | "d8" (ARGB8888) | "uf" (user flags) | "nf" (ninja flags: cache idx+weight)
#             | "s5" | "s4" | "in" (two 16-bit values)
_VTX: dict[int, tuple[int, bool, str, str | None]] = {
    0x20: (16, False, "", None),  # SH: xyzw
    0x21: (32, True, "f4", None),  # VN_SH: xyzw + nrm xyzw
    0x22: (12, False, "", None),
    0x23: (16, False, "", "d8"),
    0x24: (16, False, "", "uf"),
    0x25: (16, False, "", "nf"),
    0x26: (16, False, "", "s5"),
    0x27: (16, False, "", "s4"),
    0x28: (16, False, "", "in"),
    0x29: (24, True, "f3", None),
    0x2A: (28, True, "f3", "d8"),
    0x2B: (28, True, "f3", "uf"),
    0x2C: (28, True, "f3", "nf"),
    0x2D: (28, True, "f3", "s5"),
    0x2E: (28, True, "f3", "s4"),
    0x2F: (28, True, "f3", "in"),
    0x30: (16, True, "x", None),  # VNX: packed 10-bit normal
    0x31: (20, True, "x", "d8"),
    0x32: (20, True, "x", "uf"),
}

# strip chunk type -> (uv kind, has_normal, has_color)
_STRIP: dict[int, tuple[str | None, bool, bool]] = {
    0x40: (None, False, False),
    0x41: ("n", False, False),
    0x42: ("h", False, False),
    0x43: (None, True, False),
    0x44: ("n", True, False),
    0x45: ("h", True, False),
    0x46: (None, False, True),
    0x47: ("n", False, True),
    0x48: ("h", False, True),
    0x49: (None, False, False),
    0x4A: ("n", False, False),
    0x4B: ("h", False, False),
}


class NinjaError(ValueError):
    pass


@dataclass
class Material:
    texture: int | None = None
    diffuse: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    use_alpha: bool = False
    double_sided: bool = False
    flip_u: bool = False
    flip_v: bool = False
    clamp_u: bool = False
    clamp_v: bool = False
    ignore_light: bool = False
    env_map: bool = False
    src_blend: int = 4  # NJD_SA_SRC (source alpha) default
    dst_blend: int = 1  # NJD_DA_INV_SRC default

    def key(self) -> tuple:
        return (
            self.texture, self.diffuse, self.use_alpha, self.double_sided, self.flip_u,
            self.flip_v, self.clamp_u, self.clamp_v, self.ignore_light, self.env_map,
            self.src_blend, self.dst_blend,
        )


@dataclass
class VertexWrite:
    """One vertex chunk entry: where it lands in the cache and what it carries."""

    cache_index: int
    pos: np.ndarray
    normal: np.ndarray | None
    color: np.ndarray | None
    weight: float
    status: int  # 0 plain, 1 first, 2 middle, 3 last


@dataclass
class Strip:
    material: Material
    # per corner (3 per triangle): cache index, uv, colour (or None)
    indices: list[int]
    uvs: list[tuple[float, float]] | None
    colors: list[tuple[float, float, float, float]] | None
    normals: list[tuple[float, float, float]] | None


@dataclass
class DrawSlot:
    """NJD_CB_DP: draw the polygon list another object cached under this slot."""

    slot: int


@dataclass
class Model:
    center: tuple[float, float, float]
    radius: float
    vertices: list[VertexWrite] = field(default_factory=list)
    strips: list[Strip | DrawSlot] = field(default_factory=list)
    cache_slot: int | None = None  # NJD_CB_CP: this polygon list is stored, not drawn
    warnings: list[str] = field(default_factory=list)


@dataclass
class Object:
    index: int
    offset: int
    flags: int
    pos: tuple[float, float, float]
    rot: tuple[float, float, float]  # degrees
    scale: tuple[float, float, float]
    model: Model | None
    parent: int | None
    children: list[Object] = field(default_factory=list)

    @property
    def zxy(self) -> bool:
        return bool(self.flags & 0x20)

    @property
    def hidden(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def name(self) -> str:
        return f"node_{self.index:03d}"


@dataclass
class TexList:
    names: list[str]


@dataclass
class Motion:
    frames: int
    kind: int
    # per object index: {"pos": [(frame, xyz)], "rot": [(frame, deg xyz)], "scale": [...]}
    tracks: list[dict[str, list[tuple[int, tuple[float, float, float]]]]]


@dataclass
class Ninja:
    texlist: TexList | None = None
    root: Object | None = None
    objects: list[Object] = field(default_factory=list)  # traversal order (= motion order)
    motions: list[Motion] = field(default_factory=list)
    kind: str = ""  # "chunk" | "basic"
    warnings: list[str] = field(default_factory=list)


# -- helpers ---------------------------------------------------------------------------


def _argb(v: int) -> tuple[float, float, float, float]:
    return (((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255, (v >> 24) / 255)


def _unpack_vnx(v: int) -> np.ndarray:
    # 10 bits per axis, signed, in x | y << 10 | z << 20
    def s10(x: int) -> float:
        x &= 0x3FF
        return (x - 0x400 if x & 0x200 else x) / 511.0

    return np.array([s10(v), s10(v >> 10), s10(v >> 20)], dtype=np.float32)


def rotation_matrix(rot_deg: tuple[float, float, float], zxy: bool) -> np.ndarray:
    rx, ry, rz = (math.radians(a) for a in rot_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    # Ninja applies X then Y then Z to the matrix (v' = Rz Ry Rx v); ZXY flag = Z, X, Y
    return (my @ mx @ mz) if zxy else (mz @ my @ mx)


def local_matrix(obj: Object) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = rotation_matrix(obj.rot, obj.zxy) @ np.diag(obj.scale)
    m[:3, 3] = obj.pos
    return m


# -- chunk model ------------------------------------------------------------------------


class _ChunkParser:
    def __init__(self, data: bytes, warnings: list[str]):
        self.d = data
        self.warnings = warnings
        self.objects: list[Object] = []
        self._seen: set[int] = set()

    def u8(self, o: int) -> int:
        return self.d[o]

    def u16(self, o: int) -> int:
        return struct.unpack_from("<H", self.d, o)[0]

    def s16(self, o: int) -> int:
        return struct.unpack_from("<h", self.d, o)[0]

    def u32(self, o: int) -> int:
        return struct.unpack_from("<I", self.d, o)[0]

    def object(self, off: int, parent: int | None, depth: int = 0) -> Object:
        if off in self._seen or off + 52 > len(self.d) or depth > 64:
            raise NinjaError(f"object pointer {off:#x} invalid or cyclic")
        self._seen.add(off)
        ev, mdl, px, py, pz, rx, ry, rz, sx, sy, sz, child, sib = struct.unpack_from(
            "<II3f3i3fII", self.d, off
        )
        obj = Object(
            index=len(self.objects),
            offset=off,
            flags=ev,
            pos=(px, py, pz),
            rot=(rx * NJ_ANGLE, ry * NJ_ANGLE, rz * NJ_ANGLE),
            scale=(sx, sy, sz),
            model=None,
            parent=parent,
        )
        self.objects.append(obj)
        if mdl:
            try:
                obj.model = self.model(mdl)
            except (NinjaError, struct.error, IndexError) as e:
                self.warnings.append(f"{obj.name}: model at {mdl:#x} unreadable: {e}")
        if child:
            obj.children.append(self.object(child, obj.index, depth + 1))
        if sib and parent is not None:
            # siblings share our parent; attach to it
            sibling = self.object(sib, parent, depth)
            self.objects[parent].children.append(sibling)
        elif sib:
            sibling = self.object(sib, None, depth)
            obj.children.append(sibling)  # root with a sibling: keep the tree connected
        return obj

    def model(self, off: int) -> Model:
        vlist, plist, cx, cy, cz, r = struct.unpack_from("<II4f", self.d, off)
        m = Model(center=(cx, cy, cz), radius=r)
        if vlist:
            self.vertex_list(vlist, m)
        if plist:
            self.poly_list(plist, m)
        return m

    def vertex_list(self, off: int, m: Model) -> None:
        p = off
        d = self.d
        while p + 4 <= len(d):
            t, flags, size = d[p], d[p + 1], self.u16(p + 2)
            if t == 0xFF:
                return
            if t == 0:
                p += 4
                continue
            if t not in _VTX:
                m.warnings.append(f"unknown vertex chunk {t:#x}")
                p += 4 + size * 4
                continue
            per, has_n, nkind, extra = _VTX[t]
            idx_off, count = self.u16(p + 4), self.u16(p + 6)
            status = flags & 3
            q = p + 8
            end = p + 4 + size * 4
            if q + per * count > len(d) or q + per * count > end + 4:
                raise NinjaError(f"vertex chunk {t:#x} at {p:#x} overruns")
            for i in range(count):
                pos = np.frombuffer(d, dtype="<f4", count=3, offset=q)
                o = q + (16 if t in (0x20, 0x21) else 12)
                normal = None
                if has_n:
                    if nkind == "f4":
                        normal = np.frombuffer(d, dtype="<f4", count=3, offset=o)
                        o += 16
                    elif nkind == "f3":
                        normal = np.frombuffer(d, dtype="<f4", count=3, offset=o)
                        o += 12
                    else:
                        normal = _unpack_vnx(self.u32(o))
                        o += 4
                color = None
                cache_index = idx_off + i
                weight = 1.0
                if extra == "d8":
                    color = np.array(_argb(self.u32(o)), dtype=np.float32)
                elif extra == "nf":
                    nf = self.u32(o)
                    if status:
                        cache_index = idx_off + (nf & 0xFFFF)
                        weight = ((nf >> 16) & 0xFF) / 255.0
                elif extra == "s5":
                    c = self.u16(o)
                    color = np.array(
                        [((c >> 11) & 31) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31, 1.0],
                        dtype=np.float32,
                    )
                elif extra == "s4":
                    c = self.u16(o)
                    color = np.array(
                        [((c >> 8) & 15) / 15, ((c >> 4) & 15) / 15, (c & 15) / 15, (c >> 12) / 15],
                        dtype=np.float32,
                    )
                m.vertices.append(
                    VertexWrite(cache_index, pos.astype(np.float32), normal, color, weight, status)
                )
                q += per
            p = end
        m.warnings.append("vertex list without end chunk")

    def poly_list(self, off: int, m: Model) -> None:
        p = off
        d = self.d
        mat = Material()
        while p + 2 <= len(d):
            t, flags = d[p], d[p + 1]
            if t == 0xFF:
                return
            if t == 0:
                p += 2
                continue
            if t < 0x08:  # bits chunks
                if t == 1:  # blend alpha
                    mat.src_blend, mat.dst_blend = (flags >> 3) & 7, flags & 7
                elif t == 4:  # cache polygon list: keep, another object draws it later
                    m.cache_slot = flags
                elif t == 5:  # draw polygon list
                    m.strips.append(DrawSlot(flags))
                p += 2
                continue
            if t < 0x10:  # tiny: texture id
                data = self.u16(p + 2)
                mat = Material(**{**mat.__dict__})
                mat.texture = data & 0x1FFF
                mat.clamp_v, mat.clamp_u = bool(flags & 0x10), bool(flags & 0x20)
                mat.flip_v, mat.flip_u = bool(flags & 0x40), bool(flags & 0x80)
                p += 4
                continue
            size = self.u16(p + 2)
            body = p + 4
            end = body + size * 2
            if end > len(d):
                raise NinjaError(f"poly chunk {t:#x} at {p:#x} overruns")
            if 0x10 <= t <= 0x1F:  # material
                mat = Material(**{**mat.__dict__})
                mat.src_blend, mat.dst_blend = (flags >> 3) & 7, flags & 7
                o = body
                if t & 1:
                    mat.diffuse = _argb(self.u32(o))
                    o += 4
                # ambient / specular are lighting terms; not carried into the export
            elif t == 0x38:  # bump
                pass
            elif 0x40 <= t <= 0x4B:
                smat = Material(**{**mat.__dict__})
                smat.ignore_light = bool(flags & 0x01)
                smat.use_alpha = bool(flags & 0x08)
                smat.double_sided = bool(flags & 0x10)
                smat.env_map = bool(flags & 0x40)
                self.strip_chunk(t, body, end, smat, m)
            else:
                m.warnings.append(f"unknown poly chunk {t:#x}")
            p = end
        m.warnings.append("poly list without end chunk")

    def strip_chunk(self, t: int, body: int, end: int, mat: Material, m: Model) -> None:
        uvkind, has_n, has_c = _STRIP[t]
        head = self.u16(body)
        nstrips, nuser = head & 0x3FFF, head >> 14
        # normals inside strips: 3 x s16 in most files, 3 x f32 in some; pick what fits
        for nbytes in ((6, 12) if has_n else (0,)):
            per = 2 + (4 if uvkind else 0) + nbytes + (4 if has_c else 0)
            strip = self._read_strips(
                body + 2, end, nstrips, nuser, per, uvkind, nbytes, has_c, mat
            )
            if strip is not None:
                m.strips.append(strip)
                return
        m.warnings.append(f"strip chunk {t:#x} at {body:#x} does not fit its size")

    def _read_strips(self, p, end, nstrips, nuser, per, uvkind, nbytes, has_c, mat):
        d = self.d
        idx: list[int] = []
        uvs: list[tuple[float, float]] = []
        cols: list[tuple[float, float, float, float]] = []
        nrms: list[tuple[float, float, float]] = []
        uvdiv = 256.0 if uvkind == "n" else 1024.0
        for _ in range(nstrips):
            if p + 2 > end:
                return None
            n = self.s16(p)
            p += 2
            flip = n < 0
            n = abs(n)
            corners = []
            for i in range(n):
                if p + per > end:
                    return None
                vi = self.u16(p)
                o = p + 2
                uv = (0.0, 0.0)
                if uvkind:
                    uv = (self.s16(o) / uvdiv, self.s16(o + 2) / uvdiv)
                    o += 4
                nrm = (0.0, 0.0, 1.0)
                if nbytes == 6:
                    nrm = (self.s16(o) / 32767, self.s16(o + 2) / 32767, self.s16(o + 4) / 32767)
                    o += 6
                elif nbytes == 12:
                    nrm = tuple(struct.unpack_from("<3f", d, o))
                    o += 12
                col = (1.0, 1.0, 1.0, 1.0)
                if has_c:
                    col = _argb(self.u32(o))
                    o += 4
                p += per
                if i >= 2:
                    p += 2 * nuser
                corners.append((vi, uv, nrm, col))
            for i in range(2, n):
                a, b, c = corners[i - 2], corners[i - 1], corners[i]
                if (i % 2 == 1) != flip:
                    a, b = b, a
                for v in (a, b, c):
                    idx.append(v[0])
                    uvs.append(v[1])
                    nrms.append(v[2])
                    cols.append(v[3])
        if p != end and end - p >= 4:
            return None  # leftover bigger than alignment padding: wrong layout guess
        return Strip(
            material=mat,
            indices=idx,
            uvs=uvs if uvkind else None,
            colors=cols if has_c else None,
            normals=nrms if nbytes else None,
        )


# -- basic model (NJBM: NJS_MODEL / NJS_OBJECT from Sonic Adventure) --------------------


class _BasicParser(_ChunkParser):
    """NJS_MODEL: u32 points_ptr, u32 normals_ptr, u32 nb_points, u32 meshsets_ptr,
    u32 materials_ptr, u16 nb_meshsets, u16 nb_materials, f32 center[3], f32 radius.
    NJS_MESHSET (24 bytes): u16 type_matid (type = >>14: 0 tris, 1 quads, 2 n-gons, 3 strips;
    matid = & 0x3FFF), u16 nb_mesh, u32 meshes_ptr, u32 attrs_ptr, u32 normals_ptr,
    u32 vertcolor_ptr, u32 vertuv_ptr. NJS_MATERIAL (20 bytes): u32 diffuse, u32 specular,
    f32 exponent, u32 attr_texid, u32 attrflags."""

    def model(self, off: int) -> Model:
        unpacked = struct.unpack_from("<IIIIIHH4f", self.d, off)
        pts, nrms, npts, msets_p, mats_p, nmsets, nmats, cx, cy, cz, r = unpacked
        m = Model(center=(cx, cy, cz), radius=r)
        d = self.d
        for i in range(npts):
            pos = np.frombuffer(d, dtype="<f4", count=3, offset=pts + i * 12).astype(np.float32)
            n = None
            if nrms:
                n = np.frombuffer(d, dtype="<f4", count=3, offset=nrms + i * 12).astype(np.float32)
            m.vertices.append(VertexWrite(i, pos, n, None, 1.0, 0))
        mats = []
        for i in range(nmats):
            dif, _spec, _exp, texid, attr = struct.unpack_from("<IIfII", d, mats_p + i * 20)
            tex = texid & 0xFFFF if texid != 0xFFFFFFFF else None
            mat = Material(diffuse=_argb(dif), texture=tex)
            mat.use_alpha = bool(attr & 0x10)
            mat.double_sided = bool(attr & 0x08)
            mat.flip_u, mat.flip_v = bool(attr & 0x800), bool(attr & 0x400)
            mat.clamp_u, mat.clamp_v = bool(attr & 0x200), bool(attr & 0x100)
            mat.ignore_light = bool(attr & 0x02)
            mat.env_map = bool(attr & 0x2000)
            if attr & 0x40000000 == 0:  # texture used unless NJD_FLAG_USE_TEXTURE clear
                pass
            if not attr & 0x2000000:  # NJD_FLAG_USE_TEXTURE
                mat.texture = None
            mats.append(mat)
        for i in range(nmsets):
            typ_mat, nb, meshes, _attrs, _mn, vcol, vuv = struct.unpack_from(
                "<HHIIIII", d, msets_p + i * 24
            )
            typ, matid = typ_mat >> 14, typ_mat & 0x3FFF
            mat = mats[matid] if matid < len(mats) else Material()
            idx: list[int] = []
            uvs: list[tuple[float, float]] = []
            cols: list[tuple[float, float, float, float]] = []
            p = meshes
            k = 0  # running vertex-attribute index (uv/colour arrays are per polygon corner)

            def corner(vi: int, kk: int, vuv: int = vuv, vcol: int = vcol):
                uv = (0.0, 0.0)
                if vuv:
                    uv = (self.s16(vuv + kk * 4) / 255.0, self.s16(vuv + kk * 4 + 2) / 255.0)
                col = _argb(self.u32(vcol + kk * 4)) if vcol else (1.0, 1.0, 1.0, 1.0)
                return vi, uv, col

            if typ in (0, 1):
                n = 3 if typ == 0 else 4
                for _ in range(nb):
                    cs = [corner(self.u16(p + j * 2), k + j) for j in range(n)]
                    p += n * 2
                    k += n
                    tris = [(0, 1, 2)] if n == 3 else [(0, 1, 2), (0, 2, 3)]
                    for a, b, c in tris:
                        for v in (cs[a], cs[b], cs[c]):
                            idx.append(v[0])
                            uvs.append(v[1])
                            cols.append(v[2])
            else:
                for _ in range(nb):
                    hdr = self.u16(p)
                    p += 2
                    n, flip = hdr & 0x7FFF, bool(hdr & 0x8000)
                    cs = [corner(self.u16(p + j * 2), k + j) for j in range(n)]
                    p += n * 2
                    k += n
                    if typ == 2:  # n-gon fan
                        for j in range(2, n):
                            for v in (cs[0], cs[j - 1], cs[j]):
                                idx.append(v[0])
                                uvs.append(v[1])
                                cols.append(v[2])
                    else:
                        for j in range(2, n):
                            a, b, c = cs[j - 2], cs[j - 1], cs[j]
                            if (j % 2 == 1) != flip:
                                a, b = b, a
                            for v in (a, b, c):
                                idx.append(v[0])
                                uvs.append(v[1])
                                cols.append(v[2])
            m.strips.append(
                Strip(mat, idx, uvs if vuv else None, cols if vcol else None, None)
            )
        return m


# -- motion ------------------------------------------------------------------------------


def parse_motion(data: bytes, n_objects: int) -> Motion:
    mdata, nframes, kind, _inp = struct.unpack_from("<IIHH", data, 0)
    present = [b for b, bit in (("pos", 1), ("rot", 2), ("scale", 4)) if kind & bit]
    n = len(present)
    tracks = []
    for o in range(n_objects):
        rec_off = mdata + o * 8 * n
        if rec_off + 8 * n > len(data):
            break
        rec = struct.unpack_from(f"<{2 * n}I", data, rec_off)
        tr: dict[str, list] = {}
        for k, name in enumerate(present):
            ptr, count = rec[k], rec[n + k]
            keys = []
            for i in range(count):
                o2 = ptr + i * 16
                if o2 + 16 > len(data):
                    break
                frame = struct.unpack_from("<I", data, o2)[0]
                if name == "rot":
                    x, y, z = struct.unpack_from("<3i", data, o2 + 4)
                    keys.append((frame, (x * NJ_ANGLE, y * NJ_ANGLE, z * NJ_ANGLE)))
                else:
                    keys.append((frame, tuple(struct.unpack_from("<3f", data, o2 + 4))))
            if keys:
                tr[name] = keys
        tracks.append(tr)
    return Motion(frames=nframes, kind=kind, tracks=tracks)


# -- file ------------------------------------------------------------------------------


def blocks(data: bytes):
    """Yield (magic, payload) for an NJ-style container; a bare NJCM/NJBM/NMDM payload
    (no header) is not handled here."""
    p = 0
    while p + 8 <= len(data):
        magic = data[p : p + 4]
        size = struct.unpack_from("<I", data, p + 4)[0]
        if magic not in (b"NJTL", b"NJCM", b"NJBM", b"NMDM", b"POF0", b"GJTL", b"GJCM"):
            break
        yield magic, data[p + 8 : p + 8 + size]
        p += 8 + size


def parse_texlist(payload: bytes) -> TexList:
    names_ptr, count = struct.unpack_from("<II", payload, 0)
    names = []
    for i in range(min(count, 4096)):
        np_ = struct.unpack_from("<I", payload, names_ptr + i * 12)[0]
        end = payload.find(b"\x00", np_)
        names.append(payload[np_ : end if end >= 0 else np_ + 32].decode("ascii", "replace"))
    return TexList(names)


def parse(data: bytes, *, motions: list[bytes] | None = None) -> Ninja:
    nj = Ninja()
    for magic, payload in blocks(data):
        if magic in (b"NJTL", b"GJTL"):
            nj.texlist = parse_texlist(payload)
        elif magic in (b"NJCM", b"GJCM", b"NJBM"):
            parser = (_BasicParser if magic == b"NJBM" else _ChunkParser)(payload, nj.warnings)
            nj.root = parser.object(0, None)
            nj.objects = parser.objects
            nj.kind = "basic" if magic == b"NJBM" else "chunk"
        elif magic == b"NMDM":
            nj.motions.append(parse_motion(payload, len(nj.objects)))
    for mdata in motions or []:
        for magic, payload in blocks(mdata):
            if magic == b"NMDM":
                nj.motions.append(parse_motion(payload, len(nj.objects)))
    if nj.root is None:
        raise NinjaError("no NJCM/NJBM model block")
    return nj


def is_ninja(data: bytes) -> bool:
    return data[:4] in (b"NJTL", b"NJCM", b"NJBM", b"GJTL", b"GJCM")


def is_motion(data: bytes) -> bool:
    return data[:4] == b"NMDM"
