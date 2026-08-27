"""Retro skeletons and skin rules: CINF (bones), CSKR (vertex weights), and the ANCS
character set that ties a CMDL to them. Layouts checked against Prime 1 and Echoes.

CINF: u32 bone count; per bone: u32 id, u32 parent id, f32[3] position (bind pose, model
space), [Echoes: f32[4] rotation w x y z, f32[4] local rotation], u32 linked count,
u32[] linked ids; u32 build-order count, u32[] ids; u32 name count, per name: C string,
u32 bone id. Prime 1 bone entries are 0x14 bytes + links, Echoes 0x34 + links - told
apart by checking which stride makes the parent ids resolve.

CSKR: u32 group count; per group: u32 weight count, (u32 bone id, f32 weight)[], u32
vertex count - groups cover the model's position array in order. A footer follows.

ANCS (character set): u16 1, u16 1, u32 count; per character: u32 id, u16 version,
C string name, u32 CMDL, u32 CSKR, u32 CINF, ... (the rest is skipped by scanning for
CMDL/CSKR/CINF id triples that all resolve to resources in the same PAK).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np


class SkinError(ValueError):
    pass


@dataclass
class Bone:
    id: int
    parent: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float] | None = None  # x y z w


@dataclass
class Skeleton:
    bones: list[Bone]
    names: dict[int, str] = field(default_factory=dict)

    def index_of(self, bone_id: int) -> int | None:
        for i, b in enumerate(self.bones):
            if b.id == bone_id:
                return i
        return None


def _cstring(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\0", pos)
    return data[pos:end].decode("ascii", "replace"), end + 1


def _parse_bones(data: bytes, count: int, echoes: bool) -> tuple[list[Bone], int]:
    bones = []
    pos = 4
    for _ in range(count):
        bid, parent, x, y, z = struct.unpack_from(">II3f", data, pos)
        pos += 0x14
        rot = None
        if echoes:
            w, rx, ry, rz = struct.unpack_from(">4f", data, pos)
            rot = (rx, ry, rz, w)
            pos += 0x20
        (nl,) = struct.unpack_from(">I", data, pos)
        pos += 4 + 4 * nl
        if nl > 1024:
            raise SkinError("implausible link count")
        bones.append(Bone(bid, parent, (x, y, z), rot))
    return bones, pos


def parse_cinf(data: bytes) -> Skeleton:
    (count,) = struct.unpack_from(">I", data, 0)
    if count == 0 or count > 4096:
        raise SkinError("bad bone count")
    last_err: Exception | None = None
    for echoes in (False, True):
        try:
            bones, pos = _parse_bones(data, count, echoes)
        except (struct.error, SkinError) as e:
            last_err = e
            continue
        ids = {b.id for b in bones}
        # every bone but the root(s) must point at a bone in the table
        orphans = sum(1 for b in bones if b.parent not in ids)
        if orphans > 1:
            last_err = SkinError("parent ids do not resolve")
            continue
        (nb,) = struct.unpack_from(">I", data, pos)
        pos += 4 + 4 * nb
        (nn,) = struct.unpack_from(">I", data, pos)
        pos += 4
        names = {}
        for _ in range(nn):
            s, pos = _cstring(data, pos)
            (bid,) = struct.unpack_from(">I", data, pos)
            pos += 4
            names[bid] = s
        return Skeleton(bones, names)
    raise SkinError(f"CINF does not parse: {last_err}")


def parse_cskr(data: bytes) -> list[tuple[list[tuple[int, float]], int]]:
    """[(weights [(bone id, weight)], vertex count)] in position-array order."""
    (ng,) = struct.unpack_from(">I", data, 0)
    pos = 4
    groups = []
    for _ in range(ng):
        (wc,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if wc > 64:
            raise SkinError("implausible weight count")
        ws = [struct.unpack_from(">If", data, pos + 8 * k) for k in range(wc)]
        pos += 8 * wc
        (vc,) = struct.unpack_from(">I", data, pos)
        pos += 4
        groups.append(([(b, float(w)) for b, w in ws], vc))
    return groups


def skin_arrays(
    groups: list[tuple[list[tuple[int, float]], int]], skel: Skeleton, n_vertices: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per-position (N,4) joint indices and (N,4) weights (4 strongest, renormalised)."""
    joints = np.zeros((n_vertices, 4), np.uint16)
    weights = np.zeros((n_vertices, 4), np.float32)
    weights[:, 0] = 1.0
    v = 0
    for ws, vc in groups:
        if v >= n_vertices:
            break
        resolved = [(skel.index_of(b), w) for b, w in ws]
        resolved = [(j, w) for j, w in resolved if j is not None and w > 0]
        resolved.sort(key=lambda t: -t[1])
        resolved = resolved[:4]
        end = min(v + vc, n_vertices)
        if resolved:
            tot = sum(w for _, w in resolved) or 1.0
            j = np.zeros(4, np.uint16)
            w4 = np.zeros(4, np.float32)
            for k, (ji, wt) in enumerate(resolved):
                j[k] = ji
                w4[k] = wt / tot
            joints[v:end] = j
            weights[v:end] = w4
        v = end
    return joints, weights


def ancs_characters(data: bytes, resolve) -> list[tuple[int, int, int]]:
    """(CMDL, CSKR, CINF) id triples found in an ANCS. `resolve(type, id)` says whether an
    id exists as that resource type; the first character is read from the header, the
    rest are found by scanning for triples that all resolve."""
    out = []
    if len(data) < 24 or data[:4] != b"\x00\x01\x00\x01":
        return out
    for shift in range(4):
        view = np.frombuffer(data[shift : shift + (len(data) - shift) // 4 * 4], dtype=">u4")
        if len(view) < 3:
            continue
        for i in np.nonzero([resolve("CMDL", int(x)) for x in view[:-2]])[0]:
            cmdl, cskr, cinf = int(view[i]), int(view[i + 1]), int(view[i + 2])
            if resolve("CSKR", cskr) and resolve("CINF", cinf):
                trip = (cmdl, cskr, cinf)
                if trip not in out:
                    out.append(trip)
    return out
