"""Static props: the geometry in object files that hang on no skeleton.

Chests, doors, signs, pots, bombable rocks, tents, the drawbridge - the furniture of the world.
230 of Ocarina's 380 object files have no skeleton and 8 more return one that is not real, so
the skeleton route exports nothing for ~211 files, and 161 of the 282 object ids that rooms
actually ask for are among them.  Without this route a room is a shell full of empties.

There is no index of these display lists, so candidates are generated three ways and then
**gated**, and the gate is what makes this a rip rather than a guess:

* candidates: every stored ``0x0S XXXXXX`` word (``S`` the file's own segment) that lands on an
  8-byte boundary, and every start :mod:`n64rip.scan` accepts (a run of defined opcodes that
  reaches ``G_ENDDL`` and draws);
* the gate: run it with only the file's own segment (plus the keep banks) bound, and keep it
  only if it draws, **every** ``G_VTX`` resolved, and every vertex load came from the file's
  own segment.  Over all 2,368 limb display lists of every skeleton in the ROM, 2,326 draw and
  100.00% of them load vertices from segment 6 exclusively; on non-exporting files only 20% of
  random starts resolve every load and 8.7% load from segment 6 alone.  The gate is decisive.

Then the survivors are reduced to **roots** by the transitive ``G_DL`` call graph - a list
another kept list calls is drawn as part of it - except that a candidate that came from a
*stored pointer* is never pruned as interior: eleven real limb lists in the ROM lie strictly
inside another list's byte span.  Finally identical geometry (a hash over rounded positions
and indices) is emitted once.

The keep banks are the exception to "segment 6": ``gameplay_keep`` is object 1 and lives on
segment 4, the field and dungeon keeps on segment 5.  Bound at 6 they yield 0 display lists.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

import numpy as np

from n64rip import f3dex2, scan
from n64rip import objects as obj_mod
from n64rip import zobj
from ripcore.scene import Scene

#: object id -> the segment its file is bound at when the game draws it
HOME_SEGMENT = {obj_mod.GAMEPLAY_KEEP: 4, obj_mod.FIELD_KEEP: 5, obj_mod.DUNGEON_KEEP: 5}
MAX_CANDIDATES = 4096
#: commands whose second word is a segmented pointer
OPERAND_OPS = frozenset({f3dex2.G_DL, f3dex2.G_VTX, f3dex2.G_SETTIMG, f3dex2.G_MTX, 0xDC})


@dataclass
class Root:
    offset: int
    from_pointer: bool
    triangles: int
    result: f3dex2.Result


def home_segment(object_id: int | None) -> int:
    return HOME_SEGMENT.get(object_id, 6) if object_id is not None else 6


def candidates(data: bytes, segment: int) -> dict[int, bool]:
    """``{offset: came from a stored pointer}`` for every plausible display-list start."""
    out: dict[int, bool] = {}
    n = len(data) - 4
    for off in range(0, n, 4):
        w = struct.unpack_from(">I", data, off)[0]
        if w >> 24 == segment:
            target = w & 0x00FFFFFF
            if target % 8 != 0 or target + 8 > len(data):
                continue
            # The second word of a G_DL, G_VTX, G_SETTIMG, G_MTX or G_MOVEMEM is a pointer
            # too, and it is a CALL or a data reference, not the game naming a list.  A
            # G_DL operand in particular is exactly the interior case the root reduction
            # exists to prune, so it must not count as "stored pointer".
            operand = off % 8 == 4 and data[off - 4] in OPERAND_OPS
            if operand:
                out.setdefault(target, False)
            else:
                out[target] = True
    # Everything else comes from the scan, which accepts a start only if every opcode up to
    # G_ENDDL is one the microcode defines.  A bare "head after every G_ENDDL" or "offset 0"
    # candidate is NOT used: a run of zero words is a run of G_NOOPs, and the interpreter
    # happily walks it into the next real list and draws that list's geometry as its own.
    for found in scan.display_lists(data):
        out.setdefault(found.offset, False)
    # A G_VTX command's own operand is a stored segment word, so vertex DATA arrives here as
    # a candidate; read as commands its bytes are G_NOOPs (opcode 0x00), which the interpreter
    # walks straight through into whatever real list follows and then claims that list's
    # geometry.  No real display list in this game begins with a no-op.
    return {off: ptr for off, ptr in out.items() if off + 8 <= len(data) and data[off] != 0}


def _passes(res: f3dex2.Result, segment: int) -> bool:
    tris = sum(len(b.indices) // 3 for b in res.batches)
    if tris == 0:
        return False
    # The gate is about VERTEX loads only.  A texture on a runtime segment (8-0xD) or a
    # G_DL into one is how many real props are drawn, and rejecting the list for it threw
    # away a third of the geometry - file 767's slab and file 503 came out empty.
    loads = res.vtx_segments
    return bool(loads) and set(loads) == {segment}


def roots(data: bytes, segments: f3dex2.Segments, segment: int) -> list[Root]:
    """The gated, root-reduced, deduplicated display lists of one file."""
    cands = candidates(data, segment)
    if len(cands) > MAX_CANDIDATES:
        # keep stored pointers first, then the earliest structural heads
        keep = {o: p for o, p in cands.items() if p}
        for o in sorted(o for o, p in cands.items() if not p):
            if len(keep) >= MAX_CANDIDATES:
                break
            keep[o] = False
        cands = keep
    kept: dict[int, Root] = {}
    for off, from_ptr in cands.items():
        try:
            res = f3dex2.run((segment << 24) | off, segments)
        except Exception:  # noqa: BLE001 - a bad start is not a display list
            continue
        if not _passes(res, segment):
            continue
        kept[off] = Root(off, from_ptr, sum(len(b.indices) // 3 for b in res.batches), res)
    # interior lists: called by another kept list.  Only scan-derived ones are pruned.
    called: set[int] = set()
    for r in kept.values():
        for target in r.result.calls_to:
            if target >> 24 == segment:
                called.add(target & 0x00FFFFFF)
    out = [r for off, r in kept.items() if r.from_pointer or off not in called]
    # identical geometry once
    seen: set[str] = set()
    uniq: list[Root] = []
    # a stored pointer is the game's own name for a list; when a scan start draws the same
    # geometry, the pointer's copy is the one kept
    for r in sorted(out, key=lambda r: (not r.from_pointer, r.offset)):
        h = hashlib.sha1()
        for b in r.result.batches:
            h.update(np.round(b.positions, 1).astype(np.float32).tobytes())
            h.update(b.indices.astype(np.uint32).tobytes())
        key = h.hexdigest()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def build(name: str, data: bytes, segments: f3dex2.Segments, segment: int,
          found: list[Root] | None = None) -> tuple[Scene, list[Root]]:
    """One Scene holding every root as its own node, in the object's own space."""
    scene = Scene(name=name)
    rs = found if found is not None else roots(data, segments, segment)
    missing = 0
    for r in rs:
        missing += zobj.assemble(scene, r.result.batches, segments,
                                 group=f"dl_{r.offset:06x}", prefix=f"dl{r.offset:06x}_",
                                 skinned=False)
    scene.extras = {
        "format": "n64_static",
        "segment": segment,
        "roots": [{"offset": r.offset, "from_pointer": r.from_pointer, "triangles": r.triangles}
                  for r in rs],
        "materials": len(scene.materials),
        "textures": len(scene.textures),
        "textures_missing": missing,
    }
    return scene, rs
