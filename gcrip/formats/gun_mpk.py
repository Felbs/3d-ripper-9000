"""Neversoft Gun (GameCube, GUME52) ``.mpk.ngc`` map packs - level geometry.

The 315 map packs (only levels have one; the other 918 ``.mpk.ngc`` are 32-byte
``AB``-fill placeholders) open with the disc-wide ``04 20 00 00`` asset header
(big-endian: log2 dims at +10/+11, GX format at +13, payload bytes at +16,
header size 32 at +20, next-image offset at +24) and hold, in one member:
embedded CMPR textures, per-object prop blocks with inline vertex data, four
global vertex attribute arrays, and the level's mesh display lists.

What this reader extracts - the display-list meshes over the global arrays,
proven on z_steamboat2 (every kept mesh's vertices land inside the bounding
sphere its own header stores):

* scene header: the 44 bytes before the file's LAST ``aa ff ee ff`` marker
  carry ``u32 position count, u32 normal count, u16 colour count, u16 uv
  count`` (z_steamboat2: 32725 / 43481 / 5505 / 22130).
* global arrays, back to back with small zero padding, located from the
  normal array - the file's longest run of unit-length big-endian s16 triples
  (scale 1/16384).  UVs (s16 pairs, 1/1024) end 2 bytes before it, colours
  (RGBA8) before those, positions (f32 xyz) before the colours; the exact
  position base is settled by a bounding-sphere vote over the first meshes.
* meshes: scanned by signature - ``00 15 00 04`` with the display-list size
  repeated at -36 and +12.  Layout around the signature at ``s``::

      s-36  u32  display list size          s+4   u16  vertex (corner) count
      s-32  u32  material checksum          s+6   u16  0x0200
      s-28  u32  flags                      s+12  u32  display list size again
      s-24  u32  mesh checksum              s+28  display list
      s-20  f32[4] bounding sphere x y z r

  The display list is CP VCD_LO/VCD_HI loads (``08 50`` / ``08 60``), XF
  loads, then GX draws (VAT 7) whose vertices are index16 tuples - on the
  level meshes ``(pos, nrm, col0, tex0)`` - into the global arrays.  Indices
  are absolute: the per-attribute maxima equal the header counts minus one.
* prop objects at the front of the file use per-object INLINE arrays with the
  same mesh record shape; their indices do not fit the global arrays, so the
  sphere test rejects them (z_steamboat2: 103 of 796) - not yet extracted.

y is up; a level spans tens of thousands of units.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MARKER = b"\xaa\xff\xee\xff"
MESH_SIG = b"\x00\x15\x00\x04"
NRM_SCALE = 1.0 / 16384.0
UV_SCALE = 1.0 / 1024.0
_DRAW_OPS = (0x80, 0x90, 0x98, 0xA0)


class GunMpkError(ValueError):
    pass


def is_mpk(head: bytes) -> bool:
    """The shared asset header: only the extension separates a map pack from an
    ``.img.ngc``, so the plugin also checks the path."""
    return len(head) >= 32 and head[:4] == b"\x04\x20\x00\x00"


@dataclass
class Mesh:
    material: int  # checksum
    checksum: int
    flags: int
    sphere: tuple[float, float, float, float]
    corners: dict[str, np.ndarray]  # attr -> (N,) index per corner
    triangles: np.ndarray  # (T,3) into the corners


@dataclass
class Level:
    positions: np.ndarray  # (P,3) f32
    normals: np.ndarray  # (N,3) f32
    colors: np.ndarray  # (C,4) u8
    uvs: np.ndarray  # (U,2) f32
    meshes: list[Mesh]
    rejected: int = 0  # meshes whose indices are not into the global arrays
    warnings: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(len(m.triangles) for m in self.meshes)


# ---------------------------------------------------------------------------
# locating the global arrays
# ---------------------------------------------------------------------------


def scene_counts(data: bytes) -> tuple[int, int, int, int] | None:
    """(npos, nnrm, ncol, nuv) from the 44 bytes before the last aa ff ee ff."""
    at = data.rfind(MARKER)
    while at > 44:
        npos, nnrm = np.frombuffer(data[at - 44 : at - 36], ">u4")
        ncol, nuv = np.frombuffer(data[at - 36 : at - 32], ">u2")
        if 0 < npos < 0x200000 and 0 < nnrm < 0x200000 and ncol and nuv:
            return int(npos), int(nnrm), int(ncol), int(nuv)
        at = data.rfind(MARKER, 0, at)
    return None


def find_normals(data: bytes, min_run: int = 512) -> tuple[int, int] | None:
    """(byte offset, entries) of the longest run of unit s16 triples - the
    global normal array.  Both byte parities and all three triple phases are
    tried; zero triples do not extend a run (UV padding is full of them)."""
    best = (0, 0)
    for parity in (0, 1):
        h = np.frombuffer(data, ">i2", (len(data) - parity) // 2, parity).astype(np.int64)
        if len(h) < 6:
            continue
        sq = h * h
        s3 = sq[:-2] + sq[1:-1] + sq[2:]
        unit = np.abs(np.sqrt(s3.astype(np.float64)) * NRM_SCALE - 1.0) < 0.03
        for phase in (0, 1, 2):
            u = unit[phase::3]
            if not len(u):
                continue
            # longest run of True
            d = np.diff(np.concatenate(([0], u.view(np.int8), [0])))
            starts = np.where(d == 1)[0]
            ends = np.where(d == -1)[0]
            if not len(starts):
                continue
            k = int(np.argmax(ends - starts))
            run = int(ends[k] - starts[k])
            if run > best[1]:
                off = parity + 2 * (phase + 3 * int(starts[k]))
                best = (off, run)
    return best if best[1] >= min_run else None


def _containment(data: bytes, sigs: list[int], pos: np.ndarray, limit: int = 24) -> float:
    """Mean fraction of mesh vertices inside each mesh's own header sphere.
    The level meshes sit at the END of the pack (the front is prop objects
    with inline arrays, which never fit), so the vote samples from the back."""
    scores = []
    for s in sigs[-limit:]:
        sphere = np.frombuffer(data[s - 20 : s - 4], ">f4")
        dl = int(np.frombuffer(data[s + 12 : s + 16], ">u4")[0])
        parsed = parse_dl(data, s + 28, dl)
        if parsed is None or "pos" not in parsed[0]:
            continue
        pi = parsed[0]["pos"]
        if pi.max() >= len(pos):
            scores.append(0.0)
            continue
        d = np.linalg.norm(pos[pi] - sphere[:3], axis=1)
        scores.append(float((d <= max(float(sphere[3]), 1.0) * 1.05 + 2.0).mean()))
    return float(np.mean(scores)) if scores else 0.0


def locate_arrays(data: bytes, sigs: list[int]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    counts = scene_counts(data)
    if counts is None:
        raise GunMpkError("no scene header (aa ff ee ff counts) found")
    npos, nnrm, ncol, nuv = counts
    nrm = find_normals(data)
    if nrm is None:
        raise GunMpkError("no unit-normal run found")
    nrm0, run = nrm
    if run < min(nnrm, 1024) // 2:
        warnings.append(f"normal run {run} much shorter than count {nnrm}")
    uv0 = (nrm0 - 4 * nuv) & ~3
    col0 = uv0 - 4 * ncol
    pos_est = col0 - 16 - 12 * npos
    # the padding between the position and colour arrays varies: vote with the
    # meshes' own bounding spheres
    best = (0.0, pos_est)
    for delta in range(-48, 52, 4):
        p0 = pos_est + delta
        if p0 < 0 or p0 + 12 * npos > len(data):
            continue
        pos = np.frombuffer(data, ">f4", npos * 3, p0).reshape(-1, 3)
        if not np.isfinite(pos).all():
            continue
        with np.errstate(over="ignore", invalid="ignore"):
            score = _containment(data, sigs, pos)
        if score > best[0]:
            best = (score, p0)
    score, pos0 = best
    if score < 0.9:
        raise GunMpkError(f"position array not found (best sphere containment {score:.2f})")
    return (
        dict(pos0=pos0, npos=npos, col0=col0, ncol=ncol, uv0=uv0, nuv=nuv, nrm0=nrm0, nnrm=nnrm),
        warnings,
    )


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------


def find_meshes(data: bytes) -> list[int]:
    """Offsets of every mesh signature (of the u16 pair 00 15 00 04 whose
    display-list size at -36 is repeated at +12)."""
    out = []
    off = 0
    n = len(data)
    while True:
        i = data.find(MESH_SIG, off)
        if i < 0:
            return out
        off = i + 2
        if i < 36 or i + 28 > n:
            continue
        dl2 = int.from_bytes(data[i + 12 : i + 16], "big")
        dl1 = int.from_bytes(data[i - 36 : i - 32], "big")
        if dl1 == dl2 and 0 < dl2 < 0x100000 and i + 28 + dl2 <= n:
            out.append(i)


def _vcd_fields(lo: int, hi: int) -> list[tuple[str, int]]:
    fields = []
    sizes = {0: 0, 1: 0, 2: 1, 3: 2}
    if lo & 1:
        fields.append(("pnmtx", 1))
    for i in range(8):
        if (lo >> (1 + i)) & 1:
            fields.append((f"tmtx{i}", 1))
    for name, shift in (("pos", 9), ("nrm", 11), ("col0", 13), ("col1", 15)):
        s = sizes[(lo >> shift) & 3]
        if s:
            fields.append((name, s))
    for i in range(8):
        s = sizes[(hi >> (2 * i)) & 3]
        if s:
            fields.append((f"tex{i}", s))
    return fields


def _triangulate(op: int, n: int) -> np.ndarray:
    if n < 3:
        return np.zeros((0, 3), np.int64)
    if op == 0x98:  # strip
        i = np.arange(n - 2)
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        return np.stack([i, b, c], axis=1)
    if op == 0x90:  # triangles
        return np.arange(n - n % 3).reshape(-1, 3)
    if op == 0xA0:  # fan
        i = np.arange(1, n - 1)
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    q = np.arange(n // 4) * 4  # quads
    return np.concatenate([np.stack([q, q + 1, q + 2], 1), np.stack([q, q + 2, q + 3], 1)])


def parse_dl(data: bytes, start: int, size: int):
    """(corners, triangles, total) - corners maps attr name -> (N,) int64
    index per drawn corner; triangles index the corners."""
    pos = start
    end = min(start + size, len(data))
    lo = hi = None
    fields = None
    vdt = stride = None
    per: dict[str, list[np.ndarray]] = {}
    tris = []
    base = 0
    while pos < end:
        op = data[pos]
        if op == 0x08 and pos + 6 <= end:
            reg = data[pos + 1]
            val = int.from_bytes(data[pos + 2 : pos + 6], "big")
            if reg == 0x50:
                lo = val
            elif reg == 0x60:
                hi = val
            pos += 6
        elif op == 0x10 and pos + 5 <= end:
            cnt = int.from_bytes(data[pos + 1 : pos + 3], "big") + 1
            pos += 5 + 4 * cnt
        elif op == 0x61:
            pos += 5
        elif op == 0x00:
            pos += 1
        elif (op & 0xF8) in _DRAW_OPS and pos + 3 <= end:
            if lo is None or hi is None:
                return None
            if fields is None:
                fields = _vcd_fields(lo, hi)
                stride = sum(s for _, s in fields)
                if stride == 0:
                    return None
                vdt = np.dtype([(nm, ">u1" if s == 1 else ">u2") for nm, s in fields])
                per = {nm: [] for nm, _ in fields}
            cnt = int.from_bytes(data[pos + 1 : pos + 3], "big")
            pos += 3
            if cnt == 0 or pos + cnt * stride > end:
                return None
            arr = np.frombuffer(data, vdt, cnt, pos)
            pos += cnt * stride
            for nm, _ in fields:
                per[nm].append(arr[nm].astype(np.int64))
            tris.append(_triangulate(op & 0xF8, cnt) + base)
            base += cnt
        else:
            return None
    if not tris or fields is None:
        return None
    return {nm: np.concatenate(v) for nm, v in per.items()}, np.concatenate(tris), base


# ---------------------------------------------------------------------------
# whole level
# ---------------------------------------------------------------------------


def parse(data: bytes) -> Level:
    if not is_mpk(data[:32]):
        raise GunMpkError("not a Gun map pack")
    sigs = find_meshes(data)
    if not sigs:
        raise GunMpkError("no meshes found")
    arrays, warnings = locate_arrays(data, sigs)
    npos, ncol, nuv, nnrm = arrays["npos"], arrays["ncol"], arrays["nuv"], arrays["nnrm"]
    positions = np.frombuffer(data, ">f4", npos * 3, arrays["pos0"]).reshape(-1, 3)
    positions = positions.astype(np.float32)
    colors = np.frombuffer(data, np.uint8, ncol * 4, arrays["col0"]).reshape(-1, 4).copy()
    uvs = np.frombuffer(data, ">i2", nuv * 2, arrays["uv0"]).reshape(-1, 2).astype(np.float32)
    uvs *= UV_SCALE
    normals = np.frombuffer(data, ">i2", nnrm * 3, arrays["nrm0"]).reshape(-1, 3).astype(np.float32)
    normals *= NRM_SCALE

    meshes: list[Mesh] = []
    rejected = 0
    for s in sigs:
        sphere = tuple(float(v) for v in np.frombuffer(data[s - 20 : s - 4], ">f4"))
        material = int.from_bytes(data[s - 32 : s - 28], "big")
        flags = int.from_bytes(data[s - 28 : s - 24], "big")
        checksum = int.from_bytes(data[s - 24 : s - 20], "big")
        dl = int.from_bytes(data[s + 12 : s + 16], "big")
        parsed = parse_dl(data, s + 28, dl)
        if parsed is None:
            rejected += 1
            continue
        corners, tris, _total = parsed
        pi = corners.get("pos")
        if pi is None or pi.max() >= npos:
            rejected += 1
            continue
        # prop meshes index their object's inline arrays, not the global ones:
        # their vertices land far outside the mesh's own bounding sphere
        d = np.linalg.norm(positions[pi] - np.array(sphere[:3], np.float32), axis=1)
        if (d <= max(sphere[3], 1.0) * 1.05 + 2.0).mean() < 0.98:
            rejected += 1
            continue
        meshes.append(Mesh(material, checksum, flags, sphere, corners, tris))
    if not meshes:
        raise GunMpkError("no level meshes survived the sphere check")
    return Level(positions, normals, colors, uvs, meshes, rejected, warnings)
