"""Kalisto Entertainment TotemTech ``.dgc`` data files (Jimmy Neutron: Boy Genius, Spirits &
Spells, SpongeBob SquarePants: Revenge of the Flying Dutchman).

The files open with a plain-text banner (``TotemTech Data v1.75 (c) 1999-2002 Kalisto
Entertainment - All right reserved``), zero padding, and then an UNCOMPRESSED payload
(entropy ~5) that mixes binary blocks with text property dumps (``= 0 \\r\\n\\tGeomDesc = ""``).

Geometry lies in the open, without a directory:

* faces are records of ``u32 3 | u16 a | u16 b | u16 c`` plus a short, variable trailer, so a
  mesh shows up as a dense run of ``3`` count words - that run is the reliable anchor;
* the vertices are a big-endian ``f32 xyz`` array before the faces, with the mesh's normals and
  uvs (also float arrays) in between, so the nearest preceding run that is long enough for the
  largest index is the position array;
* several face runs may share one vertex array (one mesh split per material), and those are
  merged.

Everything is therefore found by scanning; there is no header that names a mesh.  Materials
and textures are not linked yet.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

BANNER = b"TotemTech Data"
COUNT3 = b"\x00\x00\x00\x03"
MIN_RECORDS = 8  # face records before a run counts as a mesh
RECORD_GAP = 24  # bytes between consecutive face records
WINDOW = 1 << 20  # how far back the vertex array may sit
MIN_VERTS = 8


@dataclass
class Mesh:
    positions: np.ndarray
    indices: np.ndarray
    offset: int  # of the vertex array


def is_dgc(head: bytes) -> bool:
    return BANNER in head[:0x60]


def _face_runs(data: bytes) -> list[tuple[int, int]]:
    """(start, end) of dense runs of face-count words."""
    marks: list[int] = []
    p = 0
    while True:
        q = data.find(COUNT3, p)
        if q < 0:
            break
        marks.append(q)
        p = q + 4
    if not marks:
        return []
    runs: list[tuple[int, int]] = []
    start = last = marks[0]
    n = 1
    for m in marks[1:]:
        if m - last <= RECORD_GAP:
            n += 1
        else:
            if n >= MIN_RECORDS:
                runs.append((start, last + 10))
            start = m
            n = 1
        last = m
    if n >= MIN_RECORDS:
        runs.append((start, last + 10))
    return runs


def _faces(data: bytes, start: int, end: int) -> np.ndarray:
    tris: list[tuple[int, int, int]] = []
    p = start
    while p < end:
        if data[p : p + 4] != COUNT3:
            q = data.find(COUNT3, p, min(p + RECORD_GAP + 8, end))
            if q < 0:
                break
            p = q
            continue
        a, b, c = struct.unpack_from(">3H", data, p + 4)
        tris.append((a, b, c))
        p += 10
    return np.array(tris, np.uint32).reshape(-1, 3)


def _float_runs(data: bytes, lo: int, hi: int, need: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for phase in range(3):
        off = lo + phase * 4
        n = (hi - off) // 12
        if n < need:
            continue
        v = np.frombuffer(data[off : off + n * 12], ">f4").reshape(n, 3)
        good = np.isfinite(v).all(axis=1) & (np.abs(v) < 1e4).all(axis=1)
        start = None
        for i, g in enumerate(good):
            if g and start is None:
                start = i
            elif not g and start is not None:
                if i - start >= need:
                    out.append((off + start * 12, i - start))
                start = None
        if start is not None and n - start >= need:
            out.append((off + start * 12, n - start))
    return out


def _score(data: bytes, off: int, count: int, tris: np.ndarray) -> float:
    """Spread of the referenced vertices over their median edge length; lower is better."""
    if off + count * 12 > len(data):
        return float("inf")
    pos = np.frombuffer(data, ">f4", count * 3, off).reshape(count, 3).astype(np.float64)
    keep = tris[(tris < count).all(axis=1)]
    if len(keep) < 4 or not np.isfinite(pos).all():
        return float("inf")
    used = np.unique(keep)
    span = float(np.linalg.norm(pos[used].max(axis=0) - pos[used].min(axis=0)))
    edge = float(np.median(np.linalg.norm(pos[keep[:, 1]] - pos[keep[:, 0]], axis=1)))
    if span <= 0 or edge <= 0:
        return float("inf")
    return span / edge


def meshes(data: bytes, max_meshes: int = 512, max_ratio: float = 60.0) -> list[Mesh]:
    """Meshes recovered from the payload, one per vertex array.  Each face run is paired with
    the candidate array whose referenced vertices hang together best, and a run whose best
    candidate is still incoherent is dropped rather than guessed at."""
    by_array: dict[int, tuple[int, list[np.ndarray]]] = {}
    for start, end in _face_runs(data):
        tris = _faces(data, start, end)
        if len(tris) < 4:
            continue
        need = max(int(tris.max()) + 1, MIN_VERTS)
        cands = _float_runs(data, max(0, start - WINDOW), start, need)
        if not cands:
            continue
        cands.sort(key=lambda t: -t[0])
        best = None
        for off, count in cands[:6]:
            r = _score(data, off, count, tris)
            if best is None or r < best[0]:
                best = (r, off, count)
        if best is None or best[0] > max_ratio:
            continue
        _r, off, count = best
        slot = by_array.setdefault(off, (count, []))
        slot[1].append(tris)
        if len(by_array) >= max_meshes:
            break
    out: list[Mesh] = []
    for off, (count, groups) in sorted(by_array.items()):
        tris = np.concatenate(groups)
        pos = np.frombuffer(data, ">f4", count * 3, off).reshape(count, 3).astype(np.float32)
        keep = tris[(tris < count).all(axis=1)]
        if len(keep) < 4 or _score(data, off, count, keep) > max_ratio:
            continue
        out.append(Mesh(pos, keep.reshape(-1), off))
    return out
