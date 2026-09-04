"""Kashmir ``.dat`` scenes - the engine behind City Racer, Taxi 3 and Speed Challenge:
Jacques Villeneuve's Racing Vision (every file says ``Created/Modified using Kashmir``).
A PC-born format: **little-endian** throughout, with the textures alone converted for the
GameCube.

The file is a header then a flat **chunk stream** - ``u32 kind, u32 x, u32 length,
payload`` - ended by a kind-102 trailer.  The header is ``a4 0d 6d 71, u32 2, u32 0, u32
1000, u32 0, u32 n, u32, u32, author\\0, "Created/Modified using Kashmir"\\0, zeros`` and the
stream starts at ``36 + n`` (46, 47, 49 across the three games).  Every object carries an
**8-byte id** as the first thing in its payload and a kind-8 chunk (``id, name\\0``) names it.

Kinds that matter::

    1  mesh      x = 101   id, u8 flags, u32 vertices, f32 xyz[vertices], u32 triangles,
                           triangles x (u16 v0 v1 v2, u16 uv0 uv1 uv2, u8 material),
                           u32 uvs, f32 uv[uvs]  [, "TMAP" u8 u8, u16[3 x triangles]]
    2  material x = 0     id, u8[28] colours and flags, texture name\\0 (absent when 28 long)
    3  texture  x = 0     the image file: a GameCube one (``\\0RPMOC3S\\0`` then big-endian
                           width, height, bytes, GX format, 0, 0, 5, 1, 0, u16 7, u16 0 at
                           +8, the tiled data with mips at +48 - the same as the discs'
                           standalone ``.tga``) or a real TGA
    4  node     x = 100   id, parent id, mesh id, u8 u8, f32 xyz position, f32 xyz rotation
                           (radians), u32 materials, id[materials], u32 colours, argb[colours]
    8  name               id, name\\0

A texture chunk follows the material chunk that samples it, and a material's ``texture
name`` is the key other materials share it by.  A triangle's material byte indexes the
node's material list (the Audi's body: fond, negru crom, far spate, far fata).  Meshes are
referenced by exactly one node; nodes chain through their parents and place the pieces of a
track (Pub16 at (111.06, 0.30, 23.84), yaw 1.335).  The rotation composes as
``Rz(-z) Ry(-y) Rx(-x)`` - chosen because it is the reading under which the 255 rotated
pieces of London 1 sit against their neighbours (66 % within 0.5 units, 48 % under the
un-negated readings); the three angles are seldom all set, so the order is the weakest
part of this reader.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture, tga

MAGIC = b"\xa4\x0d\x6d\x71"
HEADER_BASE = 36
TRIANGLE = 13
MAX_CHUNK_KIND = 64
MAX_COUNT = 1 << 20
MATERIAL_NAME_AT = 36
NODE_FIXED = 54
GC_TAG = b"RPMOC3S"
GC_HEADER = 48

KIND_MESH = 1
KIND_MATERIAL = 2
KIND_TEXTURE = 3
KIND_NODE = 4
KIND_NAME = 8


@dataclass
class Mesh:
    ident: bytes
    positions: np.ndarray
    uvs: np.ndarray
    triangles: np.ndarray  # (n, 3) vertex indices
    uv_indices: np.ndarray  # (n, 3) into uvs
    materials: np.ndarray  # (n,) material slot a triangle


@dataclass
class Node:
    ident: bytes
    parent: bytes
    mesh: bytes
    position: np.ndarray
    rotation: np.ndarray
    materials: list[bytes]


@dataclass
class Scene:
    author: str = ""
    meshes: dict[bytes, Mesh] = field(default_factory=dict)
    materials: dict[bytes, str | None] = field(default_factory=dict)  # id -> texture name
    textures: dict[str, np.ndarray] = field(default_factory=dict)  # texture name -> RGBA
    nodes: dict[bytes, Node] = field(default_factory=dict)
    names: dict[bytes, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def is_kashmir(head: bytes, size: int = 0) -> bool:
    return head[:4] == MAGIC and len(head) >= 24 and struct.unpack_from("<I", head, 4)[0] == 2


def chunks(data: bytes):
    """``(kind, x, payload)`` in file order."""
    if len(data) < 0x18:
        return
    o = HEADER_BASE + struct.unpack_from("<I", data, 0x14)[0]
    while o + 12 <= len(data):
        kind, x, length = struct.unpack_from("<3I", data, o)
        if kind > MAX_CHUNK_KIND or o + 12 + length > len(data):
            return
        yield kind, x, data[o + 12 : o + 12 + length]
        o += 12 + length


def mesh(p: bytes) -> Mesh | None:
    if len(p) < 13:
        return None
    vertices = struct.unpack_from("<I", p, 9)[0]
    o = 13 + 12 * vertices
    if vertices > MAX_COUNT or o + 4 > len(p):
        return None
    triangles = struct.unpack_from("<I", p, o)[0]
    t_at = o + 4
    o = t_at + TRIANGLE * triangles
    if triangles > MAX_COUNT or o + 4 > len(p):
        return None
    uvs = struct.unpack_from("<I", p, o)[0]
    uv_at = o + 4
    if uvs > MAX_COUNT or uv_at + 8 * uvs > len(p):
        return None
    positions = np.frombuffer(p, "<f4", 3 * vertices, 13).reshape(vertices, 3)
    rec = np.frombuffer(p, np.uint8, TRIANGLE * triangles, t_at).reshape(triangles, TRIANGLE)
    corners = np.ascontiguousarray(rec[:, :6]).view("<u2").astype(np.int64)
    uv_idx = np.ascontiguousarray(rec[:, 6:12]).view("<u2").astype(np.int64)
    uv = np.frombuffer(p, "<f4", 2 * uvs, uv_at).reshape(uvs, 2) if uvs else np.zeros((0, 2), "<f4")
    if triangles and (int(corners.max()) >= vertices or (uvs and int(uv_idx.max()) >= uvs)):
        return None
    if not uvs:
        uv_idx = np.zeros_like(corners)
        uv = np.zeros((1, 2), "<f4")
    return Mesh(
        bytes(p[:8]),
        positions.astype(np.float32),
        uv.astype(np.float32),
        corners,
        uv_idx,
        rec[:, 12].astype(np.int64),
    )


def gc_texture(p: bytes) -> np.ndarray | None:
    """The GameCube image the toolchain writes in place of a TGA."""
    if len(p) < GC_HEADER or p[1:8] != GC_TAG:
        return None
    width, height, size, fmt = struct.unpack_from(">4I", p, 8)
    if fmt not in gx_texture.TILE_DIMS or not (0 < width <= 2048 and 0 < height <= 2048):
        return None
    need = gx_texture.encoded_size(fmt, width, height)
    if GC_HEADER + need > len(p):
        return None
    try:
        return gx_texture.decode(fmt, width, height, p[GC_HEADER : GC_HEADER + need])
    except ValueError:
        return None


def texture(p: bytes) -> np.ndarray | None:
    rgba = gc_texture(p)
    if rgba is None and tga.is_tga(p):
        try:
            rgba = tga.decode(p)
        except Exception:  # noqa: BLE001 - a broken picture is not worth the mesh
            rgba = None
    return rgba


def node(p: bytes) -> Node | None:
    if len(p) < NODE_FIXED:
        return None
    materials = struct.unpack_from("<I", p, 50)[0]
    if NODE_FIXED + 8 * materials > len(p):
        return None
    ids = [bytes(p[NODE_FIXED + 8 * k : NODE_FIXED + 8 * k + 8]) for k in range(materials)]
    return Node(
        bytes(p[:8]),
        bytes(p[8:16]),
        bytes(p[16:24]),
        np.frombuffer(p, "<f4", 3, 26).astype(np.float64),
        np.frombuffer(p, "<f4", 3, 38).astype(np.float64),
        ids,
    )


def parse(data: bytes) -> Scene | None:
    if not is_kashmir(data[:24]):
        return None
    out = Scene()
    end = data.find(b"\0", 0x20)
    if 0 < end < 0x60:
        out.author = data[0x20:end].decode("latin-1", "replace")
    last_material: bytes | None = None
    for kind, _x, p in chunks(data):
        if kind == KIND_MESH:
            m = mesh(p)
            if m is None:
                out.warnings.append("a mesh chunk did not read")
            else:
                out.meshes[m.ident] = m
        elif kind == KIND_MATERIAL and len(p) >= 8:
            name = None
            if len(p) > MATERIAL_NAME_AT:
                end = p.find(b"\0", MATERIAL_NAME_AT)
                name = p[MATERIAL_NAME_AT : end if end > 0 else len(p)].decode("latin-1", "replace")
            out.materials[bytes(p[:8])] = name or None
            last_material = bytes(p[:8])
        elif kind == KIND_TEXTURE:
            name = out.materials.get(last_material) if last_material else None
            if name and name not in out.textures:
                rgba = texture(p)
                if rgba is not None:
                    out.textures[name] = rgba
        elif kind == KIND_NODE:
            n = node(p)
            if n is not None:
                out.nodes[n.ident] = n
        elif kind == KIND_NAME and len(p) > 8:
            out.names[bytes(p[:8])] = p[8:].split(b"\0")[0].decode("latin-1", "replace")
    return out


def _rotation(r: np.ndarray) -> np.ndarray:
    def about(axis: int, a: float) -> np.ndarray:
        c, s = np.cos(a), np.sin(a)
        m = np.eye(3)
        i, j = [(1, 2), (0, 2), (0, 1)][axis]
        m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
        if axis == 1:
            m[i, j], m[j, i] = s, -s
        return m

    return about(2, -r[2]) @ about(1, -r[1]) @ about(0, -r[0])


def world(scene: Scene, ident: bytes, memo: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """A node's world rotation and translation through its parents."""
    memo = {} if memo is None else memo
    if ident in memo:
        return memo[ident]
    n = scene.nodes.get(ident)
    if n is None:
        memo[ident] = (np.eye(3), np.zeros(3))
        return memo[ident]
    memo[ident] = (np.eye(3), np.zeros(3))  # a cycle stops here
    r = _rotation(n.rotation)
    if n.parent != ident and n.parent in scene.nodes:
        pr, pt = world(scene, n.parent, memo)
        memo[ident] = (pr @ r, pr @ n.position + pt)
    else:
        memo[ident] = (r, n.position.copy())
    return memo[ident]
