"""Artificial Mind & Movement's 2004-05 engine on GameCube (Scooby-Doo! Unmasked, Scaler):
the ``HG`` graphics layer's objects and worlds inside the per-level ``.ghr`` archive, and the
``.htd`` texture dictionaries.

Read from the shipped ``engine_ret.elf`` symbol tables (no map): the level archive is the
same ``DTStreamFAT`` as Mystery Mayhem's ``.gcr`` (``gcrip.formats.a2m_gcr``), but the class
91 ``EF3dObjRes`` and class 24 ``EFStatic3dObj`` records are ``DTBinaryPersistStream``
serialisations read field by field through the stream's virtual ``LoadData`` slots (big
endian, packed, no alignment).  The transcription below follows ``EF3dObjRes::Load3dObj``,
``EF3dObjLODRes::Load3dObjLOD``, ``EFSkinSurface`` / ``EFRigidSurfaceGroup``,
``HGDynamicSurface_SP::LoadFromStream`` / ``ImportMaterials`` / ``ImportSubSurfaces`` /
``ReadVertex``, ``EFStatic3dObj::LoadFromStream``, ``EFSpace::LoadPVSFromStream``,
``EFEnvCloneMgr::LoadFromStream``, ``HGStaticSurfaceContainer::LoadFromStream`` and
``HGTextureDictionary`` / ``HGTexture_SP`` / ``HGPalette``::

    object   u8 path length, path; u8[12] header; u16; u16 bones; u16 LODs; u16 has matrices;
             u8[16]; bones x (f32[16] local matrix, u16 parent, u16 child, u16 sibling, u16,
             u32); [bones x f32[16] inverse bind]; [(LODs - 1) x f32 distance]; u16;
             LODs x (u16 skins x (u16 n, u16[n] bone list, dynamic surface),
                     u16 rigid bones, [u16[n] bone list, dynamic surface])
    dynamic  u32 flags; u32 materials x (u8[4] colour, f32[3], u32 vertex flags, u32
    surface  pipeline, u32 textures x (u32, char[32] name)); u32 sub-surfaces x (u32, u32
             material, u32 vertices x vertex, then rigid: u32 strips, u16[strips] lengths,
             f32[4 x strips] spheres, u16 n, u16[n] corner order, u32 bytes, GX list;
             skinned: u32 strips, u16[strips], u16 n, u16[n] - or, on the other skin
             pipeline, u16 n triangles x u8[20] (three u16 corners), u16 m, u8[8 m]); u32 n,
             u8[8 n]
    vertex   by the material's vertex flags: 1 f32[3] position, 2 f32[3] normal,
             4 u8[4] colour, 8 f32[2] texcoord, 16 f32[2] (dropped), 32 f32[4] weights +
             u8[4] bone slots (kept on skins)
    world    u8[12] header; u16 nodes, u16 leaves, u32; PVS (u32, u8[0x38], u8[(nodes -
             leaves) x leaves], u32); env clones (u16 a, u16 b, (a + b) x (u32, f32, f32,
             dynamic surface), u16 c, u16 d, u8[0x50 c], d x u32[3]); nodes x (u8[0x18]
             bounds, u8[4], u16); static container (u32 materials, u32 surfaces, materials
             as above, surfaces x (u32 groups, u32, groups x (u32 material, u32 count,
             count x (u32 skip | rigid sub-surface as above))))
    .htd     u32 palettes, u32 textures; palettes x (u32 entries, u32 words an entry (1:
             ARGB8), entries);
             textures x (char[32] name, u32 width, u32 height, u32 GX format, u32, tiles)

Triangles come from the strip lengths over the corner-order list (the GX list repeats the
same index for every attribute).  Positions are metres in bind pose; the bone matrices are
row-vector local transforms with the translation in row 3.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import a2m_gcr, gx_texture

MAX_COUNT = 1 << 20
CLASS_OBJECT = a2m_gcr.CLASS_CLUMP  # 91: EF3dObjRes
CLASS_WORLD = a2m_gcr.CLASS_WORLD  # 24: EFStatic3dObj
FLAG_POS, FLAG_NRM, FLAG_CLR, FLAG_UV, FLAG_UV2, FLAG_SKIN = 1, 2, 4, 8, 16, 32
OBJECT_EXT = ".hgobj"
WORLD_EXT = ".hgworld"
HEADER = 12


class HgError(ValueError):
    pass


class Stream:
    """``DTBinaryPersistStream``: packed big-endian fields."""

    def __init__(self, d: bytes, p: int = 0):
        self.d = d
        self.p = p

    def _take(self, fmt: str, size: int):
        if self.p + size > len(self.d):
            raise HgError(f"stream ends at {len(self.d):#x}, read at {self.p:#x}")
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return v

    def u8(self) -> int:
        return self._take(">B", 1)

    def u16(self) -> int:
        return self._take(">H", 2)

    def u32(self) -> int:
        return self._take(">I", 4)

    def f32(self) -> float:
        return self._take(">f", 4)

    def raw(self, n: int) -> bytes:
        if n < 0 or self.p + n > len(self.d):
            raise HgError(f"stream ends at {len(self.d):#x}, {n} bytes wanted at {self.p:#x}")
        v = self.d[self.p : self.p + n]
        self.p += n
        return v

    def array(self, dtype: str, count: int) -> np.ndarray:
        size = np.dtype(dtype).itemsize * count
        return np.frombuffer(self.raw(size), dtype).copy()

    def count(self, n: int, what: str) -> int:
        if n > MAX_COUNT:
            raise HgError(f"{what}: {n} is not a count")
        return n


@dataclass
class Material:
    color: tuple[int, int, int, int]
    flags: int  # vertex flags
    pipeline: int
    textures: list[str]


@dataclass
class Mesh:
    material: int
    positions: np.ndarray  # (N,3)
    triangles: np.ndarray  # (T,3)
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: np.ndarray | None = None
    joints: np.ndarray | None = None  # (N,4) object bone indices
    weights: np.ndarray | None = None


@dataclass
class Bone:
    parent: int
    matrix: np.ndarray  # (4,4) row-vector local transform


@dataclass
class Model:
    name: str
    bones: list[Bone]
    materials: list[Material]
    meshes: list[Mesh]  # the first LOD
    lods: int = 1
    warnings: list[str] = field(default_factory=list)


def _material(s: Stream) -> Material:
    color = tuple(s.u8() for _ in range(4))
    for _ in range(3):
        s.f32()
    flags = s.u32()
    pipeline = s.u32()
    n = s.count(s.u32(), "textures")
    textures = []
    for _ in range(n):
        s.u32()
        textures.append(s.raw(32).split(b"\0")[0].decode("latin-1"))
    return Material(color, flags, pipeline, textures)


def _vertices(s: Stream, flags: int, n: int, skinned: bool) -> dict[str, np.ndarray]:
    """``ReadVertex`` n times: the fields present are fixed by the material's flags, so the
    record is a fixed stride and reads as one array."""
    fields = []
    if flags & FLAG_POS:
        fields.append(("pos", ">f4", 3))
    if flags & FLAG_NRM:
        fields.append(("nrm", ">f4", 3))
    if flags & FLAG_CLR:
        fields.append(("clr", "u1", 4))
    if flags & FLAG_UV:
        fields.append(("uv", ">f4", 2))
    if flags & FLAG_UV2:
        fields.append(("uv2", ">f4", 2))
    if flags & FLAG_SKIN:
        fields.append(("weights", ">f4", 4))
        fields.append(("bones", "u1", 4))
    dtype = np.dtype([(name, dt, (cnt,)) for name, dt, cnt in fields])
    rows = np.frombuffer(s.raw(dtype.itemsize * n), dtype)
    out = {name: np.ascontiguousarray(rows[name]) for name, _, _ in fields}
    if not skinned:
        out.pop("weights", None)
        out.pop("bones", None)
    out.pop("uv2", None)
    return out


def _triangles(strips: np.ndarray, order: np.ndarray) -> np.ndarray:
    tris = []
    k = 0
    for n in strips:
        seg = order[k : k + n]
        k += n
        if len(seg) < 3:
            continue
        i = np.arange(len(seg) - 2)
        a = seg[i]
        b = np.where(i % 2 == 0, seg[i + 1], seg[i + 2])
        c = np.where(i % 2 == 0, seg[i + 2], seg[i + 1])
        tris.append(np.stack([a, b, c], 1))
    if not tris:
        return np.zeros((0, 3), np.int64)
    t = np.concatenate(tris).astype(np.int64)
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    return t[keep]


def _strips_ahead(s: Stream) -> bool:
    """Whether a skinned sub-surface continues with strips (u32 count, u16 lengths whose sum
    is the corner count that follows) rather than the triangle-record form."""
    p = s.p
    try:
        n = s.u32()
        if n > 65535:
            return False
        lengths = s.array(">u2", n)
        return int(lengths.sum()) == s.u16()
    except HgError:
        return False
    finally:
        s.p = p


def _mesh(s: Stream, material: int, flags: int, skinned: bool, warn: list[str]) -> Mesh | None:
    nv = s.count(s.u32(), "vertices")
    v = _vertices(s, flags, nv, skinned)
    tri = None
    if skinned and not _strips_ahead(s):
        # the other skin pipeline: a triangle list of 20-byte records (three u16 corners,
        # the rest zero), then u16 n and 8 n bytes
        n = s.u16()
        recs = np.frombuffer(s.raw(20 * n), np.uint8).reshape(n, 20)
        tri = np.frombuffer(np.ascontiguousarray(recs[:, :6]).tobytes(), ">u2").reshape(n, 3)
        tri = tri.astype(np.int64)
        s.raw(8 * s.u16())
        order = tri.reshape(-1)
    else:
        nstrips = s.count(s.u32(), "strips")
        strips = s.array(">u2", nstrips)
        if not skinned:
            s.raw(16 * nstrips)  # a bounding sphere a strip
        n = s.u16()
        order = s.array(">u2", n)
        if not skinned:
            s.raw(s.count(s.u32(), "display list"))  # the GX list repeats these indices
        tri = _triangles(strips, order)
    if "pos" not in v or nv == 0:
        return None  # legitimate: a material without positions draws nothing
    if len(order) and order.max() >= nv:
        warn.append(f"sub-surface: corner {int(order.max())} outside {nv} vertices")
        return None
    return Mesh(
        material,
        v["pos"].astype(np.float32),
        tri,
        v.get("nrm"),
        v.get("clr"),
        v.get("uv"),
        v.get("bones"),
        v.get("weights"),
    )


def _dynamic_surface(s: Stream, warn: list[str]) -> tuple[list[Material], list[Mesh]]:
    s.u32()  # surface flags
    mats = [_material(s) for _ in range(s.count(s.u32(), "materials"))]
    meshes = []
    for _ in range(s.count(s.u32(), "sub-surfaces")):
        s.u32()
        mi = s.u32()
        if mi >= len(mats):
            raise HgError(f"material {mi} of {len(mats)}")
        flags = mats[mi].flags
        m = _mesh(s, mi, flags, bool(flags & FLAG_SKIN), warn)
        if m is not None:
            meshes.append(m)
    s.raw(8 * s.count(s.u32(), "extras"))
    return mats, meshes


def _lod(s: Stream, warn: list[str]) -> tuple[list[Material], list[Mesh]]:
    mats: list[Material] = []
    meshes: list[Mesh] = []

    def add(bones: np.ndarray | None):
        m, ms = _dynamic_surface(s, warn)
        base = len(mats)
        mats.extend(m)
        for mesh in ms:
            mesh.material += base
            if mesh.joints is not None and bones is not None and len(bones):
                mesh.joints = bones[np.minimum(mesh.joints, len(bones) - 1)].astype(np.uint16)
            meshes.append(mesh)

    for _ in range(s.u16()):
        add(s.array(">u2", s.u16()))
    rigid = s.u16()
    if rigid:
        add(s.array(">u2", rigid))
    return mats, meshes


def parse_object(data: bytes) -> Model:
    """A class-91 ``EF3dObjRes`` record: the path, the object header, bones and LODs."""
    s = Stream(data)
    path = s.raw(s.u8()).decode("latin-1")
    name = path.replace("\\", "/").rsplit("/", 1)[-1] or "object"
    s.raw(HEADER)
    s.u16()
    nbones = s.count(s.u16(), "bones")
    nlods = s.count(s.u16(), "LODs")
    matrices = s.u16()
    s.raw(16)
    bones = []
    for _ in range(nbones):
        m = s.array(">f4", 16).reshape(4, 4)
        parent = s.u16()
        s.u16()
        s.u16()
        s.u16()
        s.u32()
        bones.append(Bone(parent if parent < nbones else -1, m))
    if matrices:
        s.raw(64 * nbones)
    if nlods > 1:
        s.raw(4 * (nlods - 1))
    s.u16()
    warn: list[str] = []
    mats: list[Material] = []
    meshes: list[Mesh] = []
    for k in range(nlods):
        m, ms = _lod(s, warn)
        if k == 0:
            mats, meshes = m, ms
    return Model(name, bones, mats, meshes, nlods, warn)


def _static_material(s: Stream) -> Material:
    color = tuple(s.u8() for _ in range(4))
    for _ in range(3):
        s.f32()
    flags = s.u32()
    s.u32()
    n = s.count(s.u32(), "textures")
    textures = []
    for _ in range(n):
        s.u32()
        textures.append(s.raw(32).split(b"\0")[0].decode("latin-1"))
    return Material(color, flags, 0, textures)


def parse_world(data: bytes) -> Model:
    """A class-24 ``EFStatic3dObj`` record: the octree / PVS, the environment clones and the
    static surface container (the level geometry, in world space)."""
    s = Stream(data)
    s.raw(HEADER)
    nodes = s.u16()
    leaves = s.u16()
    s.u32()
    s.u32()
    s.raw(0x38)
    s.raw(max(0, nodes - leaves) * leaves)
    s.u32()
    warn: list[str] = []
    a = s.u16()
    b = s.u16()
    for _ in range(a + b):
        s.u32()
        s.f32()
        s.f32()
        _dynamic_surface(s, warn)  # an environment clone model; placement not read
    c = s.u16()
    d = s.u16()
    s.raw(0x50 * c)
    s.raw(12 * d)
    for _ in range(nodes):
        s.raw(0x18 + 4 + 2)
    nmat = s.count(s.u32(), "materials")
    nsurf = s.count(s.u32(), "surfaces")
    mats = [_static_material(s) for _ in range(nmat)]
    meshes: list[Mesh] = []
    for _ in range(nsurf):
        groups = s.count(s.u32(), "groups")
        s.u32()
        for _ in range(groups):
            mi = s.u32()
            if mi >= len(mats):
                raise HgError(f"material {mi} of {len(mats)}")
            for _ in range(s.count(s.u32(), "sub-surfaces")):
                if s.u32():
                    continue
                m = _mesh(s, mi, mats[mi].flags, False, warn)
                if m is not None:
                    meshes.append(m)
    return Model("world", [], mats, meshes, 1, warn)


# ---------------------------------------------------------------------------
# .htd texture dictionaries
# ---------------------------------------------------------------------------


def is_htd(head: bytes, size: int) -> bool:
    if len(head) < 16 or size < 16:
        return False
    npal, ntex, entries, fmt = struct.unpack_from(">4I", head, 0)
    if not (npal <= 4096 and 0 < ntex <= 65536):
        return False
    if npal:
        return entries in (16, 256) and fmt < 16
    return size > 32 + 16 and all(32 <= c < 127 for c in head[8:16].split(b"\0")[0])


@dataclass
class Texture:
    name: str
    width: int
    height: int
    fmt: int
    rgba: np.ndarray | None
    error: str | None = None


def parse_htd(data: bytes) -> list[Texture]:
    s = Stream(data)
    npal = s.count(s.u32(), "palettes")
    ntex = s.count(s.u32(), "textures")
    palettes = []
    for _ in range(npal):
        n = s.count(s.u32(), "palette entries")
        fmt = s.u32()
        raw = s.raw(4 * max(1, min(fmt, 16)) * n)  # the format counts the words an entry
        argb = np.frombuffer(raw[: 4 * n], np.uint8).reshape(n, 4)
        palettes.append(np.ascontiguousarray(argb[:, [1, 2, 3, 0]]))
    out = []
    for _ in range(ntex):
        name = s.raw(32).split(b"\0")[0].decode("latin-1")
        w, h, fmt, extra = (s.u32() for _ in range(4))
        if fmt not in gx_texture.TILE_DIMS or not (0 < w <= 4096 and 0 < h <= 4096):
            raise HgError(f"{name}: texture {w}x{h} format {fmt}")
        raw = s.raw(gx_texture.encoded_size(fmt, w, h))
        tex = Texture(name, w, h, fmt, None)
        try:
            pal = palettes[extra] if fmt in (8, 9, 10) and extra < len(palettes) else None
            tex.rgba = gx_texture.decode(fmt, w, h, raw, pal)
        except Exception as e:  # noqa: BLE001 - one bad texture, the rest decode
            tex.error = str(e)
        out.append(tex)
    return out


def htd_names(data: bytes) -> list[str]:
    """Texture names without decoding (walks the same stream)."""
    s = Stream(data)
    npal = s.count(s.u32(), "palettes")
    ntex = s.count(s.u32(), "textures")
    for _ in range(npal):
        n = s.count(s.u32(), "palette entries")
        s.raw(4 * max(1, min(s.u32(), 16)) * n)
    names = []
    for _ in range(ntex):
        names.append(s.raw(32).split(b"\0")[0].decode("latin-1"))
        w, h, fmt, _extra = (s.u32() for _ in range(4))
        if fmt not in gx_texture.TILE_DIMS:
            break
        s.raw(gx_texture.encoded_size(fmt, w, h))
    return names


# ---------------------------------------------------------------------------
# the .ghr archive
# ---------------------------------------------------------------------------


def is_ghr(head: bytes, size: int) -> bool:
    """The Unmasked / Scaler level archive: Mystery Mayhem's FAT under another magic."""
    if len(head) < 32 or size < 32:
        return False
    magic, count, _, first = struct.unpack_from(">4I", head, 0)
    if magic == a2m_gcr.GCR_MAGIC or magic > 0x100000 or not 0 < count <= a2m_gcr.MAX_RECORDS:
        return False
    if 16 + a2m_gcr.RECORD * count > size:
        return False
    off, cls, _res, _size = struct.unpack_from(">4I", head, 16)
    return off == 0 and cls == CLASS_WORLD


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """The models: ``<name>.hgobj`` (class 91, named after the path inside) and
    ``world.hgworld`` (class 24)."""
    out = []
    seen: dict[str, int] = {}
    for rec in a2m_gcr.records(data):
        blob = data[rec.offset : rec.end]
        if rec.class_id == CLASS_OBJECT and blob:
            n = blob[0]
            stem = (
                blob[1 : 1 + n]
                .replace(b"\\", b"/")
                .rsplit(b"/", 1)[-1]
                .decode("latin-1", "replace")
            )
            stem = (
                "".join(c if c.isalnum() or c in "_-" else "_" for c in stem)
                or f"obj_{rec.resource:x}"
            )
            k = seen.get(stem, 0)
            seen[stem] = k + 1
            out.append((f"{stem}{'' if k == 0 else f'_{k}'}{OBJECT_EXT}", blob))
        elif rec.class_id == CLASS_WORLD:
            out.append((f"world_{rec.resource & 0xFFFFFFFF:x}{WORLD_EXT}", blob))
    return out
