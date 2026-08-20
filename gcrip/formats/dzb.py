"""DZB collision meshes (Wind Waker; rooms ship one as room.dzb).

Layout (big-endian; offsets verified against the disc, matching the game's cBgD
reader as documented by noclip.website):

  header 0x30: six (count:u32, offset:u32) pairs -
               vertices, triangles, blocks, tree nodes, groups, properties
  vertex 0x0C: x,y,z f32
  tri    0x0A: v0,v1,v2 u16, property index u16, group index u16
  group  0x34: name offset u32, scale 3f, rot 3*s16, trans 3f, parent/sibling/
               child s16, room s16, +0x2E tree s16, +0x30 attributes u32
  property 0x10: three u32 bit fields + pass flags u32

Group attribute bits: 0x100 water, 0x200 lava, 0x400 poison, 0x80000 light-shaft;
anything without those is regular solid ground/wall. Property pass flags: bit 0x04
means the player passes through the triangle (fences the camera or arrows care
about); such triangles are excluded from the player's solid mesh.

Groups form a scene tree with their own SRT (rotations in s16 angle units, ZXY
order like the game's mDoMtx helpers); most are identity, but movable set pieces
(Outset's windmill, platforms) place their collision through the group transform,
so world matrices are computed through the parent chain and baked into `mesh()`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

ATTR_WATER = 0x100
ATTR_LAVA = 0x200
ATTR_POISON = 0x400
PASS_LINK = 0x04


@dataclass
class Group:
    name: str
    attr: int
    room: int
    parent: int
    scale: tuple[float, float, float]
    rot: tuple[int, int, int]  # s16 angle units
    trans: tuple[float, float, float]

    @property
    def surface(self) -> str:
        if self.attr & ATTR_WATER:
            return "water"
        if self.attr & ATTR_LAVA:
            return "lava"
        if self.attr & ATTR_POISON:
            return "poison"
        return "solid"

    def local_matrix(self) -> np.ndarray:
        rx, ry, rz = (v * np.pi / 0x8000 for v in self.rot)
        cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)  # noqa: E501
        mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        m = np.eye(4)
        m[:3, :3] = (mz @ mx @ my) @ np.diag(self.scale)  # ZXY, like mDoMtx_ZXYrotM
        m[:3, 3] = self.trans
        return m


@dataclass
class Dzb:
    vertices: np.ndarray  # (N, 3) float32, group-local
    triangles: np.ndarray  # (T, 3) vertex indices
    tri_group: np.ndarray  # (T,) group index per triangle
    tri_pass: np.ndarray  # (T,) property pass flags per triangle
    groups: list[Group] = field(default_factory=list)

    def _world_matrices(self) -> list[np.ndarray]:
        worlds: list[np.ndarray | None] = [None] * len(self.groups)

        def world(i: int) -> np.ndarray:
            if worlds[i] is None:
                m = self.groups[i].local_matrix()
                p = self.groups[i].parent
                worlds[i] = (world(p) @ m) if 0 <= p < len(self.groups) and p != i else m
            return worlds[i]

        for i in range(len(self.groups)):
            world(i)
        return worlds  # type: ignore[return-value]

    def mesh(self, surface: str, *, walkable_only: bool = True):
        """Baked (vertices (N,3) float32, triangles (M,3) int) of one surface class
        ('solid'/'water'/'lava'/'poison'), group transforms applied.
        walkable_only drops triangles flagged player-pass-through."""
        want = np.array([g.surface == surface for g in self.groups], dtype=bool)
        mask = want[self.tri_group]
        if walkable_only and surface == "solid":
            mask &= (self.tri_pass & PASS_LINK) == 0
        tris = self.triangles[mask]
        grp = self.tri_group[mask]
        if not len(tris):
            return np.zeros((0, 3), "<f4"), np.zeros((0, 3), np.int64)
        worlds = self._world_matrices()
        # bake per-group transforms: emit each triangle's corners, transformed
        corners = self.vertices[tris.reshape(-1)].astype(np.float64).reshape(-1, 3, 3)
        for gi in np.unique(grp):
            m = worlds[gi]
            if np.allclose(m, np.eye(4)):
                continue
            sel = grp == gi
            pts = corners[sel].reshape(-1, 3)
            corners[sel] = (pts @ m[:3, :3].T + m[:3, 3]).reshape(-1, 3, 3)
        flat = corners.reshape(-1, 3).astype("<f4")
        uniq, inverse = np.unique(flat, axis=0, return_inverse=True)
        return uniq, inverse.reshape(-1, 3)


def _cstr(data: bytes, off: int) -> str:
    end = data.find(b"\0", off)
    return data[off : end if end >= 0 else len(data)].decode("latin-1", "replace")


def parse(data: bytes) -> Dzb:
    (
        n_vtx, o_vtx, n_tri, o_tri, _n_blk, _o_blk,
        _n_tre, _o_tre, n_grp, o_grp, n_inf, o_inf,
    ) = struct.unpack_from(">12I", data, 0)  # fmt: skip

    vertices = np.frombuffer(data, ">f4", n_vtx * 3, o_vtx).reshape(n_vtx, 3).astype("<f4")

    raw = np.frombuffer(data, ">u2", n_tri * 5, o_tri).reshape(n_tri, 5)
    triangles = raw[:, :3].astype(np.uint32)
    tri_inf = raw[:, 3].astype(np.int64)
    tri_group = raw[:, 4].astype(np.int64)

    groups = []
    for i in range(n_grp):
        base = o_grp + i * 0x34
        (name_off,) = struct.unpack_from(">I", data, base)
        scale = struct.unpack_from(">3f", data, base + 0x04)
        rot = struct.unpack_from(">3h", data, base + 0x10)
        trans = struct.unpack_from(">3f", data, base + 0x18)
        (parent,) = struct.unpack_from(">h", data, base + 0x24)
        (room,) = struct.unpack_from(">h", data, base + 0x2A)
        (attr,) = struct.unpack_from(">I", data, base + 0x30)
        groups.append(
            Group(
                name=_cstr(data, name_off),
                attr=attr,
                room=room,
                parent=parent,
                scale=scale,
                rot=rot,
                trans=trans,
            )
        )

    pass_flags = np.zeros(max(n_inf, 1), dtype=np.uint32)
    for i in range(n_inf):
        (pass_flags[i],) = struct.unpack_from(">I", data, o_inf + i * 0x10 + 0x0C)
    tri_pass = pass_flags[np.clip(tri_inf, 0, max(n_inf - 1, 0))]

    return Dzb(
        vertices=vertices,
        triangles=triangles,
        tri_group=np.clip(tri_group, 0, max(n_grp - 1, 0)),
        tri_pass=tri_pass,
        groups=groups,
    )
