"""Collision meshes: the floor a level actually stands on.

Scene command ``0x03`` points at a 0x2C-byte ``CollisionHeader``; the same struct, minus the
water boxes, appears inside object files for the things that move - doors, drawbridges,
platforms.  It needs no display-list interpretation, no textures and no segment table beyond
"which file am I in", so it is the cheapest complete 3D description of a level there is, and
for the 28 rooms whose look is a pre-rendered photograph it is the *only* one.

Every layout fact below was checked over all 101 scenes of Ocarina of Time - 63,262 vertices,
87,215 polygons, 2,046 surface types, 120 water boxes, zero parse failures - and the numbers
are in the tests.  The traps that bit earlier readers are recorded next to the code that
avoids them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

HEADER_SIZE = 0x2C
VERTEX_STRIDE = 6
POLY_STRIDE = 16
SURFACE_STRIDE = 8
CAM_STRIDE = 8
WATER_STRIDE = 16
#: a vertex index lives in the low 13 bits of its u16; the top bits of vA and vB are flags
INDEX_MASK = 0x1FFF


@dataclass
class WaterBox:
    x_min: int
    y_surface: int
    z_min: int
    x_length: int
    z_length: int
    #: bits 0-7 camData index, 8-12 light index (0x1F none), 13-18 room index (0x3F all)
    properties: int

    @property
    def room(self) -> int:
        return (self.properties >> 13) & 0x3F


@dataclass
class CamData:
    setting: int
    count: int
    #: the Vec3s block, as raw (n, 3) int16.  Its MEANING depends on the setting: for the 184
    #: entries with count 3 it reads as (position, rotation, parameters); for setting 0x1E -
    #: the only one that ever carries count 6 - it is a six-point polyline, and reading it as
    #: two cameras writes garbage.  So the block is carried raw and named by setting only.
    points: np.ndarray


@dataclass
class Collision:
    bounds_declared: tuple[tuple[int, int, int], tuple[int, int, int]]
    vertices: np.ndarray            # (N, 3) int16, world units
    polygons: np.ndarray            # (M, 3) uint16 vertex indices, flags stripped
    poly_types: np.ndarray          # (M,) uint16, index into surface_types
    poly_flags: np.ndarray          # (M, 3) the raw top bits of vA, vB, vC
    normals: np.ndarray             # (M, 3) float, the stored unit normal
    dist: np.ndarray                # (M,) int16 plane constant
    surface_types: list[tuple[int, int]]   # raw (data0, data1) words, named only where proven
    cam_data: list[CamData] = field(default_factory=list)
    water_boxes: list[WaterBox] = field(default_factory=list)
    offsets: dict[str, int] = field(default_factory=dict)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """The DECODED extent.  The header's declared box always contains it but equals it in
        only 32 of 101 scenes, so an exporter must never use the declared one."""
        return self.vertices.min(0), self.vertices.max(0)

    def bg_cam_index(self, surface_type: int) -> int:
        return self.surface_types[surface_type][0] & 0xFF

    def exit_index(self, surface_type: int) -> int:
        """1-based; 0 means none."""
        return (self.surface_types[surface_type][0] >> 8) & 0x1F


def _seg_off(word: int, segment: int, size: int) -> int | None:
    if word >> 24 != segment:
        return None
    off = word & 0x00FFFFFF
    return off if off < size else None


def parse(data: bytes, offset: int, segment: int = 2, *, strict: bool = True) -> Collision:
    """Read the ``CollisionHeader`` at *offset* in *data*, where the file is bound at *segment*.

    Scenes are segment 2; an object file's own header is segment 6 (or 4/5 for the keep banks).
    Raises ``ValueError`` on anything that is not a collision header.
    """
    if offset + HEADER_SIZE > len(data):
        raise ValueError("collision header runs past the file")
    (mnx, mny, mnz, mxx, mxy, mxz, n_vtx, pad0, vtx_p, n_poly, pad1, poly_p,
     surf_p, cam_p, n_water, pad2, water_p) = struct.unpack_from(">6hHHIHHIIIhHI", data, offset)
    if strict and (pad0 or pad1 or pad2):
        raise ValueError("collision header padding is not zero")
    if strict and not (mnx <= mxx and mny <= mxy and mnz <= mxz):
        raise ValueError("collision bounds are not ordered")
    vtx = _seg_off(vtx_p, segment, len(data))
    poly = _seg_off(poly_p, segment, len(data))
    surf = _seg_off(surf_p, segment, len(data))
    if vtx is None or poly is None or surf is None:
        raise ValueError("collision pointers do not resolve into this file")
    # waterBoxes is 0x00000000 in the 74 scenes with no water: an assert that all five
    # pointers are segmented fires on 73% of the game.  camDataList can be NULL in objects.
    cam = _seg_off(cam_p, segment, len(data)) if cam_p else None
    water = _seg_off(water_p, segment, len(data)) if water_p else None
    if strict and ((n_water == 0) != (water is None)):
        raise ValueError("water box count and pointer disagree")
    # The layout is strictly ordered and contiguous - camData < surfaceType < poly < vtx -
    # and the polygon list ends exactly where the vertex list starts.  That adjacency is what
    # DEFINES the surface-type count, which is stored nowhere: max(poly.type)+1 is only a
    # lower bound on it.
    if strict and poly + n_poly * POLY_STRIDE != vtx:
        raise ValueError("polygon list does not end at the vertex list")
    # the SPAN is a multiple of 8 in 101/101 scenes; the offset itself is only 4-aligned
    # (scene 1006 puts it at 0x314)
    if surf >= poly or (poly - surf) % SURFACE_STRIDE:
        raise ValueError("surface type list is misplaced")
    n_surf = (poly - surf) // SURFACE_STRIDE
    if vtx + n_vtx * VERTEX_STRIDE > len(data):
        raise ValueError("vertex list runs past the file")

    verts = np.frombuffer(data, dtype=">i2", count=n_vtx * 3, offset=vtx).reshape(-1, 3)
    verts = verts.astype(np.int16)
    raw = np.frombuffer(data, dtype=">u2", count=n_poly * 8, offset=poly).reshape(-1, 8)
    poly_types = raw[:, 0].astype(np.uint16)
    idx = (raw[:, 1:4] & INDEX_MASK).astype(np.uint16)
    flags = (raw[:, 1:4] >> 13).astype(np.uint8)
    normals = raw[:, 4:7].astype(np.int16).astype(np.float64) / 0x7FFF
    dist = raw[:, 7].astype(np.int16)
    if n_poly and int(idx.max()) >= n_vtx:
        raise ValueError("polygon names a vertex past the list")
    if n_surf and int(poly_types.max()) >= n_surf:
        raise ValueError("polygon names a surface type past the list")
    if strict and n_poly:
        mag = np.linalg.norm(normals * 0x7FFF, axis=1)
        if not np.all(np.abs(mag - 0x7FFF) <= 3):
            raise ValueError("a polygon normal is not unit length")

    surfaces = [struct.unpack_from(">II", data, surf + k * SURFACE_STRIDE) for k in range(n_surf)]

    cams: list[CamData] = []
    if cam is not None:
        for k in range((surf - cam) // CAM_STRIDE):
            setting, count, pos_p = struct.unpack_from(">HhI", data, cam + k * CAM_STRIDE)
            pts = np.zeros((0, 3), np.int16)
            if count and pos_p:
                po = _seg_off(pos_p, segment, len(data))
                if po is not None and po + count * 6 <= len(data):
                    pts = np.frombuffer(data, dtype=">i2", count=count * 3, offset=po)
                    pts = pts.reshape(-1, 3).astype(np.int16)
            cams.append(CamData(setting, count, pts))

    boxes: list[WaterBox] = []
    if water is not None:
        for k in range(n_water):
            xm, ys, zm, xl, zl, wpad, props = struct.unpack_from(
                ">5hHI", data, water + k * WATER_STRIDE)
            if strict and wpad:
                raise ValueError("water box padding is not zero")
            boxes.append(WaterBox(xm, ys, zm, xl, zl, props))

    return Collision(
        bounds_declared=((mnx, mny, mnz), (mxx, mxy, mxz)),
        vertices=verts, polygons=idx, poly_types=poly_types, poly_flags=flags,
        normals=normals, dist=dist, surface_types=surfaces, cam_data=cams,
        water_boxes=boxes,
        offsets={"header": offset, "vertices": vtx, "polygons": poly, "surface_types": surf,
                 "cam_data": cam if cam is not None else -1,
                 "water_boxes": water if water is not None else -1},
    )


def winding_agrees(c: Collision) -> int:
    """How many polygons' vertex order agrees with their stored normal.

    87,215 of 87,215 on Ocarina, so nothing needs flipping at export - but it is the check
    that says the index and normal fields were read from the right bytes.
    """
    v = c.vertices.astype(np.float64)
    a, b, cc = v[c.polygons[:, 0]], v[c.polygons[:, 1]], v[c.polygons[:, 2]]
    cross = np.cross(b - a, cc - a)
    return int(np.sum(np.einsum("ij,ij->i", cross, c.normals) > 0))


def plane_residual(c: Collision) -> float:
    """Largest |n . v + dist| over every polygon's first vertex; about 1.1 on Ocarina."""
    if not len(c.polygons):
        return 0.0
    v = c.vertices[c.polygons[:, 0]].astype(np.float64)
    return float(np.max(np.abs(np.einsum("ij,ij->i", v, c.normals) + c.dist)))


def find_headers(data: bytes, segment: int = 6) -> list[int]:
    """Every offset in *data* that parses as a full, self-consistent collision header.

    For object files - the dyna-poly meshes.  The filter is the strict parse plus the
    per-polygon validation, which is what separated 201 real headers from a file full of
    plausible-looking words.
    """
    out = []
    for off in range(0, len(data) - HEADER_SIZE + 1, 4):
        # cheap pre-checks before the full parse: three zero pads and segmented pointers
        if data[off + 0x0E:off + 0x10] != b"\0\0" or data[off + 0x16:off + 0x18] != b"\0\0":
            continue
        if data[off + 0x10] != segment or data[off + 0x18] != segment:
            continue
        try:
            c = parse(data, off, segment)
        except (ValueError, struct.error):
            continue
        if len(c.polygons) == 0 or len(c.vertices) == 0:
            continue
        if plane_residual(c) > 2.0:
            continue
        out.append(off)
    return out
