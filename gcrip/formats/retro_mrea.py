"""Retro MREA areas (Metroid Prime version 0xF, Echoes 0x19): the world geometry section
as a list of world models sharing one material set. Layout checked against the discs.

Header: u32 0xDEADBEEF, u32 version, f32[12] area transform, u32 world model count,
[Echoes: u32 script layer count], u32 section count, u32 geometry section index, u32
script layers index, [Echoes: u32 generated objects index], u32 collision, u32 unknown,
u32 lights, u32 VISI, u32 PATH, u32 area octree, [Echoes: u32 portal area, u32 static
geometry map, u32 compressed block count, u32[3] pad], u32[section count] sizes, pad to
32. Echoes then stores u32[4] per compressed block (buffer size, uncompressed size,
compressed size or 0 = raw, section count), pads to 32, and the blocks: raw ones are
`uncompressed size` bytes, compressed ones are segmented LZO padded at the front so the
block ends on a 32-byte boundary. Sections are 32-byte aligned within the joined data.

Geometry section: material set (CMDL format), then per world model: header section
(u32 visor flags, f32[12] transform, f32[6] AABB), positions, normals (s16), colors,
float UVs, short UVs, surface offsets, one section per surface (surface extra data =
0x18 bytes AABB), [Echoes: 2 more sections - surface group ids, group visibility].
Prime 1 world model normals are always shorts and the short UV array is always present.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import lzo
from gcrip.formats import retro_cmdl as cmdl

MAGIC = 0xDEADBEEF
VERSIONS = {0xF: 2, 0x19: 4}  # MREA version -> CMDL/material version


class MreaError(ValueError):
    pass


@dataclass
class WorldModel:
    visor_flags: int
    transform: np.ndarray  # (3,4)
    aabb: tuple[float, ...]
    model: cmdl.Model


@dataclass
class Area:
    version: int
    transform: np.ndarray  # (3,4)
    models: list[WorldModel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_mrea(head: bytes) -> bool:
    if len(head) < 8:
        return False
    magic, version = struct.unpack_from(">II", head, 0)
    return magic == MAGIC and version in VERSIONS


def _sections(data: bytes, version: int) -> tuple[list[bytes], int, int, int]:
    """(sections, world model count, geometry section index, geometry end index)"""
    if version == 0xF:
        n_models, n_sec, geom, script = struct.unpack_from(">IIII", data, 0x38)
        sizes = list(struct.unpack_from(f">{n_sec}I", data, 0x60))
        start = (0x60 + 4 * n_sec + 31) & ~31
        body = data[start:]
        geom_end = script
    else:
        n_models, _n_layers, n_sec, geom, script = struct.unpack_from(">IIIII", data, 0x38)
        (n_blocks,) = struct.unpack_from(">I", data, 0x70)
        sizes = list(struct.unpack_from(f">{n_sec}I", data, 0x80))
        pos = (0x80 + 4 * n_sec + 31) & ~31
        blocks = [struct.unpack_from(">4I", data, pos + 16 * i) for i in range(n_blocks)]
        pos = (pos + 16 * n_blocks + 31) & ~31
        out = bytearray()
        for _buf, usize, csize, _cnt in blocks:
            if csize == 0:
                out += data[pos : pos + usize]
                pos += usize
            else:
                pos += (32 - csize % 32) % 32
                out += lzo.decompress_segmented(data[pos : pos + csize], usize)
                pos += csize
        body = bytes(out)
        geom_end = script
    secs = []
    off = 0
    for s in sizes:
        secs.append(body[off : off + s])
        off += s
    return secs, n_models, geom, geom_end


def parse(data: bytes) -> Area:
    magic, version = struct.unpack_from(">II", data, 0)
    if magic != MAGIC:
        raise MreaError("bad magic")
    if version not in VERSIONS:
        raise MreaError(f"unsupported MREA version {version:#x}")
    xf = np.array(struct.unpack_from(">12f", data, 8), np.float32).reshape(3, 4)
    area = Area(version, xf)
    secs, n_models, geom, geom_end = _sections(data, version)
    mat_version = VERSIONS[version]
    mset = cmdl.parse_material_set(secs[geom], mat_version)
    flags = cmdl.FLAG_SHORT_NORMALS | cmdl.FLAG_SHORT_UVS
    i = geom + 1
    for mi in range(n_models):
        if i + 7 > len(secs) or i >= geom_end:
            area.warnings.append(f"world model {mi}: sections missing")
            break
        hdr = secs[i]
        (visor,) = struct.unpack_from(">I", hdr, 0)
        mxf = np.array(struct.unpack_from(">12f", hdr, 4), np.float32).reshape(3, 4)
        aabb = struct.unpack_from(">6f", hdr, 0x34)
        (n_surf,) = struct.unpack_from(">I", secs[i + 6], 0)
        n_used = 7 + n_surf + (2 if version >= 0x19 else 0)
        warnings: list[str] = []
        try:
            _sets, arrays, surfaces = cmdl.parse_geometry(
                secs[i + 1 : i + 7 + n_surf], flags, mat_version, 0, warnings
            )
        except (cmdl.CmdlError, struct.error, ValueError) as e:
            area.warnings.append(f"world model {mi}: {e}")
            i += n_used
            continue
        model = cmdl.Model(
            mat_version,
            flags,
            aabb,
            [mset],
            arrays["positions"],
            arrays["normals"],
            arrays["colors"],
            arrays["uvs"],
            arrays["short_uvs"],
            surfaces,
            warnings,
        )
        area.models.append(WorldModel(visor, mxf, aabb, model))
        i += n_used
    return area
