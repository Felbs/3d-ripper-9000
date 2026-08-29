"""Krome Studios MDL3 models (Merkury engine 2004+: Ty the Tasmanian Tiger 2 / 3, The Legend
of Spyro: A New Beginning, King Arthur) as shipped on GameCube inside RKV2 archives: a
``.mdl`` table file plus a ``.mdg`` geometry file.  Big-endian throughout.

``.mdl``: ``"MDL3" | u16 subobjects | u16 textures | u16 bones | u16 refpoints | u16 | u16
blocks`` ... u32 table offsets at 0x50: ``subobjects, texture names, refpoints, bones, ?,
0, block table, 0``.  Subobject (64 B): bbox floats, u32 name @48.  Texture names: u32
string pointers.  Bones (16 B): position xyz + pad (no hierarchy in the file).  Block table:
``textures x subobjects`` u32 offsets into the ``.mdg`` (0 = no geometry for that pair).

``.mdg``: ``"MDG3"`` then geometry blocks, each ``u16 vertices | u16 uv refs | u16 | u16
primitives | u16 | u16 | u16 | u16 | u32 display list size | u32 colour size | u32 position
size | u32 uv size`` followed by the four sections.  Display-list vertices are 9 bytes:
``u16 position index, s8 normal xyz, u16 colour index, u16 uv index``.  Positions are f32
xyz per record - 16-byte records ``xyz, u8 bone a, u8 bone b, u8 weight, 0`` when the model
has bones, else 12 bytes.  Colours RGBA8; UVs s16 / 4096.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats.mdl2 import Model, Part, _gather, _triangulate

MAGIC = b"MDL3"
MAGIC_G = b"MDG3"
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}


class Mdl3Error(ValueError):
    pass


def is_mdl3(head: bytes) -> bool:
    return head[:4] == MAGIC


def _cstr(d: bytes, o: int) -> str:
    if o <= 0 or o >= len(d):
        return ""
    end = d.find(b"\0", o)
    return d[o : end if end > 0 else len(d)].decode("latin-1", "replace")


def _prims(g: bytes, base: int, size: int):
    """(prims, rows) of the display list at base: prims = (op, count, first row)."""
    p, end = base, base + size
    prims, rows = [], []
    n = 0
    while p + 3 <= end:
        op = g[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        cnt = (g[p + 1] << 8) | g[p + 2]
        if cnt == 0 or p + 3 + cnt * 9 > end:
            break
        prims.append((op & 0xF8, cnt, n))
        rows.append(np.frombuffer(g, np.uint8, cnt * 9, p + 3).reshape(cnt, 9))
        n += cnt
        p += 3 + cnt * 9
    if not prims:
        return None
    return prims, np.concatenate(rows)


def _block(g: bytes, off: int, rigged: bool):
    """One geometry block -> (positions, indices, normals, uvs, colours, joints, weights)."""
    if off + 0x20 > len(g):
        return None
    dl_size, col_size, pos_size, uv_size = struct.unpack_from(">4I", g, off + 0x10)
    base = off + 0x20
    if base + dl_size + col_size + pos_size + uv_size > len(g):
        return None
    parsed = _prims(g, base, dl_size)
    if parsed is None:
        return None
    prims, rows = parsed
    pidx = (rows[:, 0].astype(np.uint32) << 8) | rows[:, 1]
    cidx = (rows[:, 5].astype(np.uint32) << 8) | rows[:, 6]
    uidx = (rows[:, 7].astype(np.uint32) << 8) | rows[:, 8]
    # rigged models store 16-byte records, but single-bone props keep 12-byte ones: take the
    # first record size the position indices fit
    for rec in (16, 12) if rigged else (12, 16):
        nv = pos_size // rec
        if nv and pidx.max() < nv:
            break
    else:
        return None
    rigged = rigged and rec == 16
    pos_off = base + dl_size + col_size
    recs = np.frombuffer(g, np.uint8, nv * rec, pos_off).reshape(nv, rec)
    pos = np.frombuffer(recs[:, :12].tobytes(), ">f4").reshape(nv, 3).astype(np.float32)
    tri = _triangulate(prims, pidx)
    if len(tri) < 3:
        return None
    nrm = rows[:, 2:5].view(np.int8).astype(np.float32)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    normals = np.zeros((nv, 3), np.float32)
    normals[pidx] = nrm / ln
    ncol = col_size // 4
    colors = None
    if ncol and cidx.max() < ncol:
        col = np.frombuffer(g, np.uint8, ncol * 4, base + dl_size).reshape(ncol, 4) / 255.0
        colors = _gather(col.astype(np.float32), cidx, pidx, nv)
    nuv = uv_size // 4
    uvs = None
    if nuv and uidx.max() < nuv:
        uv = np.frombuffer(g, ">i2", nuv * 2, pos_off + pos_size).reshape(nuv, 2) / 4096.0
        uvs = _gather(uv.astype(np.float32), uidx, pidx, nv)
    joints = weights = None
    if rigged:
        joints = np.zeros((nv, 4), np.uint16)
        weights = np.zeros((nv, 4), np.float32)
        joints[:, 0], joints[:, 1] = recs[:, 12], recs[:, 13]
        w = recs[:, 14].astype(np.float32) / 255.0
        weights[:, 0], weights[:, 1] = w, 1.0 - w
    return pos, tri, normals, uvs, colors, joints, weights


def parse(mdl: bytes, mdg: bytes, name: str = "mdl3") -> Model:
    if not is_mdl3(mdl) or len(mdl) < 0x70 or mdg[:4] != MAGIC_G:
        raise Mdl3Error("not an MDL3 / MDG3 pair")
    nsub, ntex, nbone, _nref, _n4, _nblk = struct.unpack_from(">6H", mdl, 4)
    sub_off, tex_off, _ref_off, bone_off, _t3, _z, blk_off, _z2 = struct.unpack_from(
        ">8I", mdl, 0x50
    )
    subs = []
    for i in range(nsub):
        o = sub_off + i * 64
        if o + 64 > len(mdl):
            break
        subs.append(_cstr(mdl, struct.unpack_from(">I", mdl, o + 48)[0]) or f"sub{i}")
    if not subs:  # shadow / effect models: geometry without a subobject table
        subs = ["mesh"]
    texs = []
    for i in range(ntex):
        if tex_off + i * 4 + 4 > len(mdl):
            break
        texs.append(_cstr(mdl, struct.unpack_from(">I", mdl, tex_off + i * 4)[0]))
    bones = np.zeros((0, 3), np.float32)
    if nbone and bone_off and bone_off + nbone * 16 <= len(mdl):
        bones = np.frombuffer(mdl, ">f4", nbone * 4, bone_off).reshape(nbone, 4)[:, :3].copy()
        bones = np.where(np.isfinite(bones) & (np.abs(bones) < 1e6), bones, 0.0).astype(np.float32)
    parts: list[Part] = []
    if blk_off + len(texs) * len(subs) * 4 > len(mdl):
        return Model(name, parts, bones)
    for ti, tex in enumerate(texs):
        for si, sname in enumerate(subs):
            off = struct.unpack_from(">I", mdl, blk_off + (ti * len(subs) + si) * 4)[0]
            if off == 0:
                continue
            blk = _block(mdg, off, len(bones) > 0)
            if blk is None:
                continue
            pos, tri, normals, uvs, colors, joints, weights = blk
            if joints is not None:
                joints = np.minimum(joints, max(len(bones) - 1, 0)).astype(np.uint16)
            parts.append(Part(sname, tex, pos, tri, normals, uvs, colors, joints, weights))
    return Model(name, parts, bones)
