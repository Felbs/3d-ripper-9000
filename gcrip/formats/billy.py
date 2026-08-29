"""Billy Hatcher and the Giant Egg (GameCube) ``.arc`` models: Sonic Team's Ginja geometry in
an object tree.  Big-endian; every pointer is relative to 0x20 (the end of the file header).

Header (0x20): ``u32 file size | u32 pointer table | u32 type | 0 | 0 | "0100" | 0 | 0`` (the
pointer table at the end is the file's relocation list), a type record at 0x20 (type 0x20 =
model: ``u32 root rel`` etc.; type 0x10 = UI resource without an object tree), then object
headers of 0x5c bytes from 0x60: ``u32 flags | u32 | f32 position[3] | u32[3] | f32 scale[3]
| u32 child | u32 sibling | 0xfdfdfdfd | u32 vertex sets | 0 | u32 mesh records | 0 | u32
mesh count << 16 | 0 | f32 centre[3] | f32 radius`` followed inline by the Ginja vertex-set
table (``u8 attribute, u8 size, u16 count, u32 struct|type<<4, u32 data, u32 bytes``, 0xff
ends).  Mesh records are ``u32 parameters | u32 count | u32 primitives | u32 size``; the
parameters are Ginja's (``u8 type .. u32 data``: 1 = index attribute flags, 8 = texture id)
and the primitives raw GX strips whose rows hold the enabled u8 / u16 indices.  The embedded
GVM (``GVMH``) holds the textures (gcrip.formats.gvr).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gvr

BASE = 0x20
_OPS = (0x80, 0x90, 0x98, 0xA0)


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    indices: np.ndarray
    texture: int


def is_arc(head: bytes, size: int | None = None) -> bool:
    if len(head) < 0x18 or head[0x14:0x18] != b"0100":
        return False
    total, table = struct.unpack_from(">2I", head, 0)
    if size is not None and total != size:
        return False
    return 0x60 < table <= total


def _vertex_sets(d: bytes, off: int) -> dict[int, np.ndarray]:
    sets: dict[int, np.ndarray] = {}
    p = off
    for _ in range(12):
        if p + 16 > len(d):
            break
        attr, ssize, count, structure, ptr = struct.unpack_from(">BBHII", d, p)
        p += 16
        if attr == 0xFF:
            break
        dtype = (structure >> 4) & 0xF
        data = BASE + ptr
        if count == 0 or ssize == 0 or data + count * ssize > len(d):
            continue
        if dtype == 4:
            arr = np.frombuffer(d, ">f4", count * ssize // 4, data).reshape(count, -1)
            arr = arr.astype(np.float32)
        elif dtype == 3:
            arr = np.frombuffer(d, ">i2", count * ssize // 2, data).reshape(count, -1)
            arr = arr.astype(np.float32) / (256.0 if attr >= 5 else 1.0)
        elif dtype == 1:
            arr = np.frombuffer(d, np.int8, count * ssize, data).reshape(count, -1)
            arr = arr.astype(np.float32) / 127.0
        else:
            continue
        sets[attr] = arr
    return sets


def _mesh(d: bytes, params: int, pcount: int, prims: int, psize: int, sets) -> Mesh | None:
    pos, nrm, uv = sets.get(1), sets.get(2), sets.get(5)
    if pos is None:
        return None
    flags = 0x828
    texture = -1
    for k in range(min(pcount, 64)):
        q = params + k * 8
        if q + 8 > len(d):
            break
        ptype, data = d[q], struct.unpack_from(">I", d, q + 4)[0]
        if ptype == 1:
            flags = data & 0xFFFF
        elif ptype == 8:
            texture = data & 0xFFFF
    has = [bool(flags & 8), bool(flags & 0x20), bool(flags & 0x80), bool(flags & 0x800)]
    wide = [bool(flags & 4), bool(flags & 0x10), bool(flags & 0x40), bool(flags & 0x400)]
    stride = sum((2 if w else 1) for h, w in zip(has, wide, strict=True) if h)
    if not has[0] or stride == 0:
        return None
    p, end = prims, min(prims + psize, len(d))
    rows_all = []
    tris = []
    base = 0
    while p + 3 <= end:
        op = d[p] & 0xF8
        if d[p] == 0:
            p += 1
            continue
        if op not in _OPS:
            break
        cnt = (d[p + 1] << 8) | d[p + 2]
        p += 3
        if cnt == 0 or p + cnt * stride > end:
            break
        rows = np.frombuffer(d, np.uint8, cnt * stride, p).reshape(cnt, stride)
        p += cnt * stride
        cols = {}
        c = 0
        for name, h, w in zip(("pos", "nrm", "col", "uv"), has, wide, strict=True):
            if not h:
                continue
            if w:
                cols[name] = (rows[:, c].astype(np.int64) << 8) | rows[:, c + 1]
                c += 2
            else:
                cols[name] = rows[:, c].astype(np.int64)
                c += 1
        if cols["pos"].max() >= len(pos):
            continue
        n = cnt
        if op == 0x98:
            t = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(n - 2)]
        elif op == 0x90:
            t = [(k, k + 1, k + 2) for k in range(0, n - 2, 3)]
        elif op == 0xA0:
            t = [(0, k, k + 1) for k in range(1, n - 1)]
        else:
            continue
        rows_all.append(cols)
        tris.append(np.array(t, np.uint32).reshape(-1, 3) + base)
        base += n
    if not rows_all:
        return None
    pi = np.concatenate([r["pos"] for r in rows_all])
    mesh_nrm = mesh_uv = None
    if nrm is not None and all("nrm" in r for r in rows_all):
        ni = np.concatenate([r["nrm"] for r in rows_all])
        if ni.max() < len(nrm):
            mesh_nrm = nrm[ni][:, :3].astype(np.float32)
    if uv is not None and all("uv" in r for r in rows_all):
        ui = np.concatenate([r["uv"] for r in rows_all])
        if ui.max() < len(uv):
            mesh_uv = uv[ui][:, :2].astype(np.float32)
    return Mesh(
        pos[pi][:, :3].astype(np.float32),
        mesh_nrm,
        mesh_uv,
        np.concatenate(tris).reshape(-1),
        texture,
    )


def parse(d: bytes) -> tuple[list[Mesh], list[gvr.Texture]]:
    """(meshes in world space, GVM textures) of an .arc."""
    if not is_arc(d[:0x60], len(d)):
        return [], []
    table = struct.unpack_from(">I", d, 4)[0]
    gvm_off = d.find(b"GVMH", 0x60)
    textures = gvr.gvm_textures(d[gvm_off:]) if gvm_off > 0 else []
    limit = min(table, gvm_off if gvm_off > 0 else table) - 0x5C
    meshes: list[Mesh] = []
    seen: set[int] = set()

    def walk(o: int, origin: np.ndarray, depth: int) -> None:
        while 0x60 <= o < limit and o not in seen and len(seen) < 2048 and depth < 64:
            seen.add(o)
            w = struct.unpack_from(">23I", d, o)
            if w[13] != 0xFDFDFDFD:
                return
            pos = np.array(struct.unpack_from(">3f", d, o + 8), np.float32)
            scale = np.array(struct.unpack_from(">3f", d, o + 0x20), np.float32)
            if not np.isfinite(pos).all() or np.abs(pos).max() > 1e6:
                pos = np.zeros(3, np.float32)
            if not np.isfinite(scale).all() or (scale == 0).any():
                scale = np.ones(3, np.float32)
            child, sibling, vsets, region, count = w[11], w[12], w[14], w[16], w[18] >> 16
            world = origin + pos
            sets = _vertex_sets(d, BASE + vsets) if vsets else {}
            for i in range(min(count, 256)):
                r = BASE + region + i * 16
                if r + 16 > len(d):
                    break
                pp, pc, prp, psz = struct.unpack_from(">4I", d, r)
                m = _mesh(d, BASE + pp, pc, BASE + prp, psz, sets)
                if m is not None:
                    m.positions = (m.positions * scale + world).astype(np.float32)
                    meshes.append(m)
            if child:
                walk(BASE + child, world, depth + 1)
            o = BASE + sibling if sibling else 0

    walk(0x60, np.zeros(3, np.float32), 0)
    return meshes, textures
