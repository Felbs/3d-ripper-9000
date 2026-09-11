"""The object table: which files are actor objects, and which is ``gameplay_keep``.

The ROM has no filename table, so a file's *purpose* has to come from structure.  The game's
own object table gives it: an array of ``{vromStart, vromEnd}`` pairs in ``code``, one per
object id, each pair naming a real DMA entry.  That last part is what makes it findable
without any outside data - the table validates against the file table we already read, so a
run of pairs that all match cannot be coincidence.

Two things fall out of it:

* **Which files are objects** (actors, props, characters) rather than scenes, rooms, code
  overlays or audio.  On Ocarina of Time, 211 distinct files across 227 object slots.
* **``gameplay_keep`` is object 1** - the shared asset bank actors reach through segment 4.
  Binding it turns Link's missing textures from 7 to 2; leaving it unbound is why characters
  that borrow from it came out part-textured.

Object 2 and 3 are the field and dungeon keeps, reached through segment 5.  Neither changed
anything measurable on the actors tested, so they are bound only when asked for.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: object ids with a fixed meaning, confirmed against this ROM rather than assumed
GAMEPLAY_KEEP = 1
FIELD_KEEP = 2
DUNGEON_KEEP = 3
MIN_TABLE = 24  # a run this long of pairs that all name real files is not chance
MAX_EMPTY_RUN = 8  # consecutive {0, 0} slots before the walk decides it has left the table


@dataclass(frozen=True)
class ObjectTable:
    offset: int  # byte offset within the file that holds it
    file_index: int  # which ROM file that is (``code``)
    entries: list[int | None]  # object id -> ROM file index, None for empty slots

    def file_for(self, object_id: int) -> int | None:
        if 0 <= object_id < len(self.entries):
            return self.entries[object_id]
        return None

    @property
    def object_files(self) -> set[int]:
        return {e for e in self.entries if e is not None}


def find_object_table(rom) -> ObjectTable | None:
    """Locate the object table by validating every entry against the DMA table.

    Scans the plausible code-sized files for the longest run of ``{vromStart, vromEnd}``
    pairs where each pair is either a real file or an empty ``{0, 0}`` slot, then walks out
    from that run in both directions to pick up the empty slots at either end.
    """
    pairs = {(f.vrom_start, f.vrom_end): f.index for f in rom.files if f.vrom_start > 0x10000}
    best: tuple[int, int, int] | None = None
    for f in rom.live:
        if not (100_000 < f.size < 3_000_000):
            continue
        try:
            data = rom.read(f)
        except Exception:  # noqa: BLE001 - a file we cannot read is simply not the table
            continue
        n = len(data) // 4
        if n < 4:
            continue
        words = struct.unpack_from(f">{n}I", data, 0)

        def ok(i: int) -> bool:
            if i + 1 >= n:
                return False
            p = (words[i], words[i + 1])
            return p in pairs or p == (0, 0)

        i = 0
        while i < n - 1:
            # only real entries seed a run; a field of zeroes would otherwise win
            if (words[i], words[i + 1]) in pairs:
                j, k = i, 0
                while ok(j):
                    k += 1
                    j += 2
                if k >= MIN_TABLE and (best is None or k > best[0]):
                    best = (k, f.index, i)
                i = j
            else:
                i += 1
    if best is None:
        return None

    _, file_index, seed = best
    data = rom.read(rom.files[file_index])
    n = len(data) // 4
    words = struct.unpack_from(f">{n}I", data, 0)

    def ok(i: int) -> bool:
        if i + 1 >= n:
            return False
        p = (words[i], words[i + 1])
        return p in pairs or p == (0, 0)

    # Empty {0, 0} slots are real entries - object 0 is one - but a zero-padded region
    # would otherwise extend the table forever, so a long run of them ends the walk.
    def furthest_real(step: int) -> int:
        pos, last_real, empties = seed, seed, 0
        while 0 <= pos and ok(pos):
            if (words[pos], words[pos + 1]) == (0, 0):
                empties += 1
                if empties > MAX_EMPTY_RUN:
                    break
            else:
                empties = 0
                last_real = pos
            pos += step
        return last_real

    lo = furthest_real(-2)
    hi = furthest_real(2) + 2
    # keep the empty slots immediately before the first real one: object 0 is {0, 0}, and
    # dropping it shifts every object id by one - which silently renamed gameplay_keep.
    back = 0
    while lo - 2 >= 0 and (words[lo - 2], words[lo - 1]) == (0, 0) and back < MAX_EMPTY_RUN:
        lo -= 2
        back += 1
    entries = [pairs.get((words[lo + 2 * j], words[lo + 2 * j + 1])) for j in range((hi - lo) // 2)]
    return ObjectTable(offset=lo * 4, file_index=file_index, entries=entries)


def keep_segments(rom, table: ObjectTable | None, *, field: bool = False, dungeon: bool = False):
    """The shared banks to bind, as ``{segment: bytes}``.

    Segment 4 is ``gameplay_keep`` and is always worth binding.  The field and dungeon keeps
    sit on segment 5 and are opt-in: on the actors measured they changed nothing, and binding
    the wrong bank would decode unrelated bytes as textures.
    """
    out: dict[int, bytes] = {}
    if table is None:
        return out
    keep = table.file_for(GAMEPLAY_KEEP)
    if keep is not None:
        try:
            out[4] = rom.read(rom.files[keep])
        except Exception:  # noqa: BLE001
            pass
    other = FIELD_KEEP if field else (DUNGEON_KEEP if dungeon else None)
    if other is not None:
        idx = table.file_for(other)
        if idx is not None:
            try:
                out[5] = rom.read(rom.files[idx])
            except Exception:  # noqa: BLE001
                pass
    return out
