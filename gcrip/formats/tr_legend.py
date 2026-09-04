"""Crystal Dynamics DRM units - Tomb Raider: Legend's ``00 00 00 0e`` members inside
``bigfile.dat`` (the container is ``gcrip.formats.cd_bigfile``).

Every asset of the game - textures, animations, VO, models - travels in these units.
Big-endian throughout::

    +0   u32 version            14 (the DRM version Legend uses on every platform)
    +4   u32 count              number of section records **plus one**
    +8   u32 unit_header_size
    +12  u32 0
    +16  u32 0x800              map granularity; constant on every unit sampled
    +20  u32 0
    +24  record[count-1], 20 bytes each:
             u32 0xffffffff     pointer slot, patched at load
             u32 size           payload bytes
             u32 type<<24|sub   type: 0 data, 2 animation, 5 texture, 6 wave, 7 material
             u32 relocs<<8
             u32 id
         u32 0xffffffff         the phantom last "record": only its sentinel exists -
                                the unit's relocation pairs begin right after it
         pair[]                 {u32 value, u32 offset} - offsets ascend and stay below
                                unit_header_size, which is how the list's end is found
         unit header            unit_header_size bytes (LOD distances, object metadata)
    then per section, in record order:
         pair[relocs]           {u32 value, u32 offset} relocation pairs
         payload                size bytes

**The tiling is byte-exact**: header + records + sentinel + unit pairs + unit header +
per-section ``relocs*8 + size`` equals the member length on 16 of 16 sampled units, which
is the identity that proves the whole layout (every miscount overshoots or undershoots).

Relocations: ``value``'s high u16 is ``(target_section + 1) * 8``; its **low u16 is
uninitialised garbage** (fragments of a build-machine path - ``:\\``, ``re``, ``.d`` -
survive in it), and ``offset`` is the patch site inside this section.  The u32 stored at
the patch site is an offset within the target section.

Models: a type-0 section beginning ``04 c2 04 52`` is a model header.  Its relocated
pointers at +0x64/+0x68/+0x6c/+0x70 give position / normal / color / uv array offsets,
all inside one geometry section; +0x10 is an f32 scale vec3, +0x20 the vertex count.
The geometry section is GX-shaped: display-list packets from its start up to the first
array (op ``0x99`` strip / ``0x81`` quads / ``0x91`` triangles - VAT 1 - padded with
``0x00`` NOPs to 32-byte boundaries), each vertex 9 bytes::

    u8  matrix index (skinning; 0 on static models)
    u16 position index      -> s16 x,y,z  * scale
    u16 normal index        -> s8  x,y,z  / 127
    u16 color index         -> RGBA u8
    u16 uv index            -> u8 u,v     (quantisation unverified; /255 here)

Zero out-of-range indices across 43 models in 16 units, and the renders are unambiguous:
a perched bird, a spyglass, a leopard head with whiskers in the unit whose VO strings say
``VO\\Animals\\LEO_see_04``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

VERSION = 14
HEADER = 24
RECORD = 20
SENTINEL = 0xFFFFFFFF
MODEL_MAGIC = b"\x04\xc2\x04\x52"
MAX_SECTIONS = 4096
NORMAL_SCALE = 127.0
_DRAW_STRIP = 0x98
_DRAW_TRIS = 0x90
_DRAW_QUADS = 0x80
_DRAW_FAN = 0xA0
_DRAW_OPS = {_DRAW_QUADS, _DRAW_TRIS, _DRAW_STRIP, _DRAW_FAN}
DL_VERTEX = 9

# array-pointer slots in the model header, in (pos, nrm, col, uv) order
_PTRS = (0x64, 0x68, 0x6C, 0x70)


@dataclass
class Section:
    index: int
    type: int
    sub: int
    id: int
    offset: int  # payload offset in the member
    size: int
    relocs: list[tuple[int, int]] = field(default_factory=list)  # (target section, site)


def is_drm(head: bytes) -> bool:
    """Version 14, a sane count, and the first record's sentinel - all inside 64 bytes."""
    if len(head) < HEADER + 4:
        return False
    ver, count = struct.unpack_from(">2I", head, 0)
    if ver != VERSION or not 1 <= count - 1 <= MAX_SECTIONS:
        return False
    return struct.unpack_from(">I", head, HEADER)[0] == SENTINEL


def sections(data: bytes) -> list[Section] | None:
    """All section records with resolved payload offsets, or None unless the tiling
    lands byte-exact on the member's end."""
    if not is_drm(data[: HEADER + 4]):
        return None
    _, count, unit_size = struct.unpack_from(">3I", data, 0)
    nrec = count - 1
    pos = HEADER + nrec * RECORD
    if pos + 4 > len(data) or struct.unpack_from(">I", data, pos)[0] != SENTINEL:
        return None
    pos += 4
    # unit relocation pairs: ascending offsets below the unit header size
    prev = -1
    while pos + 8 <= len(data):
        _, off = struct.unpack_from(">2I", data, pos)
        if off <= prev or off >= unit_size:
            break
        prev = off
        pos += 8
    pos += unit_size
    out = []
    for i in range(nrec):
        sent, size, tf, fl, sid = struct.unpack_from(">5I", data, HEADER + i * RECORD)
        if sent != SENTINEL:
            return None
        relocs = []
        for _ in range(fl >> 8):
            if pos + 8 > len(data):
                return None
            val, off = struct.unpack_from(">2I", data, pos)
            relocs.append(((val >> 16) // 8 - 1, off))
            pos += 8
        if pos + size > len(data):
            return None
        out.append(Section(i, tf >> 24, tf & 0xFFFFFF, sid, pos, size, relocs))
        pos += size
    return out if pos == len(data) else None


@dataclass
class Model:
    section: int
    positions: np.ndarray  # (N,3) f32
    normals: np.ndarray | None
    colors: np.ndarray | None  # (N,4) f32
    uvs: np.ndarray | None  # (N,2) f32
    indices: np.ndarray  # (M,3) u32
    declared_vertices: int


def _packets(data: bytes, start: int, end: int):
    """(primitive, [9-byte vertices]) from a display-list region; NOPs skipped."""
    p = start
    while p < end:
        op = data[p]
        if op == 0:  # NOP padding to 32-byte boundaries
            p += 1
            continue
        prim = op & 0xF8
        if prim not in _DRAW_OPS or p + 3 > end:
            return
        n = struct.unpack_from(">H", data, p + 1)[0]
        if p + 3 + n * DL_VERTEX > end:
            return
        verts = [
            (data[q], *struct.unpack_from(">4H", data, q + 1))
            for q in range(p + 3, p + 3 + n * DL_VERTEX, DL_VERTEX)
        ]
        yield prim, verts
        p += 3 + n * DL_VERTEX


def _triangles(prim: int, n: int) -> list[tuple[int, int, int]]:
    """Corner index triples for one packet of n vertices."""
    if prim == _DRAW_STRIP:
        return [(i - 2, i, i - 1) if i % 2 else (i - 2, i - 1, i) for i in range(2, n)]
    if prim == _DRAW_TRIS:
        return [(i, i + 1, i + 2) for i in range(0, n - 2, 3)]
    if prim == _DRAW_QUADS:
        return [t for i in range(0, n - 3, 4) for t in ((i, i + 1, i + 2), (i, i + 2, i + 3))]
    return [(0, i - 1, i) for i in range(2, n)]  # fan


def models(data: bytes, secs: list[Section] | None = None) -> list[Model]:
    if secs is None:
        secs = sections(data)
    if not secs:
        return []
    out = []
    for s in secs:
        if s.type != 0 or s.size < 0x84 or data[s.offset : s.offset + 4] != MODEL_MAGIC:
            continue
        rel = dict((off, tgt) for tgt, off in s.relocs)
        if any(p not in rel for p in _PTRS):
            continue
        targets = {rel[p] for p in _PTRS}
        if len(targets) != 1:
            continue
        geo = secs[rel[_PTRS[0]]]
        ptr = [struct.unpack_from(">I", data, s.offset + p)[0] for p in _PTRS]
        if any(v > geo.size for v in ptr):
            continue
        scale = struct.unpack_from(">3f", data, s.offset + 0x10)
        nvert = struct.unpack_from(">I", data, s.offset + 0x20)[0]
        bounds = sorted(ptr) + [geo.size]
        span = [next(b for b in bounds if b > v) - v for v in ptr]
        npos, nnrm, ncol, nuv = span[0] // 6, span[1] // 3, span[2] // 4, span[3] // 2
        if npos < 3:
            continue
        base = geo.offset
        pos = np.frombuffer(data, ">i2", npos * 3, base + ptr[0]).reshape(-1, 3)
        pos = pos.astype(np.float32) * np.asarray(scale, np.float32)
        nrm = np.frombuffer(data, "b", nnrm * 3, base + ptr[1]).reshape(-1, 3)
        col = np.frombuffer(data, "B", ncol * 4, base + ptr[2]).reshape(-1, 4)
        uv = np.frombuffer(data, "B", nuv * 2, base + ptr[3]).reshape(-1, 2)

        vmap: dict[tuple[int, int, int, int], int] = {}
        vidx: list[tuple[int, int, int, int]] = []
        tris = []
        for prim, verts in _packets(data, base, base + min(ptr)):
            corner = []
            for _mtx, pi, ni, ci, ui in verts:
                if pi >= npos:
                    corner.append(None)
                    continue
                key = (pi, ni if ni < nnrm else 0, ci if ci < ncol else 0, ui if ui < nuv else 0)
                at = vmap.get(key)
                if at is None:
                    at = vmap[key] = len(vidx)
                    vidx.append(key)
                corner.append(at)
            for a, b, c in _triangles(prim, len(corner)):
                ta, tb, tc = corner[a], corner[b], corner[c]
                if None in (ta, tb, tc) or ta in (tb, tc) or tb == tc:
                    continue  # out of range, or strip-stitching degenerate
                tris.append((ta, tb, tc))
        if not tris:
            continue
        keys = np.array(vidx, np.int64)
        out.append(
            Model(
                section=s.index,
                positions=pos[keys[:, 0]],
                normals=(nrm[keys[:, 1]] / NORMAL_SCALE).astype(np.float32) if nnrm else None,
                colors=(col[keys[:, 2]] / 255.0).astype(np.float32) if ncol else None,
                uvs=(uv[keys[:, 3]] / 255.0).astype(np.float32) if nuv else None,
                indices=np.array(tris, np.uint32),
                declared_vertices=nvert,
            )
        )
    return out
