"""Ubisoft Jade engine object graph: the game objects (GAO), materials (MAT_SIN /
MAT_MSM / MAT_MTT), static LODs, worlds (WOW / WOL) and object lists that link a
GEO's material slots to textures and place it in a level.

Structures follow Ray1Map (BinarySerializer/Ray1Map, Assets/Scripts/Games/Jade/
Serializable/{OBJ,MAT,GEO,WOR,GRP,LOA}), binarized ("speed mode") layout only.
All values little-endian.

OBJ_GameObject (.gao):
  char[4] ".gao", [Montreal: u32 version], u32 editor flags, u32 identity flags,
  [Montreal v>=2: u32 name length, name], u32 status/ai/control bits,
  u8 misc (Montreal) / secto (Montpellier), u8 visi coeff, u8 lod vis, u8 lod dist,
  u8 design flags, u8 fix flags, Jade_Matrix (16 f32 I J K T with S in the 4th
  column, then u32 type flags: 2 translation, 4 rotation, 8 scale), AABB (6 f32,
  + OBB if flag 0x80000), then if BaseObject (0x1000):
    Visu (0x4000):   u32 GEO key, u32 material key, u32 draw mask, ... vertex colours
    Hierarchy (0x400000): u32 father key, Jade_Matrix local
    Anims (0x2):     u32 list tracks, u32 shape, u32 skeleton group, [Montreal:
                     bone visuals], u32 action kit
    ODE (0x10000000, Montpellier): DYN_ODE
    AdditionalMatrix (0x200000): u32 count, gizmos (GAO key + id, or a matrix)
  then if ExtendedObject (0x2000): u32 group, u32 has modifiers, f32 lod ai,
  f32 dist cut, u16 capacities, u8 ai prio, u8, u16 extra flags, then the keys
  AI / events / sound / links / light each gated by an identity flag, design
  struct, modifiers; then COL instance / col map keys; Montpellier: the name last.

GRO_Struct materials: u32 type, [Montreal: u32 object version], then
  MAT_SIN (3): ambient, diffuse, specular (RGBA u32), u32 specular exp, f32
               opacity, u32 flags, u32 texture key, u32 validate mask
  MAT_MSM (4): u32 count, u32 material keys[count]
  MAT_MTT (5): [Montpellier: ambient, diffuse] specular [Montreal v>=8: real
               specular, spec exp] [Montpellier: spec exp, f32 opacity] u32 flags,
               u32 first level pointer, u32 validate mask, [Montpellier, exp bit 31:
               u8 version, u8 sound, s16]; then levels until TextureID == 0:
               s16 texture id, u16/u32 bits, u32 flags (12 bits flags, 4 colour op,
               4 blend, 4 uv source, ...), u32 u, u32 v, [v>=9: u8 + 3 f32],
               [v>=3: u32], u32 texture key
GEO_StaticLOD (8): u8 count, u8[6] end distances, u32 GEO keys[min(count, 6)]
WOR_World (.wow): u32 version, u32 objects, [Montpellier: ambient] char[60] name,
  [Montreal: inaudible sector key], camera matrix, f32 fov, background colour,
  [Montpellier: ambient2] u32 lod cut, u32 grid keys x2, u32 game object group
  key (WOR_GameObjectGroup: u32 keys[size/4]), u32 networks, u32 text, ...
GRP_Grp: u32 group object list key (OBJ_World_GroupObjectList: u32 keys), u32 flags.

Montpellier packs (BG&E) carry no keys: files sit in the order the engine's
loader resolved references (a FIFO of requests, see LOA_Loader.LoadLoopBIN), so
`index_montpellier` replays that order to attach keys.  Montreal packs (PoP) are
keyed and `index_montreal` is a plain scan.
"""

from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import jade
from gcrip.formats.jade import (
    _R,
    GRO_GEO,
    GRO_MAT_MSM,
    GRO_MAT_MTT,
    GRO_MAT_SIN,
    GRO_STATIC_LOD,
    JadeError,
)

NULL_KEY = 0xFFFFFFFF
RLI_CODE = 0x494C5280

# OBJ_GameObject_IdentityFlags
F_BONE = 0x1
F_ANIMS = 0x2
F_LIGHTS = 0x10
F_AI = 0x20
F_DESIGN = 0x40
F_COLMAP = 0x100
F_ZDM = 0x200
F_ZDE = 0x400
F_BASE = 0x1000
F_EXTENDED = 0x2000
F_VISU = 0x4000
F_LINKS = 0x40000
F_OBBOX = 0x80000
F_ADDMATRIX = 0x200000
F_HIERARCHY = 0x400000
F_GROUP = 0x800000
F_ADDMAT_PTR = 0x1000000
F_EVENTS = 0x2000000
F_SOUND = 0x8000000
F_ODE = 0x10000000
F_SOUND_DARE = 0x20000000

# MAT_MTT level flags (low 12 bits)
MTT_TILING_U = 1
MTT_TILING_V = 2
MTT_ALPHA_TEST = 0x10
MTT_HIDE_COLOR = 0x40
MTT_ONLY_ADDITIONAL = 0x1000
UV_CHROME = 2  # uv sources: 0/1 object UVs, 2 chrome, 3-4 gizmo, 6 planar


def is_null(key: int) -> bool:
    return key in (0, NULL_KEY)


def _color(v: int) -> tuple[float, float, float, float]:
    return tuple(((v >> sh) & 255) / 255.0 for sh in (0, 8, 16, 24))


def parse_matrix(r: _R) -> np.ndarray:
    """Jade_Matrix -> 4x4 (column vectors); I/J/K are the transformed axes."""
    v = r.array("<f4", 16).astype(np.float64)
    typ = r.u32()
    m = np.eye(4)
    if typ & 4:
        m[:3, 0] = v[0:3]
        m[:3, 1] = v[4:7]
        m[:3, 2] = v[8:11]
    if typ & 8:
        m[:3, 0] *= v[3]
        m[:3, 1] *= v[7]
        m[:3, 2] *= v[11]
    if typ & 2:
        m[:3, 3] = v[12:15]
    return m


# ---------------------------------------------------------------------------
# game objects
# ---------------------------------------------------------------------------


@dataclass
class Gao:
    key: int = NULL_KEY
    name: str = ""
    version: int = 0
    flags: int = 0
    matrix: np.ndarray | None = None
    geo: int = NULL_KEY
    mat: int = NULL_KEY
    draw_mask: int = 0
    father: int = NULL_KEY
    local: np.ndarray | None = None
    list_tracks: int = NULL_KEY
    shape: int = NULL_KEY
    skeleton: int = NULL_KEY
    action_kit: int = NULL_KEY
    group: int = NULL_KEY
    refs: list[tuple[str, int]] = field(default_factory=list)  # loader order (Montpellier)
    vertex_colors: np.ndarray | None = None  # (N,4) u8 per-instance lighting (RLI)
    has_modifiers: bool = False
    complete: bool = False

    @property
    def is_bone(self) -> bool:
        return bool(self.flags & F_BONE)


def _visual(r: _R, g: Gao, montreal: bool, version: int, main: bool) -> None:
    geo = r.u32()
    mat = r.u32()
    mask = r.u32()
    if main:
        g.geo, g.mat, g.draw_mask = geo, mat, mask
        g.refs += [("geo", geo), ("mat", mat)]
    if montreal:
        if version >= 3:
            r.u8()
        if version >= 5:
            r.u8()
        r.u8()  # display order
        unk = r.u8()
        r.skip(2)
        n = r.u32()
        jade._sane(n)
        if main and n:
            g.vertex_colors = r.array("u1", 4 * n).reshape(-1, 4)
        else:
            r.skip(4 * n)
        has_lightmap = version >= 4 or not (unk & 2)
        has_ambient = version >= 4 or not (unk & 4)
        has_fog = version >= 4 or not (unk & 0x20)
        if has_lightmap:
            r.u32()
            tex = r.u32()
            if not is_null(tex):
                cnt = r.u32()
                if cnt & 0xFFFF:
                    jade._sane(cnt)
                    for _ in range(cnt):
                        t = r.u32()
                        r.skip(24 * (t & 0xFFFF))
        if has_ambient:
            k = r.u32()
            if main:
                g.refs.append(("gao", k))
        if has_fog:
            k = r.u32()
            if main:
                g.refs.append(("gao", k))
        if 4 <= version < 7:
            r.u16()
    else:
        r.skip(4)  # display order, padding
        n = r.u32()
        if n == RLI_CODE:
            k = r.u32()
            if main:
                g.refs.append(("raw", k))
        else:
            jade._sane(n)
            if main and n:
                g.vertex_colors = r.array("u1", 4 * n).reshape(-1, 4)
            else:
                r.skip(4 * n)


def _ode(r: _R) -> None:
    version = r.u8()
    typ = r.u8()
    r.skip(2)
    if version >= 2:
        r.skip(12)
    if version >= 7:
        r.skip(68)
    if version >= 6:
        r.skip(8)
    r.skip(4)
    if typ:
        r.skip(12)
    if version >= 4:
        r.skip(44)


def _tail_name(data: bytes) -> tuple[str, int]:
    """Montpellier GAOs end with u32 length + name (NUL included); returns (name,
    offset of the length field) or ("", len(data))."""
    n = len(data)
    if n < 6 or data[-1] != 0:
        return "", n
    for pos in range(n - 6, max(-1, n - 96), -1):
        if struct.unpack_from("<I", data, pos)[0] == n - pos - 4:
            return data[pos + 4 : n - 1].decode("latin-1"), pos
    return "", n


def parse_gao(data: bytes, *, montreal: bool) -> Gao:
    if data[:4] != b".gao":
        raise JadeError("not a GAO")
    g = Gao()
    r = _R(data, 4)
    try:
        g.version = r.u32() if montreal else 0
        r.u32()  # editor flags
        g.flags = flags = r.u32()
        if montreal and g.version >= 2:
            n = r.u32()
            jade._sane(n)
            g.name = data[r.p : r.p + n].split(b"\0", 1)[0].decode("latin-1")
            r.skip(n)
        r.u32()  # status / ai / control bits
        r.skip(6)  # misc|secto, visi coeff, lod vis, lod dist, design flags, fix flags
        g.matrix = parse_matrix(r)
        r.skip(24)
        if flags & F_OBBOX:
            r.skip(24)
        if flags & F_BASE:
            if flags & F_VISU:
                _visual(r, g, montreal, g.version, True)
            if flags & F_HIERARCHY:
                g.father = r.u32()
                g.refs.append(("gao", g.father))
                g.local = parse_matrix(r)
            if flags & F_ANIMS:
                g.list_tracks = r.u32()
                g.shape = r.u32()
                g.skeleton = r.u32()
                if montreal and g.version >= 2:
                    nb = r.u32()
                    jade._sane(nb)
                    for _ in range(nb):
                        if r.u32():
                            _visual(r, g, montreal, g.version, False)
                g.action_kit = r.u32()
                g.refs.append(("raw", g.action_kit))
            if flags & F_ODE and not montreal:
                _ode(r)
            if flags & F_ADDMATRIX:
                n = r.u32()
                jade._sane(n)
                for _ in range(n):
                    if flags & F_ADDMAT_PTR:
                        k = r.u32()
                        r.u32()
                        g.refs.append(("gao", k))
                    else:
                        parse_matrix(r)
        if flags & F_EXTENDED:
            g.group = r.u32()
            if flags & F_GROUP:
                g.refs.append(("grp", g.group))
            g.has_modifiers = r.u32() != 0
            r.skip(8)  # lod ai, dist cut
            r.skip(6)  # capacities, ai prio, blank, extra flags
            if flags & F_AI:
                g.refs.append(("ai", r.u32()))
            if flags & F_EVENTS:
                g.refs.append(("raw", r.u32()))
            if flags & F_SOUND:
                k = r.u32()
                if not montreal:
                    g.refs.append(("snd", k))
            if montreal and flags & F_SOUND_DARE:
                raise JadeError("DARE sound params")
            if flags & F_LINKS:
                g.refs.append(("raw", r.u32()))
            if flags & F_LIGHTS:
                g.refs.append(("light", r.u32()))
        if not montreal:
            g.name, pos = _tail_name(data)
            if flags & F_COLMAP and pos >= 4:
                pos -= 4
                g.refs.append(("colmap", struct.unpack_from("<I", data, pos)[0]))
            if flags & (F_ZDM | F_ZDE) and pos >= 4:
                pos -= 4
                g.refs.append(("col", struct.unpack_from("<I", data, pos)[0]))
        g.complete = True
    except JadeError:
        if g.matrix is None:
            raise
    return g


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------


@dataclass
class MttLevel:
    texture: int
    flags: int  # 12 bits
    color_op: int
    blend: int
    uv_source: int


@dataclass
class Material:
    kind: int  # GRO_MAT_SIN / MSM / MTT
    key: int = NULL_KEY
    diffuse: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    opacity: float = 1.0
    texture: int = NULL_KEY  # MAT_SIN
    subs: list[int] = field(default_factory=list)  # MAT_MSM
    levels: list[MttLevel] = field(default_factory=list)  # MAT_MTT

    def texture_keys(self) -> list[int]:
        """Texture references in the order the loader resolves them."""
        if self.kind == GRO_MAT_SIN:
            return [] if is_null(self.texture) else [self.texture]
        return [lv.texture for lv in self.levels if not is_null(lv.texture)]

    def base_level(self) -> MttLevel | None:
        """The level that gives the material its colour texture: mapped with the
        object's UVs (not chrome / planar / gizmo projections, which carry
        lighting and reflections) and combined as diffuse, when there is one."""
        best = None
        best_score = 99
        for lv in self.levels:
            if is_null(lv.texture):
                continue
            score = 0
            if lv.uv_source not in (0, 1):
                score += 10
            if lv.color_op not in (0, 6, 8):
                score += 2
            if lv.flags & (MTT_HIDE_COLOR | MTT_ONLY_ADDITIONAL):
                score += 20
            if score < best_score:
                best, best_score = lv, score
        return best


def parse_material(data: bytes, *, montreal: bool) -> Material:
    r = _R(data)
    kind = r.u32()
    if kind not in (GRO_MAT_SIN, GRO_MAT_MSM, GRO_MAT_MTT):
        raise JadeError("not a material")
    ov = r.u32() if montreal else 0
    m = Material(kind)
    if kind == GRO_MAT_SIN:
        r.u32()
        m.diffuse = _color(r.u32())
        r.u32()
        r.u32()
        m.opacity = struct.unpack("<f", struct.pack("<I", r.u32()))[0]
        r.u32()
        m.texture = r.u32()
        r.u32()
    elif kind == GRO_MAT_MSM:
        n = r.u32()
        jade._sane(n)
        m.subs = [r.u32() for _ in range(n)]
    else:
        version = 0
        if not montreal:
            r.u32()
            m.diffuse = _color(r.u32())
            r.u32()
            exp = r.u32()
            m.opacity = struct.unpack("<f", struct.pack("<I", r.u32()))[0]
        else:
            r.u32()
            if ov >= 8:
                r.u32()
                r.u32()
            exp = 0
        r.u32()  # flags
        first = r.u32()
        r.u32()  # validate mask
        if not montreal:
            if exp & 0x80000000:
                version = r.u8()
                r.u8()
                r.u16()
            else:
                version = 1
        if first != 0:
            for _ in range(64):
                tid = r.u16()
                if ov < 7:
                    r.u16()
                else:
                    r.u32()
                fl = r.u32()
                r.u32()
                r.u32()
                if ov >= 9:
                    r.skip(13)
                if ov >= 3:
                    r.u32()
                tex = r.u32()
                if 2 <= version <= 0x12 and r.u32():
                    raise JadeError("xenon material data")
                m.levels.append(
                    MttLevel(tex, fl & 0xFFF, (fl >> 12) & 15, (fl >> 16) & 15, (fl >> 20) & 15)
                )
                if tid == 0:
                    break
    if r.p != r.n:
        raise JadeError(f"material size mismatch: read {r.p} of {r.n}")
    return m


def parse_static_lod(data: bytes, *, montreal: bool) -> list[int]:
    r = _R(data)
    if r.u32() != GRO_STATIC_LOD:
        raise JadeError("not a static LOD")
    if montreal:
        r.u32()
    n = r.u8()
    r.skip(6)
    keys = [r.u32() for _ in range(min(n, 6))]
    if r.p != r.n:
        raise JadeError("LOD size mismatch")
    return keys


# ---------------------------------------------------------------------------
# worlds and lists
# ---------------------------------------------------------------------------


@dataclass
class Wow:
    key: int = NULL_KEY
    name: str = ""
    objects: int = NULL_KEY  # WOR_GameObjectGroup key
    refs: list[tuple[str, int]] = field(default_factory=list)
    gaos: list[int] = field(default_factory=list)  # filled once the group is read


def parse_wow(data: bytes, *, montreal: bool) -> Wow:
    if data[:4] != b".wow":
        raise JadeError("not a WOW")
    r = _R(data, 4)
    w = Wow()
    r.u32()
    r.u32()
    if not montreal:
        r.u32()
    w.name = data[r.p : r.p + 60].split(b"\0", 1)[0].decode("latin-1")
    r.skip(60)
    if montreal:
        w.refs.append(("raw", r.u32()))
    parse_matrix(r)
    r.u32()
    r.u32()
    if not montreal:
        r.u32()
    r.u32()  # lod cut
    g0 = r.u32()
    g1 = r.u32()
    if montreal:
        w.refs.append(("raw", g1 if not is_null(g1) else g0))
    else:
        w.refs += [("grid", g0), ("grid", g1)]
    w.objects = r.u32()
    w.refs.append(("gol", w.objects))
    w.refs.append(("raw", r.u32()))  # networks
    return w


def parse_wol(data: bytes) -> list[tuple[int, str]]:
    out = []
    for i in range(0, len(data) - 7, 8):
        key = struct.unpack_from("<I", data, i)[0]
        ext = data[i + 4 : i + 8].split(b"\0", 1)[0].decode("latin-1")
        out.append((key, ext))
    return out


def parse_keys(data: bytes) -> list[int]:
    n = len(data) // 4
    return list(struct.unpack_from(f"<{n}I", data, 0)) if n else []


# ---------------------------------------------------------------------------
# the indexed world
# ---------------------------------------------------------------------------


@dataclass
class World:
    montreal: bool
    gaos: dict[int, Gao] = field(default_factory=dict)
    geos: dict[int, jade.Geo] = field(default_factory=dict)
    mats: dict[int, Material] = field(default_factory=dict)
    lods: dict[int, list[int]] = field(default_factory=dict)
    raw: dict[int, bytes] = field(default_factory=dict)  # every keyed file
    wows: list[Wow] = field(default_factory=list)
    unkeyed_geos: list[tuple[int, jade.Geo]] = field(default_factory=list)  # (offset, geo)
    tex_order: list[int] = field(default_factory=list)  # first-reference order
    stats: dict[str, int] = field(default_factory=dict)
    parent: World | None = None  # the fix: objects loaded before every level
    resolver: object = None  # key -> World holding it (another keyed pack), or None

    def _chain(self, key: int):
        w = self
        while w is not None:
            yield w
            w = w.parent
        if self.resolver is not None:
            other = self.resolver(key)
            if other is not None and other is not self:
                yield other

    def find_mat(self, key: int) -> Material | None:
        for w in self._chain(key):
            m = w.mats.get(key)
            if m is not None:
                return m
        return None

    def find_gao(self, key: int) -> Gao | None:
        for w in self._chain(key):
            g = w.gaos.get(key)
            if g is not None:
                return g
        return None

    def note_textures(self, m: Material) -> None:
        seen = set(self.tex_order)
        for k in m.texture_keys():
            if k not in seen:
                seen.add(k)
                self.tex_order.append(k)

    def find_raw(self, key: int) -> bytes | None:
        for w in self._chain(key):
            d = w.raw.get(key)
            if d is not None:
                return d
        return None

    def group_gaos(self, grp_key: int) -> list[int]:
        """GRP_Grp -> OBJ_World_GroupObjectList -> GAO keys."""
        grp = self.find_raw(grp_key)
        if grp is None or len(grp) < 8:
            return []
        gol = self.find_raw(struct.unpack_from("<I", grp, 0)[0])
        return [k for k in parse_keys(gol or b"") if not is_null(k)]

    def geo_of(self, key: int) -> jade.Geo | None:
        """Follow static LODs down to the first level's geometry."""
        for _ in range(4):
            for w in self._chain(key):
                g = w.geos.get(key)
                if g is not None:
                    return g
                lod = w.lods.get(key)
                if lod:
                    key = lod[0]
                    break
            else:
                return None
        return None


def _try(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except (JadeError, ValueError, struct.error, IndexError):
        return None


GRO_OTHER = {2, 6, 7, 9, 10, 11, 12, 13, 14, 15}


def classify(data: bytes, *, montreal: bool) -> tuple[str, object]:
    """Kind of a pack file by content, with the parsed object when the kind is
    proven by an exact parse: 'gao' 'wow' 'wol' '.ext' (other tagged files),
    'geo' 'mat' 'lod' (validated), 'gro' (other render objects, unvalidated)
    or 'raw'."""
    if len(data) >= 4 and data[0] == 0x2E and all(97 <= c <= 122 for c in data[1:4]):
        tag = data[:4].decode()
        return (tag[1:] if tag in (".gao", ".wow", ".wol") else tag), None
    if len(data) >= 8:
        t = struct.unpack_from("<I", data, 0)[0]
        if t == GRO_GEO:
            g = _try(jade.parse_geo, data, montreal=montreal)
            return ("geo", g) if g is not None else ("raw", None)
        if t in (GRO_MAT_SIN, GRO_MAT_MSM, GRO_MAT_MTT):
            m = _try(parse_material, data, montreal=montreal)
            return ("mat", m) if m is not None else ("raw", None)
        if t == GRO_STATIC_LOD:
            lod = _try(parse_static_lod, data, montreal=montreal)
            return ("lod", lod) if lod is not None else ("raw", None)
        if t in GRO_OTHER and (not montreal or struct.unpack_from("<I", data, 4)[0] < 64):
            return "gro", None
    return "raw", None


def sniff(data: bytes, *, montreal: bool = False) -> str:
    return classify(data, montreal=montreal)[0]


def _ingest(w: World, key: int | None, kind: str, data: bytes, offset: int, obj=None) -> object:
    """Record one file (parsed by `classify`, or parsed here for GAO / WOW)."""
    if key is not None:
        w.raw[key] = data
    if kind == "gao":
        obj = _try(parse_gao, data, montreal=w.montreal)
        if obj is not None and key is not None:
            obj.key = key
            w.gaos[key] = obj
    elif kind == "geo" and obj is not None:
        if key is not None:
            w.geos[key] = obj
        else:
            w.unkeyed_geos.append((offset, obj))
    elif kind == "mat" and obj is not None:
        w.note_textures(obj)
        if key is not None:
            obj.key = key
            w.mats[key] = obj
    elif kind == "lod" and obj is not None and key is not None:
        w.lods[key] = obj
    elif kind == "wow":
        obj = _try(parse_wow, data, montreal=w.montreal)
        if obj is not None:
            obj.key = key if key is not None else NULL_KEY
            w.wows.append(obj)
    return obj


def index_montreal(entries: list[jade.BinEntry]) -> World:
    """Keyed pack (PoP): every file is addressable, so just parse what we know."""
    w = World(montreal=True)
    for e in entries:
        kind, obj = classify(e.data, montreal=True)
        _ingest(w, e.key, kind, e.data, e.offset, obj)
    for wow in w.wows:
        wow.gaos = [k for k in parse_keys(w.raw.get(wow.objects, b"")) if not is_null(k)]
    w.stats = {"files": len(entries), "gaos": len(w.gaos), "geos": len(w.geos), "mats": len(w.mats)}
    return w


# ---------------------------------------------------------------------------
# Montpellier: replaying the loader
# ---------------------------------------------------------------------------


def split_montpellier(dec: bytes) -> list[tuple[int, bytes, bool]]:
    """(offset, data, irregular) for every file: u32 size + data, except sound
    banks (SND_UnknownBank) that are stored as char[4] type + u32 size + data."""
    out = []
    pos = 0
    n = len(dec)
    while pos + 4 <= n:
        tagged = dec[pos] == 0x2E and all(97 <= c <= 122 for c in dec[pos + 1 : pos + 4])
        if tagged and pos + 8 <= n:
            size = struct.unpack_from("<I", dec, pos + 4)[0]
            if pos + 8 + size > n:
                break
            out.append((pos, dec[pos : pos + 8 + size], True))
            pos += 8 + size
            continue
        size = struct.unpack_from("<I", dec, pos)[0]
        if pos + 4 + size > n:
            break
        out.append((pos + 4, dec[pos + 4 : pos + 4 + size], False))
        pos += 4 + size
    return out


_COMPAT = {
    "geo": {"geo", "lod", "gro"},
    "mat": {"mat"},
    "light": {"gro", "raw"},
    "gro": {"gro", "raw"},
    "gao": {"gao"},
    "wow": {"wow"},
    "ai": {"raw"},
    ".omd": {"raw"},
    ".ova": {"raw"},
    "grid": {"raw"},
    "snd": {"snd"},
    "grp": {"raw"},
    "gol": {"raw"},
    "raw": {"raw"},
    "col": {"raw"},
    "colmap": {"raw"},
}


def _looks_like_keys(data: bytes) -> bool:
    if not data or len(data) % 4:
        return False
    keys = parse_keys(data)
    return all(is_null(k) or 0 < (k >> 24) < 0xFF for k in keys)


def _fits(kind: str, data: bytes, req: _Req) -> bool:
    if kind not in _COMPAT.get(req.kind, {req.kind}):
        return False
    if req.kind == "grp":
        if len(data) != 8 or struct.unpack_from("<I", data, 4)[0] >= 0x10000:
            return False
        return _looks_like_keys(data[:4])
    if req.kind == "gol":
        return _looks_like_keys(data)
    if req.kind == "ai":
        return len(data) == 8 and _looks_like_keys(data)
    return True


def _looks_like_sound_bank(data: bytes) -> bool:
    """SND_Bank: u32 count, then (u32 key, char[4] type) references."""
    if len(data) < 12:
        return False
    count = struct.unpack_from("<I", data, 0)[0]
    return 0 < count < 4096 and (data[8] == 0x2E or data[4:12] == bytes(8))


def _children(w: World, kind: str, key: int, obj, data: bytes) -> list[tuple[str, int]]:
    if kind == "wow" and obj is not None:
        return list(obj.refs)
    if kind == "gol":
        return [("gao", k) for k in parse_keys(data)]
    if kind == "grp" and len(data) >= 8:
        return [("gol", struct.unpack_from("<I", data, 0)[0])]
    if kind == "gao" and obj is not None:
        return list(obj.refs)
    if kind == "mat" and obj is not None and obj.kind == GRO_MAT_MSM:
        return [("mat", k) for k in obj.subs]
    if kind == "lod" and isinstance(obj, list):  # static LOD
        return [("geo", k) for k in obj]
    if kind == "ai" and len(data) == 8:  # AI_Instance: model, vars
        model, vars_ = struct.unpack_from("<II", data, 0)
        return [(".omd", model), (".ova", vars_)]
    return []


def _after_load_object(w: World, g: Gao, attached: set[int]):
    """WOR_World.JustAfterLoadObject: skeletons and shapes are resolved after the
    main loop, one object at a time; each `yield` is a point where the loader
    drains its queue."""
    attached.add(g.key)
    if not (g.flags & F_ANIMS):
        return
    yield [("raw", g.shape), ("grp", g.skeleton)]
    for bk in w.group_gaos(g.skeleton):
        bone = w.gaos.get(bk)
        if bone is None or bk in attached:
            continue
        yield from _after_load_object(w, bone, attached)
        if bone.flags & F_GROUP:
            for ek in w.group_gaos(bone.group):
                e = w.gaos.get(ek)
                if e is not None and ek not in attached:
                    yield from _after_load_object(w, e, attached)
    if is_null(g.action_kit):
        yield [("raw", g.list_tracks)]


def _world_after_load(w: World, wow: Wow, attached: set[int]):
    """Runs when the world's queue has drained: JustAfterLoad for each object."""
    yield []  # let the main queue finish first
    for k in parse_keys(w.raw.get(wow.objects, b"")):
        g = w.gaos.get(k)
        if g is not None and k not in attached:
            yield from _after_load_object(w, g, attached)


@dataclass
class _Req:
    kind: str
    key: int
    group: int
    open: bool  # the requester may also have made requests we do not walk


def index_montpellier(
    dec: bytes, preloaded: set[int] | None = None, trace: list | None = None
) -> World:
    """Replay LOA_Loader over an unkeyed pack.

    A FIFO of (kind, key) requests consumes the files in order; a request whose
    key is already loaded takes no file.  Requests are grouped by the file that
    made them (a GAO's GEO / material / AI / ..., a group's objects, an MSM's
    sub-materials).  When a file does not fit the head request, a fitting
    request later in the same group - or in the next group, if the head's
    requester made no requests we cannot see (modifiers) - means the head's
    file is missing (it came from the fix, or does not exist); otherwise the
    file answers a request we did not walk and is consumed without a key."""
    w = World(montreal=False)
    files = split_montpellier(dec)
    loaded: set[int] = set(preloaded or ())
    absent: set[int] = set()
    queue: deque[_Req] = deque()
    phases: list = []  # generators run when the queue drains
    attached: set[int] = set()
    worlds: deque[int] = deque()
    stats = {"files": len(files), "matched": 0, "unexpected": 0, "dropped": 0}
    fi = 0
    first = True
    gid = 0

    def enqueue(refs, open_: bool = False) -> None:
        nonlocal gid
        gid += 1
        for kind, key in refs:
            if not is_null(key) and key not in loaded and key not in absent:
                queue.append(_Req(kind, key, gid, open_))

    def settle() -> None:
        while queue and (queue[0].key in loaded or queue[0].key in absent):
            queue.popleft()

    def refill() -> bool:
        settle()
        while not queue:
            if phases:
                try:
                    enqueue(next(phases[-1]))
                except StopIteration:
                    phases.pop()
                settle()
                continue
            if not worlds:
                return False
            queue.append(_Req("wow", worlds.popleft(), 0, False))
        return True

    def find(kind: str, data: bytes) -> int | None:
        head = queue[0]
        nxt = None
        for i, req in enumerate(queue):
            if req.key in loaded or req.key in absent:
                continue
            if req.group != head.group:
                nxt = i
                break
            if _fits(kind, data, req):
                return i
        if head.open or head.group == 0 or nxt is None:
            return None
        g2 = queue[nxt].group
        for i in range(nxt, len(queue)):
            req = queue[i]
            if req.group != g2:
                break
            if req.key in loaded or req.key in absent:
                continue
            if _fits(kind, data, req):
                return i
        return None

    while fi < len(files):
        off, data, irregular = files[fi]
        fi += 1
        kind, obj = ("snd", None) if irregular else classify(data, montreal=False)
        if first:
            first = False
            wl = parse_wol(data) if data and len(data) % 8 == 0 else []
            if wl and all(ext in (".wow", ".wol") for _, ext in wl):
                worlds.extend(key for key, ext in wl if ext == ".wow" and not is_null(key))
                continue
            if kind == "wow":
                queue.append(_Req("wow", 0, 0, False))
                queue[0].key = NULL_KEY - 1  # a key of our own for a nameless world
        # a sound bank whose type tag is blank looks like an empty file + a file
        blank = kind == "raw" and len(data) == 0 and fi < len(files)
        if blank and _looks_like_sound_bank(files[fi][1]):
            data = files[fi][1]
            fi += 1
            kind, obj = "snd", None
        if not refill():
            stats["unexpected"] += 1
            if trace is not None:
                trace.append((fi - 1, off, kind, len(data), None, "queue empty"))
            _ingest(w, None, kind, data, off, obj)
            continue
        want = find(kind, data)
        if want is None:
            stats["unexpected"] += 1
            if trace is not None:
                heads = [(r.kind, r.key) for r in list(queue)[:4]]
                trace.append((fi - 1, off, kind, len(data), heads, "unexpected"))
            _ingest(w, None, kind, data, off, obj)
            continue
        dropped = []
        for _ in range(want):
            req = queue.popleft()
            if req.key not in loaded and req.key not in absent:
                absent.add(req.key)
                dropped.append(f"{req.kind}:{req.key:08x}")
        stats["dropped"] += len(dropped)
        req = queue.popleft()
        loaded.add(req.key)
        stats["matched"] += 1
        if trace is not None:
            note = f"match drop={len(dropped)} {' '.join(dropped)}"
            trace.append((fi - 1, off, kind, len(data), (req.kind, req.key), note))
        obj = _ingest(w, req.key, kind, data, off, obj)
        ckind = req.kind if req.kind in ("gol", "grp", "ai") else kind
        open_ = isinstance(obj, Gao) and obj.has_modifiers
        enqueue(_children(w, ckind, req.key, obj, data), open_=open_)
        if kind == "wow" and obj is not None:
            phases.append(_world_after_load(w, obj, attached))
    for wow in w.wows:
        wow.gaos = [k for k in parse_keys(w.raw.get(wow.objects, b"")) if not is_null(k)]
    stats.update(gaos=len(w.gaos), geos=len(w.geos), mats=len(w.mats), unkeyed=len(w.unkeyed_geos))
    w.stats = stats
    return w


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------


@dataclass
class SlotMaterial:
    """What a GEO element's material slot resolves to."""
    key: int
    texture: int
    color: tuple[float, float, float, float]
    alpha: bool
    clamp_u: bool
    clamp_v: bool


def resolve_slot(w: World, mat_key: int, slot: int) -> SlotMaterial | None:
    m = w.find_mat(mat_key)
    if m is None:
        return None
    if m.kind == GRO_MAT_MSM:
        if not m.subs:
            return None
        return resolve_slot(w, m.subs[slot if 0 <= slot < len(m.subs) else 0], 0)
    if m.kind == GRO_MAT_SIN:
        color = m.diffuse if (m.diffuse[3] > 0 and any(m.diffuse[:3])) else (1.0, 1.0, 1.0, 1.0)
        return SlotMaterial(m.key, m.texture, color, m.opacity < 0.999, False, False)
    lv = m.base_level()
    if lv is None:
        return SlotMaterial(m.key, NULL_KEY, (1.0, 1.0, 1.0, 1.0), False, False, False)
    return SlotMaterial(
        m.key,
        lv.texture,
        (1.0, 1.0, 1.0, 1.0),
        lv.blend not in (0, 5) or bool(lv.flags & MTT_ALPHA_TEST),
        not (lv.flags & MTT_TILING_U),
        not (lv.flags & MTT_TILING_V),
    )


def geo_materials(w: World) -> dict[int, int]:
    """GEO key -> material key, from the game objects that draw it (first wins);
    LOD levels inherit their parent's material."""
    out: dict[int, int] = {}
    for g in w.gaos.values():
        if is_null(g.geo) or is_null(g.mat):
            continue
        keys = [g.geo, *w.lods.get(g.geo, [])]
        if w.parent is not None:
            keys += w.parent.lods.get(g.geo, [])
        for k in keys:
            out.setdefault(k, g.mat)
    return out
