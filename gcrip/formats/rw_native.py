"""RenderWare GameCube **native** geometry - the unchunked tail of a CLUMP.

Piglet's BIG GAME carries 936 CLUMPs and `plugins/renderware.py` returns a scene for 68 of
them, because most of the geometry is flagged ``rpGEOMETRYNATIVE`` and holds no vertex arrays
where RenderWare would put them.  ``docs/OPEN.md`` recorded the data as "a raw block inside the
clump ... at entropy 7.37 ... **with no GX display lists in it**".

It is GX display lists.  A CLUMP's chunk walk covers STRUCT and FRAMELIST and then stops, and
everything after that - 2,215,106 bytes of a 2,232,166-byte clump - is native data: display
lists and vertex arrays with no chunk framing at all.

A **group** is one mesh::

    0x98 strips, 8-byte vertices of four big-endian u16, zero padding between
    ... 16 bytes ...
    positions   f32 x 3 big-endian, N of them
    ... 16 bytes ...
    normals     f32 x 3 big-endian, N of them
    ... 16 bytes ...
    colours     RGBA8, N of them
    texture coordinates  f32 x 2 big-endian, N of them

Two identities carry the whole reader, and neither can be satisfied by accident:

* **the indices cover exactly 0..N-1** - every one of a group's strips indexes the same array
  and uses every entry of it, so `distinct == max + 1` both fixes the vertex count and says
  whether a candidate strip run is a group at all.  A false run found at 155,403 claims 53,054
  vertices with 100 distinct values and is refused by this alone.
* **the normals are unit length** - 3,252 consecutive `f32` triples of length 1.0 to 4.15e-08 on
  the first group.  This is what locates the arrays: search forward from the lists for the
  unit-length block, and the positions are then a fixed ``16 + N * 12`` before it.

That last relation is the reason nothing has to be fitted.  Searching for the *positions* by
triangle locality does not work and actively misleads - it finds index arrays, which have tiny
triangles in a wide box, and prefers them (see ``gcrip/oracles.py``).  Searching for the
*normals* cannot: no other array in the file is 3,252 unit vectors in a row.

Measured on the biggest CLUMP in the first 40 MB of ``PIGGCN.pkd``: **36 candidate groups pass
containment, 25 of them resolve to positions and normals, ~45,592 triangles**.  The eleven that
do not find a unit-length block are declined rather than guessed at.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gcrip.identities import Identity

#: GX triangle strip, any vertex format
STRIP = 0x98
#: four big-endian u16 an indexed vertex
VERTEX = 8
#: bytes between one array and the next; four floats, not yet read
ARRAY_GAP = 16
#: zero padding between primitives
MAX_PAD = 64
#: a strip longer than this is not a strip
MAX_COUNT = 16384
#: below this a "group" is noise
MIN_VERTICES = 16
#: how far off unit length a normal may be
UNIT_TOLERANCE = 1e-3
#: how far past the lists the positions can start - measured gaps are 1 to 21 bytes
LEAD_SCAN = 64


@dataclass(frozen=True)
class Group:
    """One mesh: its strips, and where its arrays are."""

    lists_at: int
    lists_end: int
    strips: list  # [(offset, vertex count)]
    vertices: int
    positions_at: int | None = None
    normals_at: int | None = None

    @property
    def resolved(self) -> bool:
        return self.positions_at is not None


def _strips_from(data: bytes, at: int) -> tuple[list, int]:
    out = []
    n = len(data)
    while at + 3 <= n:
        p = at
        while p < n and data[p] == 0 and p - at < MAX_PAD:
            p += 1
        if p + 3 > n or data[p] != STRIP:
            break
        count = struct.unpack_from(">H", data, p + 1)[0]
        if not 2 < count <= MAX_COUNT or p + 3 + count * VERTEX > n:
            break
        out.append((p, count))
        at = p + 3 + count * VERTEX
    return out, at


def _indices(data: bytes, strips: list):
    import numpy as np

    return np.concatenate(
        [np.frombuffer(data, ">u2", c * 4, a + 3).reshape(c, 4) for a, c in strips]
    )


def candidates(data: bytes) -> list[Group]:
    """Every strip run whose indices cover exactly ``0..N-1`` with all four columns agreeing."""
    import numpy as np

    out: list[Group] = []
    at = 0
    n = len(data)
    while at < n - 3:
        if data[at] != STRIP:
            at += 1
            continue
        strips, end = _strips_from(data, at)
        if not strips:
            at += 1
            continue
        v = _indices(data, strips)
        top = int(v[:, 0].max()) + 1
        agree = float(((v[:, 0] == v[:, 1]) & (v[:, 1] == v[:, 2]) & (v[:, 2] == v[:, 3])).mean())
        if top >= MIN_VERTICES and len(set(v[:, 0].tolist())) == top and agree > 0.99:
            out.append(Group(at, end, strips, top))
            at = end
        else:
            at += 1
    return out


def resolve(data: bytes, groups: list[Group]) -> list[Group]:
    """Locate each group's arrays by its normals, which are the only unit-length block."""
    import numpy as np

    out: list[Group] = []
    n = len(data)
    for i, g in enumerate(groups):
        stop = groups[i + 1].lists_at if i + 1 < len(groups) else n
        span = g.vertices * 12
        pos = found = None
        # the positions start a few bytes after the lists and the normals a fixed
        # `ARRAY_GAP` past them, so try the near offsets and let the normals confirm - far
        # cheaper than scanning the whole gap for a unit-length block, and the same test
        for off in range(g.lists_end, min(g.lists_end + LEAD_SCAN, stop)):
            nrm = off + span + ARRAY_GAP
            if nrm + span > min(stop, n):
                break
            raw = np.frombuffer(data, ">f4", g.vertices * 3, nrm).reshape(-1, 3)
            if not np.isfinite(raw).all():
                continue
            w = raw.astype(np.float64)
            if float(np.abs(np.sqrt((w * w).sum(1)) - 1.0).max()) >= UNIT_TOLERANCE:
                continue
            arr = np.frombuffer(data, ">f4", g.vertices * 3, off).reshape(-1, 3)
            if not np.isfinite(arr).all() or not 1e-4 < float(np.abs(arr).max()) < 1e5:
                continue
            pos, found = off, nrm
            break
        if pos is None:
            out.append(g)
            continue
        out.append(Group(g.lists_at, g.lists_end, g.strips, g.vertices, pos, found))
    return out


def groups(data: bytes) -> list[Group]:
    return resolve(data, candidates(data))


def positions(data: bytes, g: Group):
    import numpy as np

    return np.frombuffer(data, ">f4", g.vertices * 3, g.positions_at).reshape(-1, 3)


def normals(data: bytes, g: Group):
    import numpy as np

    return np.frombuffer(data, ">f4", g.vertices * 3, g.normals_at).reshape(-1, 3)


def triangles(data: bytes, g: Group) -> list:
    """The group's strips flattened, dropping the degenerate joins."""
    import numpy as np

    out = []
    for at, count in g.strips:
        idx = np.frombuffer(data, ">u2", count * 4, at + 3).reshape(count, 4)[:, 0].tolist()
        for i in range(count - 2):
            tri = (
                (idx[i], idx[i + 1], idx[i + 2])
                if i % 2 == 0
                else (idx[i + 1], idx[i], idx[i + 2])
            )
            if tri[0] != tri[1] and tri[1] != tri[2] and tri[0] != tri[2]:
                out.append(tri)
    return out


# -- identities ---------------------------------------------------------------------------


def _indices_cover_the_array(data: bytes):
    found = candidates(data)
    if not found:
        return None, "no strip run passes containment"
    return True, f"{len(found)} groups index exactly 0..N-1 with all four columns agreeing"


def _normals_are_unit_length(data: bytes):
    import numpy as np

    done = groups(data)
    if not done:
        return None, "no groups"
    ok = [g for g in done if g.resolved]
    if not ok:
        return False, f"0 of {len(done)} groups found a unit-length block"
    worst = 0.0
    for g in ok:
        w = normals(data, g).astype(np.float64)
        worst = max(worst, float(np.abs(np.sqrt((w * w).sum(1)) - 1.0).max()))
    return True, f"{len(ok)} of {len(done)} groups resolved; worst |n| - 1 = {worst:.2e}"


IDENTITIES = [
    Identity(
        "the indices cover the vertex array exactly",
        "a group's strips use every value 0..N-1 and no other",
        _indices_cover_the_array,
    ),
    Identity(
        "the normals are unit length",
        "the block 16 + N*12 after the positions is N unit vectors",
        _normals_are_unit_length,
    ),
]


# -- finding the tail inside a clump ---------------------------------------------------------

#: RenderWare chunk header: u32 id, u32 size, u32 version
CHUNK = 12
#: the clump chunk id
CLUMP = 0x10
#: below this a tail is not worth reading
MIN_TAIL = 4096


def tail_of(data: bytes) -> int | None:
    """Where a CLUMP's native block starts, or ``None``.

    The walk covers STRUCT and FRAMELIST and then meets bytes that are not a chunk header - on
    the sample a zero-size chunk id 0, then display-list data.  Everything from there to the end
    of the clump is native.

    Native data that sits inside a GEOMETRY chunk belongs to `plugins/renderware.py`, which
    reads it through `rwgc.decode_native_piglet`; see :func:`owned_spans` for how a group in
    one of those is left to it rather than read twice.
    """
    if len(data) < CHUNK:
        return None
    cid, size, _ver = struct.unpack_from("<3I", data, 0)
    if cid != CLUMP or size > len(data) - CHUNK:
        return None
    end = CHUNK + size
    at = CHUNK
    while at + CHUNK <= end:
        kid, ksize, _ = struct.unpack_from("<3I", data, at)
        if ksize == 0 and kid == 0:  # the terminator the native block sits behind
            at += CHUNK
            break
        if ksize > end - at - CHUNK or kid > 0xFFFF:
            break
        at += CHUNK + ksize
    return at if end - at >= MIN_TAIL else None


def owned_spans(data: bytes) -> list[tuple[int, int]]:
    """Byte ranges of every GEOMETRY chunk in the clump - native data `renderware.py` reads.

    The biggest sampled clump holds both: 26 small geometries as GEOMETRY chunks, and a
    154,856-byte STRUCT that is a 4,054-triangle native group with no GEOMETRY around it at
    all.  Declining the whole clump when any GEOMETRY exists lost the second; reading everything
    counted the first twice.  So a group is left to `renderware.py` only when its display lists
    fall inside one of these.
    """
    from gcrip.formats import rwstream

    if len(data) < CHUNK:
        return []
    cid, size, _ = struct.unpack_from("<3I", data, 0)
    if cid != CLUMP or size > len(data) - CHUNK:
        return []
    out = []
    for k in rwstream.chunks(data, CHUNK, CHUNK + size):
        if k.type == rwstream.GEOMETRY:
            out.append((k.off - CHUNK, k.end))
        elif k.type == rwstream.GEOMLIST:
            for g in rwstream.chunks(data, k.off, k.end):
                if g.type == rwstream.GEOMETRY:
                    out.append((g.off - CHUNK, g.end))
    return out
