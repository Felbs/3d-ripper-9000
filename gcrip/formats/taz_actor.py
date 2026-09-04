"""Taz: Wanted Blitz actors - the 2002 BlitzTech generation of ``.tba``, older than the
Bratz layout in :mod:`gcrip.formats.blitz_actor` and different in every offset.

Mapped from the resources themselves (``docs/formats/`` has the note); the oracles are the
actor's own header: a bounding box at +0xa0 as ``f32 (xmin,xmax,ymin,ymax,zmin,zmax)``,
``f32 maxRadius`` at +0x9c and the resource size at +0xbc (265 of 267 actors in the hub pack
fit).  Geometry is GX display lists over indexed arrays like every Blitz generation, but

- the vertex is always ``u16 pos, u16 nrm, u16 clr, u16 tex`` (stride 8, the CP load
  ``08 50 00 00 7e 00`` says so and no other stride appears),
- positions **and normals** are ``f32 xyz`` (normals are s8 in the Bratz layout; here 100%%
  of them are unit-length floats), texcoords ``f32 st``, colours RGBA8,
- display lists carry inline CP (``0x08``) and XF (``0x10``) loads the Bratz reader never
  sees - the XF loads are the skin matrices, one per batch of strips,
- a **rigid mesh** is a 6-word record ``pos nrm tex clr dl_off dl_size`` (``dl_size`` may
  overrun the resource end - it is the padded allocation, so the walk clamps),
- a **skinned actor** instead owns one table of ``(dl_off, dl_size)`` pairs, hundreds of
  tiny lists (one per bone batch), and single shared arrays that nothing points at - they
  are found by the same oracles that validate everything else (the window of max-position
  index f32 triples inside the bbox, the window of unit-length triples for normals),
- texture CRCs sit in 16-byte batch records, ``{prim_count, crc, 0, 0}`` on rigid actors
  and ``{crc, 0, 0, prim_count}`` on skinned ones, consumed in prim order.

The reader trusts nothing it cannot verify: a mesh record only counts when its display list
walks cleanly AND its positions land in the header bbox AND its normals are unit length.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats.blitz_actor import Actor, ActorError, MeshData, _prims_to_tris

HEADER_AT = 0x80
RADIUS_AT = 0x9C
BBOX_AT = 0xA0
SIZE_AT = 0xBC
MIN_LEN = 0xD0
_PRIM_KINDS = (0x80, 0x90, 0x98, 0xA0)


def looks_like(data: bytes) -> bool:
    """The header identity: radius, min/max bbox pairs, resource size ~ member size."""
    if len(data) < MIN_LEN or data[6] != 1:
        return False
    try:
        radius = struct.unpack_from(">f", data, RADIUS_AT)[0]
        box = struct.unpack_from(">6f", data, BBOX_AT)
        size = struct.unpack_from(">I", data, SIZE_AT)[0]
    except struct.error:
        return False
    if not (0 < radius < 1e6) or not all(np.isfinite(box)):
        return False
    if not (box[0] <= box[1] and box[2] <= box[3] and box[4] <= box[5]):
        return False
    return abs(size - len(data)) <= 4096


def _walk(data: bytes, dlo: int, end: int):
    """Tolerant GX walk: [(opcode, index rows)] plus per-attr max index; stops quietly at
    the first byte that is not a NOP, CP/XF load or known primitive."""
    i = dlo
    prims: list[tuple[int, np.ndarray]] = []
    mx = [0, 0, 0, 0]
    while i < end:
        op = data[i]
        if op == 0x00:
            i += 1
            continue
        if op == 0x08:
            if i + 6 > end:
                break
            i += 6
            continue
        if op == 0x10:
            if i + 5 > end:
                break
            cnt = struct.unpack_from(">H", data, i + 1)[0]
            i += 5 + 4 * (cnt + 1)
            continue
        kind = op & 0xF8
        if kind in _PRIM_KINDS and (op & 7) == 0:
            if i + 3 > end:
                break
            nv = struct.unpack_from(">H", data, i + 1)[0]
            if nv == 0 or nv > 10000 or i + 3 + nv * 8 > end:
                break
            idx = np.frombuffer(data, dtype=">u2", count=nv * 4, offset=i + 3).reshape(-1, 4)
            prims.append((kind, idx))
            i += 3 + nv * 8
            for k in range(4):
                mx[k] = max(mx[k], int(idx[:, k].max()))
            continue
        break
    return prims, mx


def _in_box(v: np.ndarray, box, slack: float = 2.0) -> float:
    ok = (
        (v[:, 0] >= box[0] - slack)
        & (v[:, 0] <= box[1] + slack)
        & (v[:, 1] >= box[2] - slack)
        & (v[:, 1] <= box[3] + slack)
        & (v[:, 2] >= box[4] - slack)
        & (v[:, 2] <= box[5] + slack)
    )
    return float(np.mean(ok)) if len(v) else 0.0


def _f32(data: bytes, at: int, n: int, k: int) -> np.ndarray | None:
    if not at or n <= 0 or at + n * k * 4 > len(data):
        return None
    v = np.frombuffer(data, dtype=">f4", count=n * k, offset=at).reshape(n, k)
    return v.astype(np.float32) if np.all(np.isfinite(v)) else None


def _oracle(data: bytes, pos_at: int, nrm_at: int, mx, box) -> float:
    """min(inbox, unit) for a candidate mesh; -1 when the arrays do not even read."""
    pos = _f32(data, pos_at, mx[0] + 1, 3)
    nrm = _f32(data, nrm_at, mx[1] + 1, 3)
    if pos is None or nrm is None:
        return -1.0
    inb = _in_box(pos, box) if box[1] > box[0] else 1.0
    if mx[1] + 1 <= 2:
        return inb
    unit = float(np.mean(np.abs(np.linalg.norm(nrm, axis=1) - 1) < 0.05))
    return min(inb, unit)


def _rigid_meshes(data: bytes, box) -> list[dict]:
    """Every 6-word ``pos nrm tex clr dl_off dl_size`` record the oracles accept, deduped
    by display list (best score wins)."""
    L = len(data)
    words = np.frombuffer(data, dtype=">u4", count=L // 4)
    best: dict[int, dict] = {}
    for w in range(MIN_LEN // 4, len(words) - 6):
        pos, nrm, tex, clr, dlo, dls = (int(x) for x in words[w : w + 6])
        if not (0 < pos < L and 0 < nrm < L and 0 < dlo < L and dls > 0):
            continue
        if pos % 4 or nrm % 4 or dlo % 16 or pos == nrm or dlo in (pos, nrm):
            continue
        if tex and (tex >= L or tex % 4):
            continue
        if clr and (clr >= L or clr % 4):
            continue
        end = min(dlo + dls, L)
        for a in (pos, nrm, tex, clr):  # the arrays cap a DL whose padded size overruns
            if a and a > dlo:
                end = min(end, a)
        prims, mx = _walk(data, dlo, end)
        if not prims:
            continue
        score = _oracle(data, pos, nrm, mx, box)
        if score < 0.95:
            continue
        cur = best.get(dlo)
        if cur is None or score > cur["score"]:
            best[dlo] = dict(
                score=score, pos=pos, nrm=nrm, tex=tex, clr=clr, dlo=dlo, prims=prims, mx=mx
            )
    return [best[k] for k in sorted(best)]


#: every display list opens by loading the vertex descriptor - pos/nrm/clr/tex as u16 indices
DL_SIG = b"\x08\x50\x00\x00\x7e\x00"


def _sig_lists(data: bytes) -> list[tuple[int, int]]:
    """(start, end) of every display-list block, anchored on the CP vertex-descriptor load
    each one opens with.  On the skinned sample this finds 496 of 496 blocks where the
    actor's own (offset, size) table is entangled with the skin-influence table before it."""
    hits = []
    at = data.find(DL_SIG)
    while at != -1:
        hits.append(at)
        at = data.find(DL_SIG, at + 1)
    return [(h, hits[i + 1] if i + 1 < len(hits) else len(data)) for i, h in enumerate(hits)]


def _hunt_array(data: bytes, n: int, k: int, score_fn) -> int | None:
    """Best window of ``n`` k-wide f32 rows anywhere in the resource, by score_fn (fraction
    of rows passing); None under 0.98.  This is how a skinned actor's unreferenced shared
    arrays are found."""
    L = len(data)
    if n <= 0 or n * k * 4 > L:
        return None
    best = (0.0, None)
    allf = np.frombuffer(data, dtype=">f4", count=L // 4)
    for phase in range(k):
        v = allf[phase:]
        m = len(v) // k
        if m < n:
            continue
        rows = v[: m * k].reshape(-1, k)
        good = score_fn(rows) & np.all(np.isfinite(rows), axis=1)
        c = np.concatenate([[0], np.cumsum(good, dtype=np.int64)])
        w = c[n:] - c[:-n]
        top = int(np.argmax(w))
        frac = w[top] / n
        if frac > best[0]:
            best = (float(frac), phase * 4 + top * k * 4)
    return best[1] if best[0] >= 0.98 else None


def _batches(data: bytes, tex_crcs: set[int] | None) -> list[tuple[int, int]]:
    """(prim_count, texture_crc) in offset order - rigid records are {count, crc, 0, 0},
    skinned {crc, 0, 0, count}.  Without a CRC set nothing can be recognised."""
    if not tex_crcs:
        return []
    words = np.frombuffer(data, dtype=">u4", count=len(data) // 4)
    out = []
    for i in range(len(words) - 3):
        a, b, c, d = (int(x) for x in words[i : i + 4])
        if b in tex_crcs and 0 < a < 5000 and c == 0 and d == 0:
            out.append((i * 4, a, b))
        elif a in tex_crcs and b == 0 and c == 0 and 0 < d < 5000:
            out.append((i * 4, d, a))
    # a CRC word can match at two alignments; keep the first record of any overlapping pair
    keep = []
    last_end = -1
    for at, cnt, crc in out:
        if at >= last_end:
            keep.append((cnt, crc))
            last_end = at + 16
    return keep


def _mesh_data(data: bytes, node: str, prims, mx, pos_at, nrm_at, tex_at, clr_at, texture=0):
    pos = _f32(data, pos_at, mx[0] + 1, 3)
    if pos is None:
        return None
    nrm = _f32(data, nrm_at, mx[1] + 1, 3)
    tex = _f32(data, tex_at, mx[3] + 1, 2) if tex_at else None
    clr = None
    if clr_at and clr_at + (mx[2] + 1) * 4 <= len(data):
        clr = np.frombuffer(data, dtype=np.uint8, count=(mx[2] + 1) * 4, offset=clr_at).reshape(
            -1, 4
        )
    keys: dict[tuple, int] = {}
    tris: list[tuple[int, int, int]] = []
    for kind, idx in prims:
        local = []
        for row in idx:
            key = tuple(int(x) for x in row)
            j = keys.get(key)
            if j is None:
                j = keys[key] = len(keys)
            local.append(j)
        tris += _prims_to_tris(kind, local)
    if not tris:
        return None
    order = list(keys)
    take = np.array(order, dtype=np.int64)
    md = MeshData(
        node, texture, 0, pos[take[:, 0]], np.asarray(tris, dtype=np.uint32).reshape(-1)
    )
    if nrm is not None and take[:, 1].max() < len(nrm):
        md.normals = nrm[take[:, 1]]
    if tex is not None and take[:, 3].max() < len(tex):
        md.uvs = tex[take[:, 3]]
    if clr is not None and take[:, 2].max() < len(clr):
        md.colors = np.ascontiguousarray(clr[take[:, 2]])
    return md


def parse(data: bytes, tex_crcs: set[int] | None = None) -> Actor:
    """The Taz-generation actor as the shared :class:`Actor` shape (no node tree - the
    geometry is in model space, so the static shapes are complete without it)."""
    if not looks_like(data):
        raise ActorError("not a Taz-generation Blitz actor")
    box = struct.unpack_from(">6f", data, BBOX_AT)
    actor = Actor(vertex_type=8, bbox=box)
    batches = _batches(data, tex_crcs)

    def texture_for(prim_index: int) -> int:
        used = 0
        for cnt, crc in batches:
            if prim_index < used + cnt:
                return crc
            used += cnt
        return batches[-1][1] if batches else 0

    seen_prims = 0
    rigid = _rigid_meshes(data, box)
    for m in rigid:
        md = _mesh_data(
            data,
            "mesh",
            m["prims"],
            m["mx"],
            m["pos"],
            m["nrm"],
            m["tex"],
            m["clr"],
            texture=texture_for(seen_prims),
        )
        seen_prims += len(m["prims"])
        if md is not None:
            actor.meshes.append(md)

    if not actor.meshes:
        blocks = _sig_lists(data)
        if blocks:
            all_prims: list[tuple[int, np.ndarray]] = []
            mx = [0, 0, 0, 0]
            for dlo, end in blocks:
                prims, m2 = _walk(data, dlo, end)
                all_prims += prims
                for k in range(4):
                    mx[k] = max(mx[k], m2[k])
            if all_prims:
                pos_at = _hunt_array(
                    data, mx[0] + 1, 3, lambda r: (
                        (r[:, 0] >= box[0] - 2) & (r[:, 0] <= box[1] + 2)
                        & (r[:, 1] >= box[2] - 2) & (r[:, 1] <= box[3] + 2)
                        & (r[:, 2] >= box[4] - 2) & (r[:, 2] <= box[5] + 2)
                    ),
                )
                nrm_at = _hunt_array(
                    data, mx[1] + 1, 3,
                    lambda r: np.abs(np.sqrt((r * r).sum(1)) - 1) < 0.05,
                )
                tex_at = _hunt_array(
                    data, mx[3] + 1, 2,
                    lambda r: (np.abs(r) <= 32).all(axis=1) & (np.abs(r) >= 1e-6).any(axis=1),
                )
                if pos_at is not None:
                    # one mesh per batch so each bone group keeps its texture
                    at = 0
                    groups = batches or [(len(all_prims), 0)]
                    for cnt, crc in groups:
                        chunk = all_prims[at : at + cnt]
                        at += cnt
                        if not chunk:
                            continue
                        md = _mesh_data(
                            data, "skin", chunk, mx, pos_at, nrm_at or 0, tex_at or 0, 0,
                            texture=crc,
                        )
                        if md is not None:
                            actor.meshes.append(md)
                    if at < len(all_prims):
                        md = _mesh_data(
                            data, "skin", all_prims[at:], mx, pos_at, nrm_at or 0,
                            tex_at or 0, 0,
                        )
                        if md is not None:
                            actor.meshes.append(md)
    if not actor.meshes:
        raise ActorError("no meshes pass the oracles")
    return actor
