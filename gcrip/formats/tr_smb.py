"""Terminal Reality ``.SMB`` binary models - 4x4 Evo 2 (``GCMODEL.POD/MODELS/*.SMB``, 1,113
of them), the ``C3DModel::loadBinary`` of the shipped ``4x4.elf``.

Little-endian bookkeeping around big-endian GX packets::

    u32 version          1
    u32 parts
    u32, f32             a flag and 50.0 (auto-detail distance)
    part x {
        char name[32]    "OPAQUE", "opaque" - padded with 0xCD
        u32 flag
        u32 vertices, u32 frames, u32 triangles
        u8  material[172]  seven words, then the texture name at +32 ("GSTATUE.TIF", "MC2CK3.RAW")
        frames == 1: a CRenderPacket - u32 2, payload, kind, vertices, triangles, u32, u32,
                     then the payload (kind 1: the 32-byte SGCPacketHeader whose last two
                     words are the "00000008 00000001 preamble" of gcrip.formats.tr_smf,
                     then the GX list of 16-byte s16 vertices scaled by the header's
                     fraction bits; kind 4: 32-byte SVertex records), then f32 min[3], max[3]
        frames  > 1: frames x vertices x SVertex (f32 x y z, nx ny nz, u v), then
                     triangles x 3 u16 - a keyframe-animated mesh, frame 0 is the rest
    }

``CSimpleModel::loadBinary`` reads exactly this: counts at +0 / +8 / +0x10, 0xac bytes of
material at +0x24, and either ``CRenderPacket::load`` or the raw arrays.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import tr_smf

VERSION = 1
PART_NAME = 32
MATERIAL = 0xAC
MATERIAL_NAME = 32
PACKET_HEADER = 28
SVERTEX = 32
MAX_PARTS = 1 << 12
MAX_COUNT = 1 << 20
KIND_PACKET = 1
KIND_SVERTEX = 4
LAYOUT = tr_smf.LAYOUTS[4]  # 16-byte big-endian vertices: s16 pos, s16 normal, s16 uv


@dataclass
class Part:
    name: str
    material: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray
    frames: int = 1


@dataclass
class Model:
    parts: list[Part] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_smb(head: bytes, size: int) -> bool:
    if len(head) < 52 or size < 52 + 12 + MATERIAL:
        return False
    version, parts, flag = struct.unpack_from("<3I", head, 0)
    if version != VERSION or not 0 < parts <= MAX_PARTS or flag > 1:
        return False
    name = head[16:48].split(b"\0", 1)[0]
    return bool(name) and all(32 <= c < 127 for c in name)


def _svertex(data: bytes, at: int, count: int):
    v = np.frombuffer(data, "<f4", count * 8, at).reshape(count, 8)
    return (
        np.ascontiguousarray(v[:, 0:3], np.float32),
        np.ascontiguousarray(v[:, 3:6], np.float32),
        np.ascontiguousarray(v[:, 6:8], np.float32),
    )


def _packet(data: bytes, at: int, count: int, kind: int, name: str, material: str, warn):
    """One CRenderPacket payload at ``at``: the GX list (kind 1) or SVertex arrays (kind 4)."""
    if kind == KIND_PACKET:
        q = data.find(tr_smf.SIGNATURE, at, at + tr_smf.PACKET_HEADER)
        if q < 0:
            warn.append(f"{name}: no GX packet preamble")
            return None
        found = tr_smf._list_at(data, q + len(tr_smf.SIGNATURE), LAYOUT)
        if found is None:
            warn.append(f"{name}: GX list does not walk")
            return None
        prim, n, body, _end = found
        tris = tr_smf._triangles(prim, n)
        pos, nrm, uv = tr_smf._vertices(data, body, n, LAYOUT, tr_smf.packet_header(data, q))
        tris = tr_smf._orient(pos, nrm, tris)
        return Part(name, material, pos, nrm, uv, tris.reshape(-1).astype(np.uint32))
    warn.append(f"{name}: packet kind {kind} is not read")  # SVertex packets: none seen yet
    return None


def parse(data: bytes) -> Model:
    out = Model()
    if not is_smb(data[:64], len(data)):
        raise ValueError("not a 4x4 Evo 2 SMB")
    nparts = struct.unpack_from("<I", data, 4)[0]
    p = 16
    for i in range(nparts):
        if p + PART_NAME + 4 + 12 + MATERIAL > len(data):
            out.warnings.append(f"part {i}: header past the file")
            break
        name = data[p : p + PART_NAME].split(b"\0", 1)[0].decode("latin-1", "replace")
        p += PART_NAME + 4
        nv, nf, nt = struct.unpack_from("<3I", data, p)
        p += 12
        material = (
            data[p + MATERIAL_NAME : p + MATERIAL].split(b"\0", 1)[0].decode("latin-1", "replace")
        )
        p += MATERIAL
        if nv > MAX_COUNT or nt > MAX_COUNT or nf > MAX_COUNT:
            out.warnings.append(f"part {i}: implausible counts {nv} / {nf} / {nt}")
            break
        if nf == 1 and nv and nt:
            if p + PACKET_HEADER > len(data):
                out.warnings.append(f"part {i}: packet header past the file")
                break
            ver, payload, kind, pverts, ptris = struct.unpack_from("<5I", data, p)
            if ver != 2 or p + PACKET_HEADER + payload + 24 > len(data):
                out.warnings.append(f"part {i}: packet version {ver} / {payload} bytes")
                break
            part = _packet(data, p + PACKET_HEADER, pverts, kind, name, material, out.warnings)
            if part is not None:
                out.parts.append(part)
            p += PACKET_HEADER + payload + 24  # the bounding box follows the payload
            continue
        need = nv * nf * SVERTEX + nt * 6
        if p + need > len(data):
            out.warnings.append(f"part {i}: {nf} frames of {nv} vertices past the file")
            break
        if nv and nt:
            pos, nrm, uv = _svertex(data, p, nv)
            idx = np.frombuffer(data, "<u2", nt * 3, p + nv * nf * SVERTEX)
            if int(idx.max()) < nv:
                out.parts.append(Part(name, material, pos, nrm, uv, idx.astype(np.uint32), nf))
            else:
                out.warnings.append(f"part {i}: an index reaches past {nv} vertices")
        p += need
    return out
