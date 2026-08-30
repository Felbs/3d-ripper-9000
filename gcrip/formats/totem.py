"""Kalisto Entertainment TotemTech ``.dgc`` data files (Jimmy Neutron: Boy Genius, Spirits &
Spells, SpongeBob SquarePants: Revenge of the Flying Dutchman).

The files open with a plain-text banner (``TotemTech Data v1.75 (c) 1999-2002 Kalisto
Entertainment - All right reserved``), zero padding, and then an uncompressed payload
(entropy ~5) that mixes binary blocks with text property dumps (``= 0 \\r\\n\\tGeomDesc = ""``).

Geometry is stored plainly rather than behind a table: a big-endian ``f32 xyz`` vertex array
followed by face records of ``u32 3 | u16 a | u16 b | u16 c`` and a short, variable trailer
(the next record is found by scanning for the ``3`` count word).  There is no global mesh
directory, so meshes are recovered by locating the vertex runs and reading the faces that
follow them - the same approach the GX structure scanner takes for display lists.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

BANNER = b"TotemTech Data"
COUNT3 = b"\x00\x00\x00\x03"
MIN_VERTS = 24
MIN_FACES = 8


@dataclass
class Mesh:
    positions: np.ndarray
    indices: np.ndarray
    offset: int


def is_dgc(head: bytes) -> bool:
    return BANNER in head[:0x60]


def _vertex_runs(data: bytes, limit: float = 1e4) -> list[tuple[int, int]]:
    """(offset, vertex count) of big-endian f32 xyz runs, longest first."""
    out: list[tuple[int, int]] = []
    for phase in range(3):
        off = phase * 4
        n = (len(data) - off) // 12
        if n < MIN_VERTS:
            continue
        v = np.frombuffer(data[off : off + n * 12], ">f4").reshape(n, 3)
        good = (
            np.isfinite(v).all(axis=1)
            & (np.abs(v) < limit).all(axis=1)
            & (np.abs(v) > 1e-5).any(axis=1)
        )
        start = None
        for i, g in enumerate(good):
            if g and start is None:
                start = i
            elif not g and start is not None:
                if i - start >= MIN_VERTS:
                    out.append((off + start * 12, i - start))
                start = None
        if start is not None and n - start >= MIN_VERTS:
            out.append((off + start * 12, n - start))
    out.sort(key=lambda t: -t[1])
    return out


SEARCH = 1 << 16


def _faces(data: bytes, start: int, nverts: int, budget: int = 200000) -> tuple[np.ndarray, int]:
    """Face records following a vertex run.  A mesh may keep normals and uvs between the
    positions and the faces, so the first record is searched for in a window rather than
    expected immediately; returns (triangles, end offset)."""
    tris: list[tuple[int, int, int]] = []
    first = data.find(COUNT3, start, start + SEARCH)
    if first < 0:
        return np.zeros((0, 3), np.uint32), start
    p = first
    while p + 10 <= len(data) and len(tris) < budget:
        if data[p : p + 4] != COUNT3:
            nxt = data.find(COUNT3, p, p + 32)
            if nxt < 0:
                break
            p = nxt
            continue
        a, b, c = struct.unpack_from(">3H", data, p + 4)
        if max(a, b, c) >= nverts:
            break
        tris.append((a, b, c))
        p += 10
        nxt = data.find(COUNT3, p, p + 32)
        if nxt < 0:
            break
        p = nxt
    return np.array(tris, np.uint32).reshape(-1, 3), p


def meshes(data: bytes, max_meshes: int = 256) -> list[Mesh]:
    out: list[Mesh] = []
    used: list[tuple[int, int]] = []
    for off, count in _vertex_runs(data):
        if len(out) >= max_meshes:
            break
        end = off + count * 12
        if any(off < u_end and u_off < end for u_off, u_end in used):
            continue
        tris, _stop = _faces(data, end, count)
        if len(tris) < MIN_FACES:
            continue
        seen = np.unique(tris)
        pos = np.frombuffer(data, ">f4", count * 3, off).reshape(count, 3).astype(np.float32)
        span = float(np.abs(pos[seen]).max()) if len(seen) else 0.0
        if span == 0.0 or span > 1e4:
            continue
        out.append(Mesh(pos, tris.reshape(-1), off))
        used.append((off, end))
    return out
