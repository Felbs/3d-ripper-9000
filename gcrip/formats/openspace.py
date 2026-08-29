"""Ubisoft OpenSpace / CPA levels on GameCube (Rayman 3: Hoodlum Havoc, Rayman Arena).

A level is a relocated memory image: ``<level>.lvl`` (big-endian, 4-byte header word then the
image) plus ``<level>.ptr`` = ``u32 count | count x (u32 target file, u32 position)`` listing
every pointer field (positions are relative to lvl + 4; target file 0 = fix.lvl, 1 = the
level, 2 = transit.lvl) followed by 16-byte fill-in records.  A pointer value is an offset
into the target file (+ 4).  Layouts follow raymap (github.com/byvar/raymap):

* SuperObject: ``u32 type (1 world, 2 perso, 4 sector, 8 physical object, 0x20/0x40 IPO)
  | data | first child | last child | u32 children | next | prev | parent | matrix | static
  matrix | i32 | u32 draw flags | u32 flags | u32 | bounding volume``; matrix = ``u32 type |
  f32[16] row-major, translation in row 3 | f32[4] scale``.
* IPO: ``physical object | radiosity | ...``; PhysicalObject: ``visual set | collide set |
  ...``; visual set: ``u32 0 | u16 lod count | u16 type | lod distances | lod data pointers``.
* GeometricObject (Rayman 3 GC): ``vertices | normals | blend weights | i32 | element types |
  elements | i32 | parallel boxes | u32 look-at | u16 vertex count | u16 element count | u16 |
  u16 boxes | sphere f32[4] | ...``; Rayman Arena GC has no i32 after the blend weights.
  Vertices / normals are ``f32 x y z`` (Z up).
* Triangle element (type 1): ``material | u16 triangles | u16 uvs | u16 uv maps | i16 lightmap
  | triangles | [R3 GC u32] | uv mapping | normals | uvs | u32 x5 (GC) | u8 visible | u8 |
  u16 mapping entries | mapping vertices | mapping uvs | u16 strip length | u16 disconnected
  triangles | strip | disconnected | name[0x34]``.  On GameCube the plain triangle list is
  empty; the optimized strip / disconnected indices address the mapping arrays (u16 vertex
  and uv indices).
* VisualMaterial: ``u32 flags | ... | u32 texture count (+0x64) | texture entry +0x68 ->
  TextureInfo``; TextureInfo: ``... | u16 height (+0x1c) | u16 width (+0x1e) | ... | name
  (+0x4a)``.  The level header holds the texture table (pointers) followed by one u32 per
  texture naming its TPL: 2 = ``<level>_lvl.tpl`` (Rayman 3) in table order, 6 =
  ``<level>_trans.tpl``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

BASE = 4
SO_TYPES = {1: "world", 2: "perso", 4: "sector", 8: "physical", 0x20: "ipo", 0x40: "ipo"}


@dataclass
class Level:
    lvl: bytes
    fix: bytes | None
    pointers: dict[int, int]  # position in lvl -> target file
    arena: bool = False

    def u32(self, a: int, buf: bytes | None = None) -> int:
        return struct.unpack_from(">I", buf or self.lvl, a)[0]

    def u16(self, a: int, buf: bytes | None = None) -> int:
        return struct.unpack_from(">H", buf or self.lvl, a)[0]

    def deref(self, pos: int) -> tuple[bytes, int] | None:
        """(buffer, offset) the pointer field at lvl position ``pos`` points to."""
        f = self.pointers.get(pos)
        if f is None:
            return None
        buf = self.lvl if f == 1 else self.fix if f == 0 else None
        if buf is None:
            return None
        v = self.u32(pos) + BASE
        return (buf, v) if v < len(buf) else None


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    indices: np.ndarray
    texture: str | None  # texture name
    tpl: tuple[int, int] | None  # (file id, index in that TPL)


@dataclass
class Instance:
    name: str
    matrix: np.ndarray  # 4x4 row-vector convention
    meshes: list[Mesh] = field(default_factory=list)


def read_ptr(ptr: bytes) -> dict[int, int]:
    if len(ptr) < 4:
        return {}
    n = struct.unpack_from(">I", ptr, 0)[0]
    if 4 + n * 8 > len(ptr):
        return {}
    out = {}
    for i in range(n):
        f, o = struct.unpack_from(">2I", ptr, 4 + i * 8)
        out[o + BASE] = f
    return out


def is_level(name: str, head: bytes) -> bool:
    low = name.lower()
    if not low.endswith(".lvl") or low.endswith(("kf.lvl", "_vb.lvl")):
        return False
    return len(head) >= 0x20 and head[:2] == b"\0\0"


# -- textures ------------------------------------------------------------------------


def texture_table(lv: Level) -> tuple[list[int], list[int]]:
    """(TextureInfo offsets, TPL file id per texture) from the level header table."""
    lvl = lv.lvl
    best: tuple[int, int] = (0, 0)
    positions = sorted(p for p in lv.pointers if p < 0x4000)
    for start in positions:
        if start < best[0] + best[1] * 4 and best[1]:
            continue
        run = 0
        p = start
        while p in lv.pointers:
            t = lv.deref(p)
            if not t or t[0] is not lvl:
                break
            o = t[1]
            if o + 0x60 > len(lvl) or not lvl[o + 0x4A : o + 0x4A + 64].split(b"\0")[
                0
            ].lower().endswith(b".tga"):
                break
            run += 1
            p += 4
        if run > best[1]:
            best = (start, run)
    start, count = best
    if not count:
        return [], []
    infos = [lv.u32(start + 4 * i) + BASE for i in range(count)]
    files = [lv.u32(start + 4 * count + 4 * i) for i in range(count)]
    return infos, files


def texture_name(lv: Level, info: int) -> str:
    return lv.lvl[info + 0x4A : info + 0x4A + 64].split(b"\0")[0].decode("latin-1", "replace")


# -- geometry ------------------------------------------------------------------------


def _strip_triangles(strip: np.ndarray) -> list[tuple[int, int, int]]:
    out = []
    for k in range(len(strip) - 2):
        a, b, c = int(strip[k]), int(strip[k + 1]), int(strip[k + 2])
        if a in (b, c) or b == c:
            continue
        out.append((a, c, b) if k % 2 else (a, b, c))
    return out


def geometric_object(
    lv: Level, buf: bytes, a: int, texinfo_index: dict[int, int], files: list[int]
) -> list[Mesh]:
    """Meshes of the GeometricObject at (buf, a)."""
    if buf is not lv.lvl:
        return []  # objects in fix.lvl are not placed by level super objects we export
    sh = 0 if lv.arena else 4  # Rayman 3 GC has an extra i32 after the blend weights
    if a + 0x40 + sh > len(buf):
        return []
    nv, ne = lv.u16(a + 0x20 + sh), lv.u16(a + 0x22 + sh)
    if not (0 < nv < 65536 and 0 < ne < 4096):
        return []
    rv, rt, re_ = lv.deref(a), lv.deref(a + 0xC + sh), lv.deref(a + 0x10 + sh)
    if not (rv and rt and re_):
        return []
    vb, vo = rv
    if vo + nv * 12 > len(vb):
        return []
    verts = np.frombuffer(vb, ">f4", nv * 3, vo).reshape(nv, 3).astype(np.float32)
    nrm = None
    rn = lv.deref(a + 4)
    if rn and rn[1] + nv * 12 <= len(rn[0]):
        nrm = np.frombuffer(rn[0], ">f4", nv * 3, rn[1]).reshape(nv, 3).astype(np.float32)
    tb, to = rt
    eb, eo = re_
    if to + ne * 2 > len(tb) or eo + ne * 4 > len(eb):
        return []
    meshes = []
    esh = 4 if not lv.arena else 0  # Rayman3GC u32 after the triangles pointer
    for i in range(ne):
        if lv.u16(to + 2 * i, tb) != 1 or (eo + 4 * i) not in lv.pointers:
            continue
        e = lv.u32(eo + 4 * i) + BASE
        if e + 0x4C + esh > len(lvl := lv.lvl):
            continue
        nuv = lv.u16(e + 6)
        opt = e + 0x30 + esh  # u8 visible | u8 | u16 mapping entries
        nmap = lv.u16(opt + 2)
        nstrip, ndisc = lv.u16(opt + 0xC), lv.u16(opt + 0xE)
        mv = lv.deref(opt + 4)
        mu = lv.deref(opt + 8)
        if not mv or nmap == 0 or mv[1] + nmap * 2 > len(mv[0]):
            continue
        mapv = np.frombuffer(mv[0], ">u2", nmap, mv[1]).astype(np.int64)
        if mapv.max() >= nv:
            continue
        tris: list[tuple[int, int, int]] = []
        sp = lv.deref(opt + 0x10)
        if nstrip >= 3 and sp and sp[1] + nstrip * 2 <= len(sp[0]):
            tris += _strip_triangles(np.frombuffer(sp[0], ">u2", nstrip, sp[1]))
        dp = lv.deref(opt + 0x14)
        if ndisc and dp and dp[1] + ndisc * 6 <= len(dp[0]):
            tris += [
                tuple(t)
                for t in np.frombuffer(dp[0], ">u2", ndisc * 3, dp[1]).reshape(-1, 3).tolist()
            ]
        if not tris:
            continue
        T = np.array(tris, np.int64)
        if T.max() >= nmap:
            continue
        uv = None
        ru = lv.deref(e + 0x18 + esh)
        if mu and ru and nuv and mu[1] + nmap * 2 <= len(mu[0]) and ru[1] + nuv * 8 <= len(ru[0]):
            mapu = np.frombuffer(mu[0], ">u2", nmap, mu[1]).astype(np.int64)
            uvs = np.frombuffer(ru[0], ">f4", nuv * 2, ru[1]).reshape(nuv, 2).astype(np.float32)
            if mapu.max() < nuv:
                uv = uvs[mapu]
        tex_name = None
        tpl = None
        rm = lv.deref(e)
        if rm and rm[0] is lvl and rm[1] + 0x70 <= len(lvl):
            m = rm[1]
            if lv.u32(m + 0x64) and (m + 0x68) in lv.pointers:
                rt_ = lv.deref(m + 0x68)
                if rt_ and rt_[0] is lvl:
                    info = rt_[1]
                    tex_name = texture_name(lv, info)
                    k = texinfo_index.get(info)
                    if k is not None:
                        fid = files[k]
                        tpl = (fid, sum(1 for j in range(k) if files[j] == fid))
        meshes.append(
            Mesh(
                verts[mapv],
                nrm[mapv] if nrm is not None else None,
                uv,
                T.reshape(-1).astype(np.uint32),
                tex_name,
                tpl,
            )
        )
    return meshes


def _matrix(lv: Level, pos: int) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    t = lv.deref(pos)
    if not t or t[0] is not lv.lvl or t[1] + 4 + 64 > len(lv.lvl):
        return m
    arr = np.frombuffer(lv.lvl, ">f4", 16, t[1] + 4).reshape(4, 4)
    if np.isfinite(arr).all() and abs(arr).max() < 1e6:
        m = arr.astype(np.float32).copy()
    if t[1] + 4 + 80 <= len(lv.lvl):
        s = np.frombuffer(lv.lvl, ">f4", 3, t[1] + 68)
        if np.isfinite(s).all() and (abs(s) < 1e4).all() and (s != 0).all():
            m[:3, :3] = m[:3, :3] * s[:, None]
    return m


def super_objects(lv: Level) -> dict[int, dict]:
    """type-validated SuperObject records keyed by offset (anchored on the matrix field)."""
    out = {}
    lvl = lv.lvl
    for pos in lv.pointers:
        so = pos - 0x20
        if so < 0 or so + 0x3C > len(lvl):
            continue
        t = lv.u32(so)
        if t not in SO_TYPES:
            continue
        ok = True
        for off in (4, 8, 0xC, 0x14, 0x18, 0x1C, 0x24):
            v = lv.u32(so + off)
            if v and (so + off) not in lv.pointers:
                ok = False
                break
        if not ok:
            continue
        out[so] = {
            "type": SO_TYPES[t],
            "data": so + 4,
            "first": lv.u32(so + 8) + BASE if lv.u32(so + 8) else 0,
            "next": lv.u32(so + 0x14) + BASE if lv.u32(so + 0x14) else 0,
            "parent": lv.u32(so + 0x1C) + BASE if lv.u32(so + 0x1C) else 0,
            "matrix": _matrix(lv, so + 0x20),
        }
    return out


def align_textures(dims: list[tuple[int, int]], tpl_dims: list[tuple[int, int]]) -> list[int]:
    """Index into the TPL for each texture-table entry: an in-order alignment that tolerates
    extra TPL images (skips) and GameCube downscales (dimension mismatches)."""
    n, m = len(dims), len(tpl_dims)
    if not n or not m:
        return [-1] * n
    INF = 10**9
    # cost[i][j] = best cost aligning dims[:i] with tpl[:j]
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[int]] = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = j  # skipped tpl images
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = cost[i - 1][j - 1] + (0 if dims[i - 1] == tpl_dims[j - 1] else 3)
            skip = cost[i][j - 1] + 1
            if match <= skip:
                cost[i][j], back[i][j] = match, 1
            else:
                cost[i][j], back[i][j] = skip, 2
    out = [-1] * n
    i, j = n, min(range(m + 1), key=lambda jj: cost[n][jj])
    while i > 0 and j > 0:
        if back[i][j] == 1:
            out[i - 1] = j - 1
            i -= 1
            j -= 1
        else:
            j -= 1
    return out


def instances(lv: Level) -> list[Instance]:
    """Placed static geometry (IPO / physical-object super objects) in world space."""
    texinfos, files = texture_table(lv)
    texinfo_index = {o: i for i, o in enumerate(texinfos)}
    sos = super_objects(lv)
    world: dict[int, np.ndarray] = {}

    def global_matrix(so: int, depth: int = 0) -> np.ndarray:
        if so in world:
            return world[so]
        rec = sos[so]
        m = rec["matrix"]
        p = rec["parent"]
        if p in sos and p != so and depth < 64:
            m = m @ global_matrix(p, depth + 1)
        world[so] = m
        return m

    out = []
    for so, rec in sos.items():
        if rec["type"] not in ("ipo", "physical"):
            continue
        d = lv.deref(rec["data"])
        if not d or d[0] is not lv.lvl:
            continue
        po = d[1]
        name = f"so_{so:x}"
        if rec["type"] == "ipo":
            r = lv.deref(po)
            if not r or r[0] is not lv.lvl:
                continue
            nm = lv.lvl[po + 0x2C : po + 0x2C + 0x32].split(b"\0")[0]
            if nm and all(32 <= c < 127 for c in nm):
                name = nm.decode()
            po = r[1]
        vs = lv.deref(po)
        if not vs or vs[0] is not lv.lvl or vs[1] + 0x14 > len(lv.lvl):
            continue
        v = vs[1]
        nlod, vtype = lv.u16(v + 4), lv.u16(v + 6)
        if nlod == 0 or vtype != 0:
            continue
        lods = lv.deref(v + 0xC)
        if not lods or lods[0] is not lv.lvl or lods[1] not in lv.pointers:
            continue
        geo = lv.deref(lods[1])
        if not geo:
            continue
        meshes = geometric_object(lv, geo[0], geo[1], texinfo_index, files)
        if meshes:
            out.append(Instance(name, global_matrix(so), meshes))
    return out
