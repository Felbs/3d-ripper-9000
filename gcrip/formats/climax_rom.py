"""Climax ``.rom`` models (``ROM 1.26`` on ATV: Quad Power Racing 2 and The Italian Job,
``ROM 1.27`` on Hot Wheels World Race) - ``cModelFile::Init`` and ``cModelMeshFile::Init``
in the Hot Wheels ``main.dol`` (named by its ``HotwheelsFCDntsc.map``; ATV's DOL has the
same code with a 4-byte shorter mesh header).

The file is the runtime image: ``Init`` only sets pointers over it.  Big-endian::

    +0    char magic[12]      "ROM 1.26" / "ROM 1.27"
    +12   u32 materials       140-byte records at +0x48: char name[16] (the .bog's stem), ...
    +16   u32 B               124-byte records
    +20   u32 points          44-byte records: char name[32], f32 xyz  (attachment points)
    +24   u32 D               104-byte records
    +28   u32 E               32-byte records
    +32   u32 meshes
    +36   u32 min / max patch steps, f32
    +48   f32 min[3], max[3]
    +72   the tables in that order, then the meshes back to back

    mesh  u32 flags, u32 material, u32, u32, u32, u32 triangles, u32 patches, u32 C,
          u32 vertices, u32[3] (1.27 adds a u32) - header 0x30 / 0x34
          triangles x u32[3]; patches x 672 bytes; C x u32; vertices x 56 bytes:
          f32 position[3], normal[3], uv[2], uv2[2], u32[4]

A patch (``Bgc::cPatchMeshGC``) is a bicubic Bezier: 12 bytes, then f32 x[16], y[16], z[16]
control points (row-major 4x4), then six more 16-float arrays that are zero on every sample
and a tail the tool left uninitialised.  The game tessellates them between the model's min
and max patch steps; this reader uses a fixed 4x4 subdivision.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGICS = {b"ROM 1.26": 0x30, b"ROM 1.27": 0x34}
HEADER = 0x48
MATERIAL = 0x8C
MATERIAL_NAME = 16
RECORD_B = 0x7C
POINT = 0x2C
RECORD_D = 0x68
RECORD_E = 0x20
TRIANGLE = 12
PATCH = 0x2A0
VERTEX = 0x38
PATCH_STEPS = 4
MAX_COUNT = 1 << 20


@dataclass
class Mesh:
    material: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray
    patches: int = 0


@dataclass
class Model:
    version: bytes
    materials: list[str] = field(default_factory=list)
    points: list[tuple[str, tuple[float, float, float]]] = field(default_factory=list)
    meshes: list[Mesh] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_rom(head: bytes, size: int) -> bool:
    if len(head) < 36 or head[:8] not in MAGICS or size < HEADER:
        return False
    counts = struct.unpack_from(">6I", head, 12)
    return all(c <= MAX_COUNT for c in counts)


def _bezier(cp: np.ndarray, steps: int) -> np.ndarray:
    """Positions of a bicubic Bezier patch on a (steps+1)^2 grid; ``cp`` is (4, 4, 3)."""
    t = np.linspace(0.0, 1.0, steps + 1, dtype=np.float32)
    b = np.stack([(1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t**3], 1)  # (n,4)
    return np.einsum("ui,vj,ijk->uvk", b, b, cp)


def _grid_triangles(steps: int, base: int) -> np.ndarray:
    n = steps + 1
    out = []
    for i in range(steps):
        for j in range(steps):
            a = base + i * n + j
            out += [[a, a + 1, a + n], [a + 1, a + n + 1, a + n]]
    return np.array(out, np.uint32)


def _patch_mesh(data: bytes, at: int, count: int, material: int) -> Mesh:
    pos = []
    idx = []
    for k in range(count):
        p = at + k * PATCH + 12
        x = np.frombuffer(data, ">f4", 16, p)
        y = np.frombuffer(data, ">f4", 16, p + 64)
        z = np.frombuffer(data, ">f4", 16, p + 128)
        cp = np.stack([x, y, z], 1).reshape(4, 4, 3).astype(np.float32)
        grid = _bezier(cp, PATCH_STEPS)
        idx.append(_grid_triangles(PATCH_STEPS, sum(len(q) for q in pos)))
        pos.append(grid.reshape(-1, 3))
    positions = np.concatenate(pos).astype(np.float32)
    tris = np.concatenate(idx)
    n = PATCH_STEPS + 1
    uv = np.tile(
        np.stack(np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n), indexing="ij"), -1)
        .reshape(-1, 2)
        .astype(np.float32),
        (count, 1),
    )
    normals = _face_normals(positions, tris)
    return Mesh(material, positions, normals, uv, tris.reshape(-1), count)


def _face_normals(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    p = pos[tris]
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    out = np.zeros_like(pos)
    for k in range(3):
        np.add.at(out, tris[:, k], face)
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return (out / np.where(n > 0, n, 1)).astype(np.float32)


def parse(data: bytes) -> Model:
    if not is_rom(data[:64], len(data)):
        raise ValueError("not a Climax ROM")
    version = data[:8]
    mesh_header = MAGICS[version]
    nmat, nb, npts, nd, ne, nmesh = struct.unpack_from(">6I", data, 12)
    out = Model(version)
    p = HEADER
    for _ in range(nmat):
        if p + MATERIAL > len(data):
            break
        name = data[p : p + MATERIAL_NAME].split(b"\0", 1)[0].decode("latin-1", "replace")
        out.materials.append(name)
        p += MATERIAL
    p += nb * RECORD_B
    for _ in range(npts):
        if p + POINT > len(data):
            break
        name = data[p : p + 32].split(b"\0", 1)[0].decode("latin-1", "replace")
        out.points.append((name, struct.unpack_from(">3f", data, p + 32)))
        p += POINT
    p += nd * RECORD_D + ne * RECORD_E
    for i in range(nmesh):
        if p + mesh_header > len(data):
            out.warnings.append(f"mesh {i}: header past the file")
            break
        _flags, material = struct.unpack_from(">Ii", data, p)
        ntri, npatch, nc, nv = struct.unpack_from(">4I", data, p + 0x14)
        if max(ntri, npatch, nc, nv) > MAX_COUNT:
            out.warnings.append(f"mesh {i}: implausible counts")
            break
        tri_at = p + mesh_header
        patch_at = tri_at + ntri * TRIANGLE
        vert_at = patch_at + npatch * PATCH + nc * 4
        end = vert_at + nv * VERTEX
        if end > len(data):
            out.warnings.append(f"mesh {i}: {nv} vertices past the file")
            break
        if npatch:
            out.meshes.append(_patch_mesh(data, patch_at, npatch, material))
        if ntri and nv:
            tris = np.frombuffer(data, ">u4", ntri * 3, tri_at).astype(np.uint32)
            if int(tris.max()) < nv:
                v = np.frombuffer(data, ">f4", nv * 14, vert_at).reshape(nv, 14)
                out.meshes.append(
                    Mesh(
                        material,
                        np.ascontiguousarray(v[:, 0:3], np.float32),
                        np.ascontiguousarray(v[:, 3:6], np.float32),
                        np.ascontiguousarray(v[:, 6:8], np.float32),
                        tris,
                    )
                )
            else:
                out.warnings.append(f"mesh {i}: an index reaches past {nv} vertices")
        p = end
    return out
