"""Terminal Reality ``CModel`` version 6 - RoadKill's ``.smf`` and ``.smb`` (the same class,
``CModel::loadHeader`` / ``loadData`` in the shipped ``Hunter.elf``).

The whole file is headers first, payloads after - which is why a scan for
``u32 2 | size | ... | vertices | triangles`` beside a vertex array found single-object files
and nothing of the 28-object cars.  Little-endian bookkeeping, big-endian GX payloads::

    u32 6, u32 objects, u32 collision meshes, u32 materials, u32 frames
    material x { u32 6; u8 record[228] - the .tif at +12 }
    collision x { char name[32]; u32 1, vertices, triangles; f32 xyz[vertices]; u16[3][triangles] }
    f32 min[3], max[3]
    object x { char name[32]; u16 material; u32 2; f32 min[3], max[3];
               u32 2, payload, kind, vertices, triangles, u32 }
    frames > 1: u16[objects + collision]; per frame per object f32 quat[4], f32 pos[3]
    object x payload:  the 32-byte SGCPacketHeader of gcrip.formats.tr_smf (its sizes left
                       0xCDCDCDCD, +4 = the index list offset, the fraction bits at +16),
                       13-byte vertices (s16 position, s8 normal, s16 uv, scaled by the
                       bits), then u16[3][triangles] big-endian at the offset

``CRenderPacket::loadData`` reads the payload raw and points the index list at
``payload + payload[4]``; ``setVertexFormat`` feeds the fraction bits to ``GXSetVtxAttrFmt``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import tr_smf

VERSION = 6
MATERIAL = 0xE4
MATERIAL_NAME = 12
NAME = 32
OBJECT_HEADER = NAME + 2 + 4 + 24 + 24
PACKET_HEADER = 24  # u32 2, payload, kind, vertices, triangles, u32
MAX_COUNT = 1 << 20
LAYOUT = tr_smf.LAYOUTS[6]  # 13-byte vertices


@dataclass
class Obj:
    name: str
    material: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


@dataclass
class Model:
    materials: list[str] = field(default_factory=list)
    objects: list[Obj] = field(default_factory=list)
    frames: int = 1
    warnings: list[str] = field(default_factory=list)


def is_cmodel(head: bytes, size: int) -> bool:
    if len(head) < 24 or size < 24:
        return False
    version, nobj, ncoll, nmat, frames = struct.unpack_from("<5I", head, 0)
    if version != VERSION or not 0 < nmat <= 4096 or nobj > MAX_COUNT or ncoll > MAX_COUNT:
        return False
    return 0 < frames <= MAX_COUNT and struct.unpack_from("<I", head, 20)[0] == VERSION


def parse(data: bytes) -> Model:
    out = Model()
    if not is_cmodel(data[:24], len(data)):
        raise ValueError("not a CModel version 6")
    _v, nobj, ncoll, nmat, frames = struct.unpack_from("<5I", data, 0)
    out.frames = frames
    p = 20
    for i in range(nmat):
        if p + 4 + MATERIAL > len(data):
            out.warnings.append(f"material {i} past the file")
            return out
        rec = data[p + 4 : p + 4 + MATERIAL]
        out.materials.append(rec[MATERIAL_NAME:].split(b"\0", 1)[0].decode("latin-1", "replace"))
        p += 4 + MATERIAL
    for i in range(ncoll):
        if p + NAME + 12 > len(data):
            out.warnings.append(f"collision mesh {i} past the file")
            return out
        _cv, nv, nt = struct.unpack_from("<3I", data, p + NAME)
        p += NAME + 12 + nv * 12 + nt * 6
    p += 24  # the model's bounding box
    heads = []
    for i in range(nobj):
        if p + OBJECT_HEADER > len(data):
            out.warnings.append(f"object {i} header past the file")
            return out
        name = data[p : p + NAME].split(b"\0", 1)[0].decode("latin-1", "replace")
        mat = struct.unpack_from("<H", data, p + NAME)[0]
        pv, payload, kind, nv, nt, _x = struct.unpack_from("<6I", data, p + NAME + 2 + 4 + 24)
        if pv != 2:
            out.warnings.append(f"object {i} ({name}): packet version {pv}")
            return out
        heads.append((name, mat, payload, kind, nv, nt))
        p += OBJECT_HEADER
    if frames > 1:
        p += 2 * (nobj + ncoll) + frames * (nobj + ncoll) * 28
    for name, mat, payload, kind, nv, nt in heads:
        if p + payload > len(data):
            out.warnings.append(f"{name}: payload past the file")
            break
        material = out.materials[mat] if mat < len(out.materials) else ""
        obj = _payload(data, p, payload, kind, nv, nt, name, material, out.warnings)
        if obj is not None:
            out.objects.append(obj)
        p += payload
    return out


def _payload(data, at, size, kind, nv, nt, name, material, warn) -> Obj | None:
    if kind != 1:
        warn.append(f"{name}: packet kind {kind} is not read")
        return None
    if size < tr_smf.PACKET_HEADER + 4 or not nv or not nt:
        warn.append(f"{name}: empty packet")
        return None
    index_at = struct.unpack_from(">I", data, at + 4)[0]
    fracs = struct.unpack_from(">3I", data, at + 16)
    if index_at + nt * 6 > size or index_at < tr_smf.PACKET_HEADER + nv * LAYOUT.stride:
        warn.append(f"{name}: index list at {index_at} does not fit {nv} vertices")
        return None
    packet = tr_smf.Packet(*fracs, kind)
    if max(fracs) > tr_smf.MAX_FRAC:
        warn.append(f"{name}: fraction bits {fracs}")
        return None
    pos, nrm, uv = tr_smf._vertices(data, at + tr_smf.PACKET_HEADER, nv, LAYOUT, packet)
    tris = np.frombuffer(data, ">u2", nt * 3, at + index_at).reshape(-1, 3).astype(np.uint32)
    if int(tris.max()) >= nv:
        warn.append(f"{name}: an index reaches past {nv} vertices")
        return None
    tris = tr_smf._orient(pos, nrm, tris)
    return Obj(name, material, pos, nrm, uv, tris.reshape(-1).astype(np.uint32))
