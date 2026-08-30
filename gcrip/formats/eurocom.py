"""Eurocom EngineX files on GameCube: the ``Filelist.bin`` / ``Filelist.000`` virtual file
system and the ``GEOM`` ``.edb`` databases (Sphinx and the Cursed Mummy, Spyro: A Hero's
Tail, Batman Begins, Buffy: Chaos Bleeds, Robots, 007: Nightfire, Harry Potter and the
Chamber of Secrets, Ice Age 2, ...).  Structures follow the eurotools ``eurochef`` crates
and 010 templates (github.com/eurotools).  Big-endian on GameCube.

Filelist.bin (v4-7): ``u32 version | u32 size | u32 count | [v5+: u16 build type, u16
extra lists] | i32 rel. offset of the name pointer table`` then per file ``[v4: u32
offset] u32 length | u32 hashcode | u32 version | u32 flags | [v5+: u32 nlocs, (u32
offset, u32 list index) x nlocs]``; names are relative pointers to C strings (v7 obfuscates
each byte by ``+ 0x16 - file index - char index``).  Offsets index ``Filelist.000`` (and
``.001`` ...); ``.edb`` lengths in the list are the base size - the real size sits in the
EDB header.

EDB: ``"GEOM" | u32 hashcode | u32 version | u32 flags | u32 time | u32 file size | u32
base size | u32 platform versions[6]`` then, at 0x54 (versions < 248) or 0x40, hash arrays
``i16 count | i16 hash size | i32 rel. offset`` for sections, ref pointers, entities,
anims, anim skins, anim scripts, maps, anim modes, anim sets, particles, swooshes,
spreadsheets, fonts, [v248+: force feedback, materials], [v240: 8 pad bytes], textures.
Array elements start with ``u32 hashcode, u16 section, u16 debug, u32 address, u32 ptr``.
Entities: ``u32 type`` (0x601 mesh, 0x603 split) + base (flags, sort, bbox ...) + for
meshes relative pointers to the texture index list, GX tri-strips, vertices (f32 xyz +
u32), texture coordinates (s16 pairs, scaled by the top bits of the index-count word),
vertex colours (RGBA8), ...  Each GX tri-strip is ``u16, u16 texture index, u16 flags,
u16 transparency, u32 data size, u32, u32[4]`` + a display list whose vertices are four
u16 indices (position, normal, colour, uv).  Textures: ``u16 w, u16 h, u16 depth, u16
game flags, s16 scroll u/v, u8 frames, u8 images, u8 rate, pad, u8 values, u8 regions,
u8 mips, u8 format, u32, u8 colour[4], [v250+: i32 external], i16 rel x4, u32 data size,
i32 rel frame offsets[images]`` -> 64-byte GX header (byte 27 = GX format) + pixels.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

GEOM = b"GEOM"
FILELIST_NAMES = ("filelist.bin",)

# Eurocom "exformat" -> GX texture format
EXFORMAT_GX = {0: 14, 1: 6, 3: 5, 4: 0, 5: 1, 7: 2, 8: 3}


class EurocomError(ValueError):
    pass


# --------------------------------------------------------------------------- filelist


@dataclass
class FileEntry:
    name: str
    size: int
    hashcode: int
    version: int
    locations: list[tuple[int, int]]  # (offset, list index)


def _rel(data: bytes, pos: int, fmt: str = ">i") -> int:
    """Absolute target of the relative pointer stored at pos (relative to itself)."""
    off = struct.unpack_from(fmt, data, pos)[0]
    return pos + off if off else 0


def is_filelist(head: bytes) -> bool:
    if len(head) < 16:
        return False
    ver, size, count = struct.unpack_from(">3I", head, 0)
    return 4 <= ver <= 7 and 0 < count < 100_000 and size >= 16


def filelist(data: bytes) -> list[FileEntry]:
    if not is_filelist(data[:16]):
        return []
    ver, _size, count = struct.unpack_from(">3I", data, 0)
    p = 12
    if ver >= 5:
        p += 4
    names_ptr = _rel(data, p)
    p += 4
    out = []
    for _i in range(count):
        if p + 16 > len(data):
            break
        locs = []
        if ver <= 4:
            locs.append((struct.unpack_from(">I", data, p)[0], 0))
            p += 4
        length, hashcode, fver, _flags = struct.unpack_from(">4I", data, p)
        p += 16
        if ver >= 5:
            n = struct.unpack_from(">I", data, p)[0]
            p += 4
            for _ in range(min(n, 64)):
                off, idx = struct.unpack_from(">2I", data, p)
                p += 8
                locs.append((off, idx))
        out.append(FileEntry(f"{hashcode:08x}", length, hashcode, fver, locs))
    if names_ptr:
        for i, e in enumerate(out):
            sp = names_ptr + i * 4
            if sp + 4 > len(data):
                break
            s = _rel(data, sp)
            if not s or s >= len(data):
                continue
            chars = []
            j = 0
            while s + j < len(data):
                c = data[s + j]
                if ver >= 7:
                    c = (c + 0x16 - i - j) & 0xFF
                if c == 0:
                    break
                chars.append(c)
                j += 1
                if j > 512:
                    break
            name = bytes(chars).decode("latin-1", "replace")
            if name:
                e.name = name
    return out


def member_name(e: FileEntry) -> str:
    """``x:\\sphinx\\binary\\_bin_gc\\doors.edb`` -> ``sphinx/binary/_bin_gc/doors.edb``."""
    n = e.name.replace("\\", "/")
    if len(n) > 2 and n[1] == ":":
        n = n[2:]
    return n.lstrip("/")


# --------------------------------------------------------------------------- edb


@dataclass
class ArrayElement:
    hashcode: int
    section: int
    address: int


@dataclass
class TextureInfo:
    hashcode: int
    address: int
    width: int
    height: int


@dataclass
class Edb:
    data: bytes
    hashcode: int
    version: int
    flags: int
    size: int
    entities: list[ArrayElement]
    textures: list[TextureInfo]
    animskins: list[ArrayElement] = field(default_factory=list)


def is_edb(head: bytes) -> bool:
    if len(head) < 16 or head[:4] != GEOM:
        return False
    version = struct.unpack_from(">I", head, 8)[0]
    return 150 <= version <= 300


def _hash_array(data: bytes, pos: int) -> tuple[int, int]:
    """(count, absolute data offset) of the hash array at pos."""
    count = struct.unpack_from(">h", data, pos)[0]
    return max(count, 0), _rel(data, pos + 4)


def parse(data: bytes) -> Edb:
    if not is_edb(data[:16]):
        raise EurocomError("not a GEOM database")
    hashcode, version, flags, _time, size = struct.unpack_from(">5I", data, 4)
    p = 0x54 if version < 248 else 0x40
    lists = []
    n_lists = 13 + (2 if version >= 248 else 0)
    for _ in range(n_lists):
        lists.append(_hash_array(data, p))
        p += 8
    if version == 240:
        p += 8
    tex_count, tex_off = _hash_array(data, p)
    ent_count, ent_off = lists[2]
    skin_count, skin_off = lists[4]
    ent_size = 20 + (4 if version in (221, 200) else 0)
    ent_size += 12 if version < 213 or version == 221 else 0
    entities = []
    for i in range(ent_count):
        o = ent_off + i * ent_size
        if o + 16 > len(data):
            break
        h, sec, _dbg, addr = struct.unpack_from(">IHHI", data, o)
        entities.append(ArrayElement(h, sec, addr))
    textures = []
    for i in range(tex_count):
        o = tex_off + i * 28
        if o + 28 > len(data):
            break
        h, sec, _dbg, addr, _ptr, w, hgt = struct.unpack_from(">IHHIIHH", data, o)
        textures.append(TextureInfo(h, addr, w, hgt))
    skins = []
    skin_size = 28 + (8 if version in (248, 252) else 0)
    for i in range(skin_count):
        o = skin_off + i * skin_size
        if o + 16 > len(data):
            break
        h, sec, _dbg, addr = struct.unpack_from(">IHHI", data, o)
        skins.append(ArrayElement(h, sec, addr))
    return Edb(data, hashcode, version, flags, size, entities, textures, skins)


@dataclass
class Strip:
    texture: int  # index into the entity's texture list
    flags: int
    transparency: int
    positions: np.ndarray  # (N,3)
    indices: np.ndarray  # (M,) triangles
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None


@dataclass
class MeshEntity:
    hashcode: int
    address: int
    textures: list[int]  # texture_list indices into Edb.textures
    strips: list[Strip]


def _layout(version: int) -> dict[str, int]:
    """GameCube mesh-entity field offsets (from the u32 type word) per EDB version: the
    old games (Buffy 170, Sphinx 182) have no texture list and 12-byte vertices; Spyro (240)
    and Robots (248) add the list, 16-byte vertices and a 16-byte pad in the base entity;
    Batman Begins (251) and Ice Age 2 (252) put ten floats before the counts."""
    if version <= 221:
        return {
            "texture_list": 0,
            "tristrips": 0x44,
            "vertices": 0x48,
            "texcoords": 0x4C,
            "colors": 0x50,
            "normals": 0x54,
            "tristrip_count": 0x5C,
            "vertex_count": 0x60,
            "index_count": 0x68,
            "vertex_size": 12,
        }
    counts = 0xA4 if version >= 251 else 0x7C
    return {
        "texture_list": 0x54,
        "tristrips": 0x58,
        "vertices": 0x5C,
        "texcoords": 0x60,
        "colors": 0x64,
        "normals": 0x68,
        "tristrip_count": counts,
        "vertex_count": counts + 4,
        "index_count": counts + 12,
        "vertex_size": 16,
    }


def _positions(d: bytes, off: int, n: int, rec: int) -> np.ndarray | None:
    if off + n * rec > len(d):
        return None
    recs = np.frombuffer(d, ">f4", n * (rec // 4), off).reshape(n, rec // 4)
    pos = recs[:, :3].astype(np.float32)
    if not np.isfinite(pos).all() or float(np.abs(pos).max()) > 1e7:
        return None
    return pos


_OPS = (0x98, 0x90, 0x80, 0xA0)


def _gx_indices(dl: bytes):
    """GX strips in a Eurocom display list -> list of (op, index rows (N,4) u16).  The op
    is stored as a u16 (``00 98``) followed by a u16 count; raw GX bytes are accepted too."""
    out = []
    p = 0
    n = len(dl)
    while p + 4 <= n:
        if dl[p] == 0 and dl[p + 1] in _OPS:
            op = dl[p + 1]
            cnt = (dl[p + 2] << 8) | dl[p + 3]
            p += 4
        elif dl[p] in _OPS:
            op = dl[p]
            cnt = (dl[p + 1] << 8) | dl[p + 2]
            p += 3
        elif dl[p] == 0:
            p += 1
            continue
        else:
            break
        if cnt == 0 or p + cnt * 8 > n:
            break
        rows = np.frombuffer(dl, ">u2", cnt * 4, p).reshape(cnt, 4)
        out.append((op, rows))
        p += cnt * 8
    return out


def _strip_tris(op: int, n: int) -> np.ndarray:
    """Triangle index triples (into the strip's own vertex run) for a GX primitive."""
    if op == 0x98:
        t = []
        for k in range(n - 2):
            a, b, c = k, k + 1, k + 2
            t.append((a, c, b) if k % 2 else (a, b, c))
        return np.array(t, np.uint32).reshape(-1, 3)
    if op == 0x90:
        m = n - n % 3
        return np.arange(m, dtype=np.uint32).reshape(-1, 3)
    if op == 0xA0:
        return np.array([(0, k, k + 1) for k in range(1, n - 1)], np.uint32).reshape(-1, 3)
    return np.zeros((0, 3), np.uint32)


def mesh_entity(edb: Edb, el: ArrayElement, _depth: int = 0) -> list[MeshEntity]:
    """Mesh entities under an entity-list element (split entities recurse)."""
    d = edb.data
    a = el.address
    if a + 4 > len(d) or _depth > 8:
        return []
    kind = struct.unpack_from(">I", d, a)[0]
    if kind == 0x603:  # split
        p = a + 0x44 + (16 if edb.version > 221 else 0)
        count = struct.unpack_from(">I", d, p)[0]
        p += 4
        if edb.version > 213:
            p += 4
        out = []
        for _i in range(min(count, 1024)):
            if p + 4 > len(d):
                break
            sub = _rel(d, p)
            p += 4
            if sub:
                out += mesh_entity(edb, ArrayElement(el.hashcode, el.section, sub), _depth + 1)
        return out
    if kind != 0x601:
        return []
    f = _layout(edb.version)
    if a + f["index_count"] + 4 > len(d):
        return []
    tex_ptr = _rel(d, a + f["texture_list"]) if f["texture_list"] else 0
    strips_ptr = _rel(d, a + f["tristrips"])
    verts_ptr = _rel(d, a + f["vertices"])
    uv_ptr = _rel(d, a + f["texcoords"])
    col_ptr = _rel(d, a + f["colors"])
    nstrips, nverts = struct.unpack_from(">2I", d, a + f["tristrip_count"])
    index_word = struct.unpack_from(">I", d, a + f["index_count"])[0]
    uv_div = float(65536 >> ((index_word >> 28) & 7))
    textures: list[int] = []
    if tex_ptr and tex_ptr + 2 <= len(d):
        n = struct.unpack_from(">H", d, tex_ptr)[0]
        textures = list(struct.unpack_from(f">{min(n, 256)}H", d, tex_ptr + 2))
    rec = f["vertex_size"]
    if uv_ptr > verts_ptr and (uv_ptr - verts_ptr) in (nverts * 12, nverts * 16):
        rec = (uv_ptr - verts_ptr) // nverts  # skinned old-version entities carry 16 bytes
    if not (verts_ptr and nverts and verts_ptr + nverts * rec <= len(d)):
        return []
    pos = _positions(d, verts_ptr, nverts, rec)
    if pos is None:
        pos = _positions(d, verts_ptr, nverts, 28 - rec)
    if pos is None:
        return []
    nrm = None
    strips: list[Strip] = []
    p = strips_ptr
    for _ in range(min(nstrips, 4096)):
        if p + 32 > len(d):
            break
        _u1, tex, flags, trans, dsize = struct.unpack_from(">4HI", d, p)
        p += 32  # strip header: 4 x u16, u32 size, u32, 4 x u32
        dl = d[p : p + dsize]
        p += dsize
        for op, rows in _gx_indices(dl):
            n = len(rows)
            pi = rows[:, 0].astype(np.int64)
            if pi.max() >= nverts:
                continue
            tri = _strip_tris(op, n)
            if len(tri) == 0:
                continue
            P = pos[pi]
            N = None if nrm is None else nrm[pi]
            uvs = None
            if uv_ptr:
                ui = rows[:, 3].astype(np.int64)
                if uv_ptr + int(ui.max()) * 4 + 4 <= len(d):
                    raw = np.frombuffer(d, ">i2", (int(ui.max()) + 1) * 2, uv_ptr).reshape(-1, 2)
                    uvs = (raw[ui].astype(np.float32) / uv_div).astype(np.float32)
            cols = None
            if col_ptr:
                ci = rows[:, 2].astype(np.int64)
                if col_ptr + int(ci.max()) * 4 + 4 <= len(d):
                    n_c = (int(ci.max()) + 1) * 4
                    raw = np.frombuffer(d, np.uint8, n_c, col_ptr).reshape(-1, 4)
                    cols = (raw[ci].astype(np.float32) / 255.0).astype(np.float32)
            strips.append(Strip(tex, flags, trans, P, tri.reshape(-1), N, uvs, cols))
    if not strips:
        return []
    return [MeshEntity(el.hashcode, a, textures, strips)]


@dataclass
class Placement:
    hashcode: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]  # radians, applied X then Y then Z
    scale: tuple[float, float, float]
    object_ref: int
    group: int


# Placement record shapes: (stride, position, rotation, scale, object reference) offsets.
# The Sphinx-era games pack the fields tightly (56 bytes) and Spyro on adds four bytes; Buffy
# (v170) keeps each vector padded to four floats.
PLACEMENT_SHAPES = (
    (56, 4, 20, 32, 48),
    (60, 4, 20, 32, 48),
    (80, 48, 16, 32, 68),
)
_ENTITY_TAGS = (0x02, 0x82)


def maps(edb: Edb) -> list[ArrayElement]:
    """Map-list elements (list 6 of the header)."""
    d = edb.data
    p = 0x54 if edb.version < 248 else 0x40
    count, off = _hash_array(d, p + 8 * 6)
    out = []
    for i in range(count):
        o = off + i * 20
        if o + 12 > len(d):
            break
        h, sec, _dbg, addr = struct.unpack_from(">IHHI", d, o)
        out.append(ArrayElement(h, sec, addr))
    return out


def _placement_records(d: bytes, base: int, count: int, shape) -> list[Placement]:
    stride, po, ro, so, refo = shape
    out = []
    for k in range(count):
        o = base + k * stride
        if o + stride > len(d):
            break
        pos = struct.unpack_from(">3f", d, o + po)
        rot = struct.unpack_from(">3f", d, o + ro)
        scale = struct.unpack_from(">3f", d, o + so)
        ref = struct.unpack_from(">I", d, o + refo)[0]
        if not all(abs(v) < 1e6 for v in pos + scale + rot):
            continue
        out.append(Placement(0, pos, rot, scale, ref, 0))
    return out


def placements(edb: Edb, el: ArrayElement) -> list[Placement]:
    """Object placements of a map: ``u32 count | i32 rel pointer`` at +0x48 of the map header
    (``u32 0x500`` magic) then fixed-size records holding a position, an euler rotation, a
    scale and the hashcode of the entity to place.  Three record shapes are in use across the
    library (see ``PLACEMENT_SHAPES``); the one whose references name real entities wins."""
    d = edb.data
    a = el.address
    if a + 0x50 > len(d) or struct.unpack_from(">I", d, a)[0] != 0x500:
        return []
    count = struct.unpack_from(">I", d, a + 0x48)[0]
    rel = struct.unpack_from(">i", d, a + 0x4C)[0]
    base = a + 0x4C + rel
    smallest = min(sh[0] for sh in PLACEMENT_SHAPES)
    if not (0 < count < 100000) or base < 0 or base + count * smallest > len(d):
        return []
    best: list[Placement] = []
    best_score = -1
    for shape in PLACEMENT_SHAPES:
        if base + count * shape[0] > len(d):
            continue
        recs = _placement_records(d, base, count, shape)
        score = sum(1 for p in recs if (p.object_ref >> 24) in _ENTITY_TAGS)
        if score > best_score:
            best, best_score = recs, score
    return best


def texture_rgba(edb: Edb, t: TextureInfo) -> np.ndarray | None:
    """Decode the first frame of a texture with gcrip's GX decoder."""
    from gcrip.formats import gx_texture

    d = edb.data
    a = t.address
    if edb.version <= 205:
        a += 4
    if a + 0x34 > len(d):
        return None
    w, h, _depth, _gf, _su, _sv, _frames, images, _rate, _pad, _vals, _regions, _mips, fmt = (
        struct.unpack_from(">4H2h8B", d, a)
    )
    gx_fmt = EXFORMAT_GX.get(fmt)
    if gx_fmt is None or images == 0 or not (0 < w <= 2048 and 0 < h <= 2048):
        return None
    need = gx_texture.encoded_size(gx_fmt, w, h)
    # after the fixed fields: 2-4 i16 relative pointers and version-specific pads, then the
    # u32 data size and the frame pointers - take the (size, pointer) pair that lands on a
    # 64-byte GX header (byte 27 = GX format)
    for p in range(a + 0x20, a + 0x34, 4):
        size = struct.unpack_from(">I", d, p)[0]
        cand = _rel(d, p + 4)
        if not (need <= size <= need * 2 + 64 and cand > 0 and cand + 64 + need <= len(d)):
            continue
        fb = d[cand + 27]
        if fb == gx_fmt or fb in (0, 1, 2, 3, 4, 5, 6, 8, 9, 14):
            if fb in (0, 1, 2, 3, 4, 5, 6, 8, 9, 14):
                gx_fmt = fb
                need = gx_texture.encoded_size(gx_fmt, w, h)
            body = d[cand + 64 : cand + 64 + need]
            if len(body) < need:
                return None
            try:
                return gx_texture.decode(gx_fmt, w, h, body)
            except Exception:  # noqa: BLE001
                return None
    return None
