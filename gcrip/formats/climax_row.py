"""Climax ``.row`` worlds - the tracks of Hot Wheels World Race (``ROW 2.26``), ATV: Quad
Power Racing 2 and The Italian Job (``ROW 2.25``): ``cWorld::Load``, ``cWorld::LoadNode``,
``cWorldMesh::Load`` and ``Bgc::cMeshGC::SetVertices(cWorldVertexFile*)`` in the Hot Wheels
``main.dol``, named by its ``.map``.

Big-endian.  Header counts from +12; the tables follow from +0x38 in this order with these
file strides (the runtime copies them into objects of other sizes)::

    +0x10  textures     0x8c   char name[16] - the .bog's stem - and material settings
    +0x14  mirrors      0x44
    +0x18  markers      0xbc   "start0" ...
    +0x1c               0x2c
    +0x20               0x4c
    +0x24               0x80
    +0x28               0x68
    +0x2c  projections  0x60
    +0x30  texture anims 0x20  names
    +0x34  nodes               the count the tree below must reach

Then the node tree, depth first (``cWorld::LoadNode``): a 48-byte node - ``u32 meshes,
f32, f32 centre[3], f32 min[3], max[3], u8 has_child[2], u16`` - is a leaf when it has
meshes and a branch otherwise, its flagged children following in order.  A leaf's meshes
(``cWorldMeshHeaderFile``, 48 bytes)::

    u32 flags, i32 texture[3], u32 triangles, u32 vertices, u32 patches, u32 patches2,
    i32 texture anim[3], i32 anim
    triangles x u32[3]; vertices x 52 bytes (f32 position[3], normal[3], uv[3][2], u8
    rgba[4]); (patches + patches2) x 604 bytes

A world patch (``cWorldPatchFile``, ``Bgc::cPatchMeshGC::Init``) is a bicubic Bezier: 12
bytes, f32 x[16], y[16], z[16] control points, f32 uv[4][2] at its corners, zeros.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import climax_rom

MAGICS = (b"ROW 2.25", b"ROW 2.26")
HEADER = 0x38
TEXTURE = 0x8C
TEXTURE_NAME = 16
STRIDES = (0x44, 0xBC, 0x2C, 0x4C, 0x80, 0x68, 0x60, 0x20)  # tables +0x14 .. +0x30
NODE = 0x30
MESH_HEADER = 0x30
TRIANGLE = 12
VERTEX = 0x34
PATCH = 0x25C
MAX_COUNT = 1 << 20
MAX_NODES = 1 << 16


@dataclass
class Mesh:
    texture: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    colors: np.ndarray | None
    indices: np.ndarray
    patches: int = 0


@dataclass
class World:
    version: bytes
    textures: list[str] = field(default_factory=list)
    meshes: list[Mesh] = field(default_factory=list)
    nodes: int = 0
    warnings: list[str] = field(default_factory=list)


def is_row(head: bytes, size: int) -> bool:
    if len(head) < HEADER or head[:8] not in MAGICS or size < HEADER:
        return False
    counts = struct.unpack_from(">10I", head, 0x10)
    return all(c <= MAX_COUNT for c in counts) and 0 < counts[9] <= MAX_NODES


def _patch_mesh(data: bytes, at: int, count: int, texture: int) -> Mesh:
    pos, idx, uvs = [], [], []
    steps = climax_rom.PATCH_STEPS
    n = steps + 1
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    for k in range(count):
        p = at + k * PATCH + 12
        x = np.frombuffer(data, ">f4", 16, p)
        y = np.frombuffer(data, ">f4", 16, p + 64)
        z = np.frombuffer(data, ">f4", 16, p + 128)
        cp = np.stack([x, y, z], 1).reshape(4, 4, 3).astype(np.float32)
        corners = np.frombuffer(data, ">f4", 8, p + 192).reshape(4, 2)
        idx.append(climax_rom._grid_triangles(steps, sum(len(q) for q in pos)))
        pos.append(climax_rom._bezier(cp, steps).reshape(-1, 3))
        # corner uvs bilinear over the grid: corners run 0, 1, 2, 3 around the patch
        u = t[:, None, None]
        v = t[None, :, None]
        c0, c1, c2, c3 = corners
        uv = (1 - u) * (1 - v) * c0 + u * (1 - v) * c1 + u * v * c2 + (1 - u) * v * c3
        uvs.append(uv.reshape(-1, 2).astype(np.float32))
    positions = np.concatenate(pos).astype(np.float32)
    tris = np.concatenate(idx)
    normals = climax_rom._face_normals(positions, tris)
    return Mesh(texture, positions, normals, np.concatenate(uvs), None, tris.reshape(-1), count)


def parse(data: bytes) -> World:
    if not is_row(data[:HEADER], len(data)):
        raise ValueError("not a Climax ROW")
    out = World(data[:8])
    counts = struct.unpack_from(">10I", data, 0x10)
    p = HEADER
    for _ in range(counts[0]):
        if p + TEXTURE > len(data):
            out.warnings.append("texture table past the file")
            return out
        out.textures.append(
            data[p : p + TEXTURE_NAME].split(b"\0", 1)[0].decode("latin-1", "replace")
        )
        p += TEXTURE
    for count, stride in zip(counts[1:9], STRIDES, strict=True):
        p += count * stride
    nodes = counts[9]

    def node(p: int) -> int:
        if p + NODE > len(data):
            raise ValueError("node past the file")
        out.nodes += 1
        if out.nodes > nodes:
            raise ValueError("more nodes than the header counts")
        nmesh = struct.unpack_from(">I", data, p)[0]
        has_child = data[p + 0x2C : p + 0x2E]
        p += NODE
        if nmesh:
            for _ in range(min(nmesh, MAX_COUNT)):
                if p + MESH_HEADER > len(data):
                    raise ValueError("mesh header past the file")
                _flags, t0, _t1, _t2, ntri, nv, np1, np2 = struct.unpack_from(">IiiiIIII", data, p)
                tri_at = p + MESH_HEADER
                vert_at = tri_at + ntri * TRIANGLE
                patch_at = vert_at + nv * VERTEX
                end = patch_at + (np1 + np2) * PATCH
                if end > len(data) or max(ntri, nv, np1, np2) > MAX_COUNT:
                    raise ValueError("mesh data past the file")
                if ntri and nv:
                    tris = np.frombuffer(data, ">u4", ntri * 3, tri_at).astype(np.uint32)
                    if int(tris.max()) < nv:
                        raw = np.frombuffer(data, np.uint8, nv * VERTEX, vert_at).reshape(
                            nv, VERTEX
                        )
                        f = raw[:, :0x30].copy().view(">f4").reshape(nv, 12)
                        out.meshes.append(
                            Mesh(
                                t0,
                                np.ascontiguousarray(f[:, 0:3], np.float32),
                                np.ascontiguousarray(f[:, 3:6], np.float32),
                                np.ascontiguousarray(f[:, 6:8], np.float32),
                                np.ascontiguousarray(raw[:, 0x30:0x34]),
                                tris,
                            )
                        )
                    else:
                        out.warnings.append("a mesh indexes past its vertices")
                if np1 + np2:
                    out.meshes.append(_patch_mesh(data, patch_at, np1 + np2, t0))
                p = end
            return p
        for k in range(2):
            if has_child[k]:
                p = node(p)
        return p

    try:
        end = node(p)
    except ValueError as e:
        out.warnings.append(str(e))
        return out
    if end != len(data):
        out.warnings.append(f"the tree ends at {end} of {len(data)} bytes")
    if out.nodes != nodes:
        out.warnings.append(f"{out.nodes} nodes walked, {nodes} declared")
    return out
