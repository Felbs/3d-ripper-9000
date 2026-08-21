"""DZB collision meshes (Wind Waker; rooms ship one as room.dzb).

Layout (big-endian; offsets verified against the disc, matching the game's cBgD
reader as documented by noclip.website):

  header 0x30: six (count:u32, offset:u32) pairs -
               vertices, triangles, blocks, tree nodes, groups, properties
  vertex 0x0C: x,y,z f32
  tri    0x0A: v0,v1,v2 u16, property index u16, group index u16
  group  0x34: name offset u32, scale 3f, rot 3*s16, trans 3f, parent/sibling/
               child s16, room s16, +0x2E tree s16, +0x30 attributes u32
  property 0x10: three u32 bit fields + pass flags u32 (cBgD_Ti_t mPolyInf0..3)

Group attribute bits: 0x100 water, 0x200 lava, 0x400 poison, 0x80000 light-shaft;
anything without those is regular solid ground/wall. Property pass flags: bit 0x04
means the player passes through the triangle (fences the camera or arrows care
about); such triangles are excluded from the player's solid mesh.

Property bit fields (masks/shifts are the ones dBgS::GetPolyId0/1/2 use, see
zeldaret/tww src/d/d_bg_s.cpp and the knowledge note dzb-polygon-attributes.md):

  inf0: cam_id 0xFF, sound 0x1F00>>8, exit 0x7E000>>13, poly_color 0x7F80000>>19,
        no_shadow bit 27
  inf1: link_no 0xFF, wall_code 0xF00>>8, special_code 0xF000>>12,
        attribute 0x1F0000>>16, ground_code 0x3E00000>>21
  inf2: cam_move_bg 0xFF, room_cam_id >>8, room_path_id >>16, room_path_point >>24
  inf3: pass flags 0x01 camera, 0x02 objects, 0x04 Link, 0x08 arrows/light (+no
        shadow draw), 0x10 hookshot sticks, 0x20 bombs, 0x40 boomerang, 0x80 hookshot

Wall codes the player reacts to (daPy_lk_c::setFrontWallType): 1 climbable (vines /
ivy - free 2D climbing), 2 no-grab wall (never hang / climb / catch), 3 push-pull
grab face, 4 ladder, 5 ladder top (descend onto the ladder from above). Any other
wall is plain and can be hung from when its top edge is 27-170 units above Link's
feet, so "hang" is a geometric tag here (vertical triangles that are not code 2).
Special code 1 is a slide slope, 3 refuses wall-hiding (sidle).

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
PASS_CAMERA = 0x01
PASS_OBJ = 0x02
PASS_LINK = 0x04
PASS_ARROW = 0x08
HOOKSHOT_STICK = 0x10
PASS_BOMB = 0x20
PASS_BOOMERANG = 0x40
PASS_HOOKSHOT = 0x80

WALL_PLAIN = 0
WALL_CLIMB = 1  # vines / ivy: procClimb*
WALL_NOHANG = 2  # setFrontWallType bails out: no catch, hang, climb or sidle
WALL_GRAB = 3  # push/pull block face (daPyRFlg0_UNK8 -> dActStts_GRAB)
WALL_LADDER = 4  # procLadder*
WALL_LADDER_TOP = 5  # upper rim: procLadderDownStart when grounded
WALL_CODE_NAMES = {
    WALL_PLAIN: "plain",
    WALL_CLIMB: "climb",
    WALL_NOHANG: "nohang",
    WALL_GRAB: "grab",
    WALL_LADDER: "ladder",
    WALL_LADDER_TOP: "ladder_top",
}
SPECIAL_SLIDE = 1  # getSlidePolygon: Link slides down it
SPECIAL_NO_WHIDE = 3  # getWHideModePolygon refuses it
GROUND_ABYSS = 4  # "Abyss ground code" (d_a_am2.cpp): fall-through void floor
GROUND_NO_SLIDE = 8  # m3580 == 8: slope handling disabled (stairs-like)

WALL_NORMAL_Y = 0.05  # |n.y| <= this counts as a wall for the player (setFrontWallType)
TAGS = ("ladder", "ladder_top", "climb", "nohang", "grab", "hang", "hookshot", "slide")


@dataclass(frozen=True)
class PolyProperty:
    """One 0x10 property record, decoded with the game's own masks."""

    cam_id: int
    sound_id: int
    exit_index: int
    poly_color: int
    no_shadow: bool
    link_no: int
    wall_code: int
    special_code: int
    attribute_code: int
    ground_code: int
    cam_move_bg: int
    room_cam_id: int
    room_path_id: int
    room_path_point: int
    pass_flags: int

    @classmethod
    def decode(cls, inf0: int, inf1: int, inf2: int, inf3: int) -> PolyProperty:
        return cls(
            cam_id=inf0 & 0xFF,
            sound_id=(inf0 >> 8) & 0x1F,
            exit_index=(inf0 >> 13) & 0x3F,
            poly_color=(inf0 >> 19) & 0xFF,
            no_shadow=bool((inf0 >> 27) & 1),
            link_no=inf1 & 0xFF,
            wall_code=(inf1 >> 8) & 0xF,
            special_code=(inf1 >> 12) & 0xF,
            attribute_code=(inf1 >> 16) & 0x1F,
            ground_code=(inf1 >> 21) & 0x1F,
            cam_move_bg=inf2 & 0xFF,
            room_cam_id=(inf2 >> 8) & 0xFF,
            room_path_id=(inf2 >> 16) & 0xFF,
            room_path_point=(inf2 >> 24) & 0xFF,
            pass_flags=inf3 & 0xFF,
        )

    @property
    def wall(self) -> str:
        return WALL_CODE_NAMES.get(self.wall_code, f"wall{self.wall_code}")

    @property
    def link_through(self) -> bool:
        return bool(self.pass_flags & PASS_LINK)

    @property
    def hookshot(self) -> bool:
        return bool(self.pass_flags & HOOKSHOT_STICK)


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
    tri_inf: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))  # property idx
    properties: list[PolyProperty] = field(default_factory=list)

    def _prop_array(self, name: str) -> np.ndarray:
        vals = np.array([getattr(p, name) for p in self.properties] or [0], dtype=np.int64)
        return vals[np.clip(self.tri_inf, 0, len(vals) - 1)]

    @property
    def tri_wall(self) -> np.ndarray:
        return self._prop_array("wall_code")

    @property
    def tri_special(self) -> np.ndarray:
        return self._prop_array("special_code")

    @property
    def tri_ground(self) -> np.ndarray:
        return self._prop_array("ground_code")

    @property
    def tri_attribute(self) -> np.ndarray:
        return self._prop_array("attribute_code")

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

    def world_corners(self) -> np.ndarray:
        """(T, 3, 3) float64 triangle corners with group transforms baked in."""
        worlds = self._world_matrices()
        grp = self.tri_group
        corners = self.vertices[self.triangles.reshape(-1)].astype(np.float64).reshape(-1, 3, 3)
        for gi in np.unique(grp):
            m = worlds[gi]
            if np.allclose(m, np.eye(4)):
                continue
            sel = grp == gi
            pts = corners[sel].reshape(-1, 3)
            corners[sel] = (pts @ m[:3, :3].T + m[:3, 3]).reshape(-1, 3, 3)
        return corners

    def tri_normals(self) -> np.ndarray:
        """(T, 3) unit normals in world space (degenerate triangles -> zero)."""
        c = self.world_corners()
        n = np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0])
        length = np.linalg.norm(n, axis=1, keepdims=True)
        return np.divide(n, length, out=np.zeros_like(n), where=length > 0)

    def is_wall(self) -> np.ndarray:
        """(T,) True where the player treats the triangle as a wall (|n.y| <= 0.05)."""
        if not len(self.triangles):
            return np.zeros(0, dtype=bool)
        return np.abs(self.tri_normals()[:, 1]) <= WALL_NORMAL_Y

    def surface_mask(self, surface: str) -> np.ndarray:
        want = np.array([g.surface == surface for g in self.groups], dtype=bool)
        return want[self.tri_group]

    def tag_mask(self, tag: str) -> np.ndarray:
        """(T,) mask of triangles carrying a gameplay tag (see TAGS).
        ladder/ladder_top/climb/nohang/grab come straight from the wall code;
        hookshot is pass bit 0x10; slide is special code 1; hang is derived:
        a vertical solid triangle Link can collide with whose wall code is not
        2 (no-hang) - the 27..170 unit ledge-height test happens at runtime."""
        wall = self.tri_wall
        if tag == "ladder":
            return wall == WALL_LADDER
        if tag == "ladder_top":
            return wall == WALL_LADDER_TOP
        if tag == "climb":
            return wall == WALL_CLIMB
        if tag == "nohang":
            return wall == WALL_NOHANG
        if tag == "grab":
            return wall == WALL_GRAB
        if tag == "hookshot":
            return (self.tri_pass & HOOKSHOT_STICK) != 0
        if tag == "slide":
            return self.tri_special == SPECIAL_SLIDE
        if tag == "hang":
            solid = self.surface_mask("solid") & ((self.tri_pass & PASS_LINK) == 0)
            return solid & self.is_wall() & (wall != WALL_NOHANG)
        raise ValueError(f"unknown tag {tag!r}; known: {TAGS}")

    def mesh_by(self, mask: np.ndarray):
        """Baked (vertices (N,3) float32, triangles (M,3) int) of the masked triangles,
        group transforms applied and identical corners welded."""
        mask = np.asarray(mask, dtype=bool)
        if not mask.any():
            return np.zeros((0, 3), "<f4"), np.zeros((0, 3), np.int64)
        corners = self.world_corners()[mask]
        flat = corners.reshape(-1, 3).astype("<f4")
        uniq, inverse = np.unique(flat, axis=0, return_inverse=True)
        return uniq, inverse.reshape(-1, 3)

    def mesh(self, surface: str, *, walkable_only: bool = True):
        """Baked (vertices (N,3) float32, triangles (M,3) int) of one surface class
        ('solid'/'water'/'lava'/'poison'), group transforms applied.
        walkable_only drops triangles flagged player-pass-through."""
        mask = self.surface_mask(surface)
        if walkable_only and surface == "solid":
            mask &= (self.tri_pass & PASS_LINK) == 0
        return self.mesh_by(mask)

    def tagged(self, tag: str):
        """mesh_by(tag_mask(tag)) - triangles for one gameplay tag (see TAGS)."""
        return self.mesh_by(self.tag_mask(tag))

    def tag_counts(self) -> dict[str, int]:
        return {t: int(self.tag_mask(t).sum()) for t in TAGS}


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

    properties = [
        PolyProperty.decode(*struct.unpack_from(">4I", data, o_inf + i * 0x10))
        for i in range(n_inf)
    ]
    pass_flags = np.array([p.pass_flags for p in properties] or [0], dtype=np.uint32)
    tri_inf = np.clip(tri_inf, 0, max(n_inf - 1, 0))
    tri_pass = pass_flags[tri_inf]

    return Dzb(
        vertices=vertices,
        triangles=triangles,
        tri_group=np.clip(tri_group, 0, max(n_grp - 1, 0)),
        tri_pass=tri_pass,
        groups=groups,
        tri_inf=tri_inf,
        properties=properties,
    )
