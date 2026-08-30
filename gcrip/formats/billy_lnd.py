"""Billy Hatcher ``stg_*.lnd`` stage terrain (Sonic Team, GameCube).  Same ``0100`` file header
and 0x20-relative pointers as the ``.arc`` resources (gcrip.formats.billy), but the level is
not an object tree: it is one vertex pool drawn by raw GX display lists.

Layout (all offsets relative to 0x20 unless noted)::

  file 0x20  u32 level ptr | u32 n extra | u32 0x18 | u32 extra ptr | u32 0x20
             | u32 GVM ptr | u32 extra[n] | u32 texlist ptr | u32 texture count -> 12-byte
             NJS_TEXNAME entries (name ptr, 0, 0) right after the pair; GVM textures in
             texlist order
  level      u32 parts ptr | u32 ... ; parts: u32 material count | ptr | u32 pool count | ptr
             | u32 display-list count | ptr | u32 group count | ptr | u32 1 | u32 batch count
             | u32 batches ptr
  material   (u32 1 | u32 ptr) -> 40 bytes, word 9 = texlist index, word 8 = parameters
  pool       u32 0 | u32 slots ptr, six slots ``u8 0 | u8 kind | u16 count | u32 data``:
             position f32[3], normal f32[3], colour RGBA8, colour 1, uv s16[2] / 256, uv 1
  display    (u32 0 | u32 ptr) -> ``u32 flags | u32 data' | u32 size' | u32 data | u32 size``
             (one of the two pairs is used, the other zero); flags bit 0
             position, 1 normal, 2 colour, 3 colour 1, 4 uv, 5 uv 1: one u16 index per set bit
             in each strip row (GX 0x98 / 0x90 / 0xa0 ops)
  batch      u32 kind (1 opaque, 2, 4 translucent) | u32 count | u32 entries ptr; entries are
             20 bytes ``u32 group | u32 pool | u32 material | u32 0 | u32 display list``
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gvr

BASE = 0x20
_OPS = (0x80, 0x90, 0x98, 0xA0)


@dataclass
class Pool:
    positions: np.ndarray | None = None
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: np.ndarray | None = None


@dataclass
class Mesh:
    material: int
    translucent: bool
    positions: np.ndarray
    normals: np.ndarray | None
    colors: np.ndarray | None
    uvs: np.ndarray | None
    indices: np.ndarray


@dataclass
class Level:
    meshes: list[Mesh] = field(default_factory=list)
    material_texture: dict[int, int] = field(default_factory=dict)
    texnames: list[str] = field(default_factory=list)
    textures: list[gvr.Texture] = field(default_factory=list)


def _texlist(head: bytes) -> tuple[int, int]:
    """(file offset of the texlist pointer pair, its own file offset) - the pair follows the
    ``n`` extra-table pointers announced by the header word at 0x24."""
    extra = struct.unpack_from(">I", head, 0x24)[0]
    return 0x38 + 4 * extra, 0x38 + 4 * extra


def is_lnd(head: bytes, size: int | None = None) -> bool:
    """Recognise a terrain file.

    Must work from ``gcrip.classify.SNIFF_BYTES`` (64) bytes, which is all a plugin's
    ``detect`` is ever given - the texlist pointer pair usually sits past that.  The version
    stamp at 0x14 and the total length stored at 0 (which has to equal the file size exactly)
    are already decisive; the texlist is checked as well whenever the caller passes enough.
    """
    if len(head) < 0x28 or head[0x14:0x18] != b"0100":
        return False
    total, table = struct.unpack_from(">2I", head, 0)
    if size is not None and total != size:
        return False
    if not 0x60 < table <= total:
        return False
    pair, _ = _texlist(head)
    if pair + 8 > len(head):
        return True
    tex_ptr, tex_count = struct.unpack_from(">2I", head, pair)
    return BASE + tex_ptr == pair + 8 and 0 < tex_count < 4096


def _texnames(d: bytes) -> list[str]:
    ptr, count = struct.unpack_from(">2I", d, _texlist(d[:0x60])[0])
    names = []
    for i in range(min(count, 4096)):
        e = BASE + ptr + i * 12
        if e + 12 > len(d):
            break
        s = BASE + struct.unpack_from(">I", d, e)[0]
        z = d.find(b"\0", s)
        names.append(d[s : z if z >= 0 else len(d)].decode("latin-1", "replace"))
    return names


def _pool(d: bytes, off: int) -> Pool:
    pool = Pool()
    _zero, slots = struct.unpack_from(">2I", d, off)
    slots += BASE
    n = len(d)
    for k, attr in enumerate(("positions", "normals", "colors", None, "uvs", None)):
        e = slots + k * 8
        if e + 8 > n:
            break
        count, ptr = struct.unpack_from(">HI", d, e + 2)
        ptr += BASE
        if attr is None or count == 0 or ptr >= n:
            continue
        if attr in ("positions", "normals"):
            if ptr + count * 12 > n:
                continue
            arr = np.frombuffer(d, ">f4", count * 3, ptr).reshape(count, 3).astype(np.float32)
        elif attr == "colors":
            if ptr + count * 4 > n:
                continue
            arr = np.frombuffer(d, np.uint8, count * 4, ptr).reshape(count, 4) / 255.0
            arr = arr.astype(np.float32)
        else:
            if ptr + count * 4 > n:
                continue
            arr = np.frombuffer(d, ">i2", count * 2, ptr).reshape(count, 2) / 256.0
            arr = arr.astype(np.float32)
        setattr(pool, attr, arr)
    return pool


def _display_list(d: bytes, flags: int, data: int, size: int, pool: Pool) -> Mesh | None:
    if pool.positions is None:
        return None
    sets = [
        ("pos", pool.positions),
        ("nrm", pool.normals),
        ("col", pool.colors),
        ("col1", None),
        ("uv", pool.uvs),
        ("uv1", None),
    ]
    cols = [name for k, (name, _) in enumerate(sets) if flags & (1 << k)]
    if "pos" not in cols:
        return None
    stride = 2 * len(cols)
    p, end = data, min(data + size, len(d))
    rows_all, tris, base = [], [], 0
    while p + 3 <= end:
        if d[p] == 0:
            p += 1
            continue
        op = d[p] & 0xF8
        if op not in _OPS:
            break
        cnt = (d[p + 1] << 8) | d[p + 2]
        p += 3
        if cnt == 0 or p + cnt * stride > end:
            break
        rows = np.frombuffer(d, ">u2", cnt * len(cols), p).reshape(cnt, len(cols))
        p += cnt * stride
        if op == 0x98:
            t = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(cnt - 2)]
        elif op == 0x90:
            t = [(k, k + 1, k + 2) for k in range(0, cnt - 2, 3)]
        elif op == 0xA0:
            t = [(0, k, k + 1) for k in range(1, cnt - 1)]
        else:
            continue
        if not t:
            continue
        rows_all.append(rows)
        tris.append(np.array(t, np.uint32).reshape(-1, 3) + base)
        base += cnt
    if not rows_all:
        return None
    rows = np.concatenate(rows_all).astype(np.int64)
    out = {}
    for j, name in enumerate(cols):
        arr = dict(sets).get(name)
        if arr is None:
            continue
        idx = rows[:, j]
        if idx.max() >= len(arr):
            if name == "pos":
                return None
            continue
        out[name] = arr[idx]
    return Mesh(
        -1,
        False,
        out["pos"],
        out.get("nrm"),
        out.get("col"),
        out.get("uv"),
        np.concatenate(tris).reshape(-1),
    )


def parse(d: bytes) -> Level:
    level = Level()
    if not is_lnd(d[:0x60], len(d)):
        return level
    n = len(d)
    level.texnames = _texnames(d)
    g = d.find(b"GVMH", 0x60)
    level.textures = gvr.gvm_textures(d[g:]) if g > 0 else []
    lvl = BASE + struct.unpack_from(">I", d, BASE)[0]
    if lvl + 4 > n:
        return level
    parts = BASE + struct.unpack_from(">I", d, lvl)[0]
    if parts + 0x2C > n:
        return level
    w = struct.unpack_from(">11I", d, parts)
    n_mat, p_mat, n_pool, p_pool, n_dl, p_dl, _n_grp, _p_grp, _one, n_batch, p_batch = w
    if n_mat > 4096 or n_pool > 64 or n_dl > 65536 or n_batch > 64:
        return level
    for i in range(n_mat):
        e = BASE + p_mat + i * 8
        if e + 8 > n:
            break
        m = BASE + struct.unpack_from(">I", d, e + 4)[0]
        if m + 0x28 <= n:
            level.material_texture[i] = struct.unpack_from(">I", d, m + 0x24)[0]
    pools = []
    for i in range(n_pool):
        e = BASE + p_pool + i * 8
        pools.append(_pool(d, e) if e + 8 <= n else Pool())
    dls = []
    for i in range(n_dl):
        e = BASE + p_dl + i * 8
        if e + 8 > n:
            break
        ptr = BASE + struct.unpack_from(">I", d, e + 4)[0]
        if ptr + 20 > n:
            dls.append(None)
            continue
        flags, data0, size0, data, size = struct.unpack_from(">5I", d, ptr)
        if size == 0 and size0:
            data, size = data0, size0
        dls.append((flags, BASE + data, size))
    for b in range(n_batch):
        e = BASE + p_batch + b * 12
        if e + 12 > n:
            break
        kind, count, ptr = struct.unpack_from(">3I", d, e)
        for i in range(min(count, 65536)):
            q = BASE + ptr + i * 20
            if q + 20 > n:
                break
            _grp, pool_i, mat, _z, dl_i = struct.unpack_from(">5I", d, q)
            if dl_i >= len(dls) or dls[dl_i] is None or pool_i >= len(pools):
                continue
            flags, data, size = dls[dl_i]
            mesh = _display_list(d, flags, data, size, pools[pool_i])
            if mesh is None:
                continue
            mesh.material = mat
            mesh.translucent = kind == 4
            level.meshes.append(mesh)
    return level
