"""Neko Entertainment (NGDK 1.5) level worlds - the ``MWLD`` chunk of the Cocoto and
Charlie's Angels ``.GCN`` files once :mod:`gcrip.formats.neko_lz` has unpacked them.

The unpacked file is ``u32 3, u32 4, u32 file bytes`` then big-endian chunks ``tag, u32
size, payload`` (4-aligned): ``MWLD`` the static world, ``STAO`` static objects, ``DYNO``
dynamic objects (a serialised tree with ``0xcccccccc`` tool fill, unread), ``VOX1``,
``LIGT``, ``ENGD``.  ``MWLD``::

    u32 faces, u32 vertices, u32 normals, u32, u32
    faces    x 20: u16 flags, u16 normal, 3 x (u16 vertex, u8 0xff, u8 0), u16 material, u16
    vertices x 16: s16 x y z, u8 u8, s16 u, s16 v (/4096), u8 r g b a
    normals  x 8:  s16 x y z (/4096), u16
    objects  x 0x94: char[16] name, 3 x s32 position (16.16), ..., +0x24 u32 vertex base,
                     +0x28 u32 face base, ...   ("01", "02", "Bateau01" ...)
    then LDWM blocks - GX triangle strips (0x98) of 6-byte corners, three identical u16
    indices - the render lists the faces duplicate

The face list's vertex indices are **relative to their object's vertex base**: Charlie's
Angels level 1 has 65,853 vertices across 15 objects but no index above 10,092, and adding
each object's base (from the object table, faces sliced by face base) turns the tangle into
a city block with boats.  Cocoto Kart Racer's arena (one object, 2,511 faces) reads either
way.  Vertex coordinates are world space; the object positions are not applied.

Not read: the material -> texture table (``GFX.PC`` is headerless pixel data and no
dimension table has been found in the ``.GCN`` or ``TIN.PC``), so the world comes out with a
primitive a material id and no pictures; and ``DYNO``, which holds the props.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

HEADER = 0x0C
FACE = 20
VERTEX = 16
NORMAL = 8
OBJECT = 0x94
OBJECT_NAME = 16
OBJECT_VERTEX_BASE = 0x24
OBJECT_FACE_BASE = 0x28
UV_SCALE = 1.0 / 4096.0
POSITION_SCALE = 1.0 / 256.0
MAX_COUNT = 1 << 22


@dataclass
class World:
    positions: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray
    triangles: np.ndarray  # (n, 3) absolute vertex indices
    materials: np.ndarray  # (n,) material id a face
    objects: list[tuple[str, int, int]] = field(
        default_factory=list
    )  # name, vertex base, face base
    warnings: list[str] = field(default_factory=list)


def is_level(head: bytes, size: int = 0) -> bool:
    return (
        len(head) >= 16
        and head[:8] == b"\0\0\0\x03\0\0\0\x04"
        and head[12:16] == b"MWLD"
        and (size == 0 or struct.unpack_from(">I", head, 8)[0] <= size)
    )


def chunks(data: bytes):
    o = HEADER
    while o + 8 <= len(data):
        tag = data[o : o + 4]
        size = struct.unpack_from(">I", data, o + 4)[0]
        if not tag.isalnum() or o + 8 + size > len(data):
            return
        yield tag.decode("ascii"), data[o + 8 : o + 8 + size]
        o = (o + 8 + size + 3) & ~3


def _objects(p: bytes, at: int, faces: int, vertices: int) -> list[tuple[str, int, int]]:
    out = []
    while at + OBJECT <= len(p):
        raw = p[at : at + OBJECT_NAME].split(b"\0")[0]
        if not raw or not all(32 <= c < 127 for c in raw):
            break
        vbase, fbase = struct.unpack_from(">2I", p, at + OBJECT_VERTEX_BASE)
        if vbase > vertices or fbase > faces:
            break
        out.append((raw.decode("ascii"), vbase, fbase))
        at += OBJECT
    return out


def world(payload: bytes) -> World | None:
    if len(payload) < 20:
        return None
    faces, vertices, normals = struct.unpack_from(">3I", payload, 0)
    if not (0 < faces <= MAX_COUNT and 0 < vertices <= MAX_COUNT and normals <= MAX_COUNT):
        return None
    f_at = 20
    v_at = f_at + FACE * faces
    n_at = v_at + VERTEX * vertices
    o_at = n_at + NORMAL * normals
    if o_at > len(payload):
        return None
    rec = np.frombuffer(payload, np.uint8, FACE * faces, f_at).reshape(faces, FACE)
    corners = np.stack(
        [np.ascontiguousarray(rec[:, k : k + 2]).view(">u2").ravel() for k in (4, 8, 12)], 1
    ).astype(np.int64)
    materials = np.ascontiguousarray(rec[:, 16:18]).view(">u2").ravel().astype(np.int64)
    v = np.frombuffer(payload, ">i2", vertices * 8, v_at).reshape(vertices, 8)
    positions = (v[:, :3].astype(np.float32) * POSITION_SCALE).astype(np.float32)
    uvs = (v[:, 4:6].astype(np.float32) * UV_SCALE).astype(np.float32)
    colors = np.frombuffer(payload, np.uint8, vertices * 16, v_at).reshape(vertices, 16)[:, 12:16]
    objects = _objects(payload, o_at, faces, vertices)
    out = World(positions, uvs, np.ascontiguousarray(colors), corners, materials, objects)
    if objects:
        # faces index vertices relative to their object; slice by face base, add vertex base
        bases = sorted(objects, key=lambda x: x[2])
        tri = corners.copy()
        for k, (_name, vbase, fbase) in enumerate(bases):
            end = bases[k + 1][2] if k + 1 < len(bases) else faces
            tri[fbase:end] += vbase
        out.triangles = tri
    if int(out.triangles.max()) >= vertices:
        out.warnings.append("faces index past the vertices")
        keep = (out.triangles < vertices).all(1)
        out.triangles = out.triangles[keep]
        out.materials = out.materials[keep]
    return out


def parse(data: bytes) -> World | None:
    if not is_level(data[:16], len(data)):
        return None
    for tag, payload in chunks(data):
        if tag == "MWLD":
            return world(payload)
    return None
