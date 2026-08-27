"""HSD joint animations: figatrees (Melee's PlXxAJ.dat archives) sampled into Clips.

PlXxAJ.dat is a plain concatenation of DAT files, each padded to 32 bytes, each with one
`*_figatree` root (checked on PlFxAJ.dat: 221 sub-files, `PlyFox5K_Share_ACTION_Wait1_figatree`).

HSD_FigaTree: 0x00 u32 type (1)  0x04 u32 0  0x08 f32 frame count
              0x0C ptr u8[] tracks per joint, joints in tree traversal order, 0xFF ends
              0x10 ptr HSD_Track[]
HSD_Track (0xC): u16 stream length, u16 0, u8 track type (HSD_A_J_*: 1-3 rotation XYZ in
              radians, 5-7 translation, 8-10 scale), u8 value format, u8 tangent format,
              u8 0, u32 stream offset (data block relative)
Value / tangent format: bits 5-7 type (0 f32, 1 s16, 2 u16, 3 s8, 4 u8), bits 0-4 frac.
Stream (little endian!): packets of an opcode byte (low nibble: 1 CON 2 LIN 3 SPL0 4 SPL
5 SLP 6 KEY; bits 4-6 + continuation bytes: key count - 1) followed by that many keys:
CON/LIN/SPL0 = value, wait; SPL = value, slope, wait; SLP = slope (applies to the next
key); KEY = value. Waits are 7-bit continuation varints of frames since the last key.
Matches sysdolphin's fobj.c (parseFloat / parsePackInfo / FObjAnim*)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import hsd
from ripcore.scene import Clip

OP_CON, OP_LIN, OP_SPL0, OP_SPL, OP_SLP, OP_KEY = 1, 2, 3, 4, 5, 6
TRACK_ROT = (1, 2, 3)
TRACK_TRA = (5, 6, 7)
TRACK_SCA = (8, 9, 10)


def split_archive(data: bytes) -> list[tuple[int, int]]:
    """(offset, size) of every DAT inside a concatenated animation archive."""
    out = []
    off = 0
    while off + hsd.HEADER <= len(data):
        fsz, dsz, nrel, nroot, nref = struct.unpack_from(">IIIII", data, off)
        if fsz < hsd.HEADER or off + fsz > len(data) or dsz > fsz or nroot + nref == 0:
            break
        out.append((off, fsz))
        off += (fsz + 31) & ~31
    return out


def is_archive(data: bytes) -> bool:
    return len(split_archive(data)) >= 2


@dataclass
class Track:
    kind: int
    keys: list[tuple[float, float, float, int]]  # (frame, value, slope, op)


@dataclass
class Figatree:
    name: str
    frames: float
    joints: list[list[Track]]


def _parse_value(buf: bytes, pos: int, fmt: int) -> tuple[float, int]:
    kind, frac = fmt & 0xE0, fmt & 0x1F
    if kind == 0:
        return struct.unpack_from("<f", buf, pos)[0], pos + 4
    denom = float(1 << frac)
    if kind == 0x20:
        return struct.unpack_from("<h", buf, pos)[0] / denom, pos + 2
    if kind == 0x40:
        return struct.unpack_from("<H", buf, pos)[0] / denom, pos + 2
    if kind == 0x60:
        return struct.unpack_from("<b", buf, pos)[0] / denom, pos + 1
    if kind == 0x80:
        return buf[pos] / denom, pos + 1
    return 0.0, pos


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    v = 0
    shift = 0
    while pos < len(buf):
        d = buf[pos]
        pos += 1
        v |= (d & 0x7F) << shift
        shift += 7
        if not d & 0x80:
            break
    return v, pos


Key = tuple[float, float, float, int]  # frame, value, slope, opcode


def decode_stream(buf: bytes, value_fmt: int, slope_fmt: int) -> list[Key]:
    keys: list[Key] = []
    pos = 0
    frame = 0.0
    pending_slope: float | None = None
    n = len(buf)
    while pos < n:
        d = buf[pos]
        op = d & 0x0F
        count = ((d >> 4) & 7) + 1
        pos += 1
        shift = 3
        while d & 0x80 and pos < n:
            d = buf[pos]
            pos += 1
            count += (d & 0x7F) << shift
            shift += 7
        for _ in range(count):
            if pos >= n:
                break
            slope = 0.0
            if op in (OP_CON, OP_LIN, OP_SPL0, OP_SPL, OP_KEY):
                value, pos = _parse_value(buf, pos, value_fmt)
                if op == OP_SPL:
                    slope, pos = _parse_value(buf, pos, slope_fmt)
                if pending_slope is not None:
                    slope = pending_slope
                    pending_slope = None
                keys.append((frame, value, slope, op))
                if op != OP_KEY:
                    wait, pos = _varint(buf, pos)
                    frame += wait
            elif op == OP_SLP:
                s, pos = _parse_value(buf, pos, slope_fmt)
                pending_slope = s
            else:
                return keys
    return keys


def sample(keys: list[tuple[float, float, float, int]], frames: int, rest: float) -> np.ndarray:
    """Evaluate a track at frames 0..frames-1."""
    if not keys:
        return np.full(frames, rest, np.float32)
    if len(keys) == 1:
        return np.full(frames, keys[0][1], np.float32)
    kf = np.array([k[0] for k in keys], np.float64)
    kv = np.array([k[1] for k in keys], np.float64)
    ks = np.array([k[2] for k in keys], np.float64)
    kop = np.array([k[3] for k in keys], np.int64)
    t = np.arange(frames, dtype=np.float64)
    seg = np.clip(np.searchsorted(kf, t, side="right") - 1, 0, len(keys) - 2)
    f0, f1 = kf[seg], kf[seg + 1]
    v0, v1 = kv[seg], kv[seg + 1]
    d = f1 - f0
    u = np.clip(np.where(d > 0, (t - f0) / np.where(d > 0, d, 1.0), 0.0), 0.0, 1.0)
    u2, u3 = u * u, u * u * u
    hermite = (
        (2 * u3 - 3 * u2 + 1) * v0
        + (u3 - 2 * u2 + u) * d * ks[seg]
        + (-2 * u3 + 3 * u2) * v1
        + (u3 - u2) * d * ks[seg + 1]
    )
    op = kop[seg]
    out = np.where(op == OP_LIN, v0 + (v1 - v0) * u, hermite)
    out = np.where((op == OP_CON) | (op == OP_KEY), v0, out)
    out = np.where(t >= kf[-1], kv[-1], out)
    out = np.where(t <= kf[0], kv[0], out)
    return out.astype(np.float32)


def parse_figatree(dat: hsd.DatFile, off: int, name: str) -> Figatree | None:
    if not dat.valid(off, 0x14):
        return None
    ftype, _z, frames, counts_ptr, tracks_ptr = struct.unpack_from(
        ">IIfII", dat.data, hsd.HEADER + off
    )
    if ftype != 1 or not dat.valid(counts_ptr) or not dat.valid(tracks_ptr):
        return None
    counts = []
    k = 0
    while dat.valid(counts_ptr + k, 1) and k < 4096:
        c = dat.u8(counts_ptr + k)
        if c == 0xFF:
            break
        counts.append(c)
        k += 1
    joints: list[list[Track]] = []
    ti = 0
    for c in counts:
        tracks = []
        for _ in range(c):
            t = tracks_ptr + ti * 0xC
            ti += 1
            if not dat.valid(t, 0xC):
                break
            length, _p, kind, vfmt, sfmt, _p2, data_off = struct.unpack_from(
                ">HHBBBBI", dat.data, hsd.HEADER + t
            )
            if not dat.valid(data_off, length):
                continue
            tracks.append(Track(kind, decode_stream(dat.bytes(data_off, length), vfmt, sfmt)))
        joints.append(tracks)
    return Figatree(name, frames, joints)


def figatree_clip(tree: Figatree, joints: list[hsd.Jobj], fps: float = 60.0) -> Clip:
    frames = max(1, int(round(tree.frames)) + 1)
    clip = Clip(name=tree.name, frames=frames, fps=fps)
    for ji, tracks in enumerate(tree.joints):
        if ji >= len(joints) or not tracks:
            continue
        j = joints[ji]
        kinds = {t.kind for t in tracks}
        if kinds & set(TRACK_ROT):
            rot = [
                sample(_track(tracks, k), frames, j.rotation[i]) for i, k in enumerate(TRACK_ROT)
            ]
            clip.rotation[ji] = euler_to_quat(np.stack(rot, axis=1))
        if kinds & set(TRACK_TRA):
            clip.translation[ji] = np.stack(
                [sample(_track(tracks, k), frames, j.position[i]) for i, k in enumerate(TRACK_TRA)],
                axis=1,
            )
        if kinds & set(TRACK_SCA):
            clip.scale[ji] = np.stack(
                [sample(_track(tracks, k), frames, j.scale[i]) for i, k in enumerate(TRACK_SCA)],
                axis=1,
            )
    return clip


def euler_to_quat(e: np.ndarray) -> np.ndarray:
    """(F,3) HSD euler radians (X then Y then Z) -> (F,4) quaternions x y z w."""
    hx, hy, hz = e[:, 0] * 0.5, e[:, 1] * 0.5, e[:, 2] * 0.5
    cx, sx, cy, sy, cz, sz = np.cos(hx), np.sin(hx), np.cos(hy), np.sin(hy), np.cos(hz), np.sin(hz)
    # q = qz * qy * qx
    w = cz * cy * cx + sz * sy * sx
    x = cz * cy * sx - sz * sy * cx
    y = cz * sy * cx + sz * cy * sx
    z = sz * cy * cx - cz * sy * sx
    q = np.stack([x, y, z, w], axis=1)
    # keep consecutive frames on the same hemisphere so LINEAR samplers do not flip
    if len(q) > 1:
        dots = np.sum(q[1:] * q[:-1], axis=1)
        sign = np.cumprod(np.where(dots < 0, -1.0, 1.0))
        q[1:] *= sign[:, None]
    return q.astype(np.float32)


def _track(tracks: list[Track], kind: int) -> list:
    for t in tracks:
        if t.kind == kind:
            return t.keys
    return []


def archive_trees(data: bytes) -> tuple[list[Figatree], int]:
    """Every figatree in an animation archive, plus the count of unreadable ones."""
    trees: list[Figatree] = []
    bad = 0
    for off, size in split_archive(data):
        try:
            sub = hsd.DatFile(data[off : off + size])
        except hsd.HsdError:
            bad += 1
            continue
        for r in sub.roots:
            if r.reference or not r.name.endswith("_figatree"):
                continue
            tree = parse_figatree(sub, r.offset, r.name[: -len("_figatree")])
            if tree is None:
                bad += 1
            else:
                trees.append(tree)
    return trees, bad


# a fighter's costumes share one archive: keep the last few decoded (key, trees, bad)
_tree_cache: list[tuple[tuple, list[Figatree], int]] = []


def archive_clips(
    data: bytes, joints: list[hsd.Jobj], fps: float = 60.0, key: tuple | None = None
) -> tuple[list[Clip], list[str]]:
    """Clips for every figatree in the archive whose joint count matches `joints`."""
    cache_key = (key, len(data), data[:64]) if key is not None else None
    hit = next((e for e in _tree_cache if e[0] == cache_key), None) if cache_key else None
    if hit is None:
        trees, bad = archive_trees(data)
        if cache_key is not None:
            _tree_cache.append((cache_key, trees, bad))
            del _tree_cache[:-3]
    else:
        _, trees, bad = hit
    clips = [figatree_clip(t, joints, fps) for t in trees if len(t.joints) == len(joints)]
    skipped = bad + len(trees) - len(clips)
    warnings = []
    if skipped:
        warnings.append(f"{skipped} figatrees skipped (joint count mismatch or unreadable)")
    return clips, warnings
