"""Krome Studios MDL2 models as shipped on GameCube (``.gmd`` inside RKV archives: Ty the
Tasmanian Tiger; the PC ``.mdl`` shares the tables).  Big-endian throughout.

Header: ``"MDL2" | u16 fragments | u16 subobjects | u16 colliders | u16 bones | u32
subobject table | u32 collider table | u32 bone table | u32 vertex buffer | u32 vertex
count | bbox floats``; names live in the header area.  Subobject (80 B): bounds, u32 name,
u32 material, u32 triangles, ..., u16 mesh count @66, u32 mesh table @68.  Mesh (16 B):
u32 material name, u32 display list, u32 (size / 16) << 16, u32 strips.  Display list: GX
strips whose vertices are four u16 indices (position, normal, colour, uv) into one
interleaved vertex buffer of 28-byte records: ``f32 xyz | s8 nx ny nz, u8 flag | s16 u, v
(/4096) | s16 weight (/4096), s8 bone a, s8 bone b | u8 rgba``.  Bones: 16 B each, a
position (world space) - no hierarchy in the model file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"MDL2"
PRIM_OPS = {0x80, 0x90, 0x98, 0xA0}


class Mdl2Error(ValueError):
    pass


@dataclass
class Part:
    name: str
    material: str
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    colors: np.ndarray | None = None
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None


@dataclass
class Model:
    name: str
    parts: list[Part]
    bones: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))


def is_mdl2(head: bytes) -> bool:
    return head[:4] == MAGIC


def _triangulate(prims, idx):
    from gcrip.formats.eagl import _triangulate as tri

    return tri(prims, idx)


def _cstr(d: bytes, o: int) -> str:
    if o <= 0 or o >= len(d):
        return ""
    end = d.find(b"\0", o)
    return d[o : end if end > 0 else len(d)].decode("latin-1", "replace")


def parse(d: bytes, name: str = "mdl2") -> Model:
    if not is_mdl2(d) or len(d) < 0x30:
        raise Mdl2Error("not an MDL2 model")
    _frag, nsub, _ncol, nbone = struct.unpack_from(">4H", d, 4)
    sub_off, _col_off, bone_off, vert_off = struct.unpack_from(">4I", d, 12)
    nv = struct.unpack_from(">I", d, 0x1C)[0]
    if vert_off + nv * 28 > len(d) or nv == 0:
        raise Mdl2Error("vertex buffer outside the file")
    rec = np.frombuffer(d, np.uint8, nv * 28, vert_off).reshape(nv, 28)
    pos = np.frombuffer(rec[:, :12].tobytes(), ">f4").reshape(nv, 3).astype(np.float32)
    nrm = rec[:, 12:15].view(np.int8).astype(np.float32)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    nrm = (nrm / ln).astype(np.float32)
    uv = np.frombuffer(rec[:, 16:20].tobytes(), ">i2").reshape(nv, 2).astype(np.float32) / 4096.0
    weight = np.frombuffer(rec[:, 20:22].tobytes(), ">i2").astype(np.float32) / 4096.0
    bone_a = rec[:, 22].view(np.int8).astype(np.int32)
    bone_b = rec[:, 23].view(np.int8).astype(np.int32)
    col = rec[:, 24:28].astype(np.float32) / 255.0
    bones = np.zeros((0, 3), np.float32)
    if nbone and bone_off + nbone * 16 <= len(d):
        bones = np.frombuffer(d, ">f4", nbone * 4, bone_off).reshape(nbone, 4)[:, :3].copy()
    parts: list[Part] = []
    for i in range(nsub):
        o = sub_off + i * 80
        if o + 80 > len(d):
            break
        sname = _cstr(d, struct.unpack_from(">I", d, o + 48)[0])
        nmesh = struct.unpack_from(">H", d, o + 66)[0]
        moff = struct.unpack_from(">I", d, o + 68)[0]
        for j in range(nmesh):
            mo = moff + j * 16
            if mo + 16 > len(d):
                break
            mat_ptr, dl_off, packed, _nseg = struct.unpack_from(">4I", d, mo)
            size = (packed >> 16) * 16
            if dl_off + size > len(d) or size < 8:
                continue
            rows = _rows(d[dl_off : dl_off + size])
            if rows is None:
                continue
            prims, rows = rows
            cols = [(rows[:, 2 * k].astype(np.uint32) << 8) | rows[:, 2 * k + 1] for k in range(4)]
            pidx = cols[0]
            if pidx.max() >= nv:
                continue
            tri = _triangulate(prims, pidx)
            if len(tri) < 3:
                continue

            joints = np.zeros((nv, 4), np.uint16)
            weights = np.zeros((nv, 4), np.float32)
            if len(bones):
                a = np.clip(bone_a, 0, len(bones) - 1)
                b = np.clip(bone_b, 0, len(bones) - 1)
                w = np.clip(weight, 0.0, 1.0)
                joints[:, 0], joints[:, 1] = a, b
                weights[:, 0], weights[:, 1] = w, 1.0 - w
            parts.append(
                Part(
                    sname,
                    _cstr(d, mat_ptr),
                    pos,
                    tri,
                    _gather(nrm, cols[1], pidx, nv),
                    _gather(uv, cols[3], pidx, nv),
                    _gather(col, cols[2], pidx, nv),
                    joints if len(bones) else None,
                    weights if len(bones) else None,
                )
            )
    return Model(name, parts, bones)


def _rows(dl: bytes):
    prims = []
    p = 0
    while p + 3 <= len(dl):
        op = dl[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        cnt = (dl[p + 1] << 8) | dl[p + 2]
        if cnt == 0 or p + 3 + cnt * 8 > len(dl):
            break
        prims.append((op & 0xF8, cnt, p + 3))
        p += 3 + cnt * 8
    if not prims:
        return None
    rows = np.concatenate(
        [np.frombuffer(dl, np.uint8, c * 8, o).reshape(c, 8) for _, c, o in prims]
    )
    return prims, rows


def _gather(src: np.ndarray, col: np.ndarray, pidx: np.ndarray, nv: int) -> np.ndarray:
    """An attribute re-indexed per position (its own index column, falling back to the
    position index when out of range)."""
    idx = np.where(col < nv, col, pidx)
    out = np.zeros((nv, src.shape[1]), np.float32)
    out[pidx] = src[idx]
    return out


def gtx_decode(d: bytes) -> np.ndarray | None:
    """Krome ``.gtx`` GameCube texture -> (h, w, 4) u8.  Header ``u32 version | u32 width |
    u32 height | 8 zero bytes | u8 extra mip levels ...`` then the GX pixels at 0x20:
    version 2 is CMPR (mip chain follows the base level), version 0 is RGB5A3."""
    if len(d) < 0x20:
        return None
    ver, w, h = struct.unpack_from(">3I", d, 0)
    if not (0 < w <= 4096 and 0 < h <= 4096) or ver not in (0, 2):
        return None
    from gcrip.formats import gx_texture

    fmt = 14 if ver == 2 else 5
    need = gx_texture.encoded_size(fmt, w, h)
    if len(d) < 0x20 + need:
        return None
    return gx_texture.decode(fmt, w, h, d[0x20 : 0x20 + need])
