"""Face tables that were established by hand, because no rule finds them.

Every other route in this package is a rule: read the actor's pointer array, or seed a walk at
the palette the head names.  Those cover most of the cast.  A handful of actors are covered by
neither - their table is not in an overlay, and it does not begin where the palette ends - and
for those the offsets were found by decoding windows of the object file and **looking at
them**.

That is deliberately data rather than code.  The intruding frames in these files are real
artwork, not noise: on object 357 the wrong frames measure *smoother* than several correct
ones, so no threshold separates them, and every attempt to generalise a rule from these cases
either missed them or dragged junk onto characters that were already right.  A short attested
table is honest about that; another heuristic would not be.

Each row records what was seen, so a later reader can check it rather than trust it.  Object
ids are stable across Ocarina of Time's releases, so these hold for Master Quest too - but
they are **offsets into a specific object file**, so they must be re-checked against any other
game before being reused.
"""

from __future__ import annotations

from typing import NamedTuple


class Table(NamedTuple):
    """One expression table: where it is, how to read it, and what it looks like."""

    offsets: tuple[int, ...]
    fmt: int      # texture.FMT_*
    size: int     # texture.SIZE_*
    width: int
    height: int
    tlut: int | None   # offset of the palette in the same file, None for true-colour
    seen: str


#: object id -> {"eyes"|"mouths": Table}
OOT: dict[int, dict[str, Table]] = {
    75: {
        "eyes": Table(
            (0x5120, 0x5520, 0x5920), 2, 1, 32, 32, 0x4F20,
            "blue eye under a brown brow: open / closed / half-open looking sideways",
        ),
        "mouths": Table(
            (0x5F60, 0x6360), 2, 1, 32, 16, 0x5D20,
            "a closed lip line; a dark open mouth",
        ),
    },
    29: {
        # Her eyes come from the code route (the array her Update indexes).  These mouths are
        # in her object on the same 0x400 grid as the eyes but only one of them is in that
        # array - the others are reached by states this actor does not own.  The user wants
        # every expression, and these are unmistakably hers.
        "mouths": Table(
            (0x7608, 0x9048, 0xA448), 2, 1, 32, 32, 0x6ED0,
            "a closed lip line; a small closed smile; a wide open shout with the tongue",
        ),
    },
    155: {
        "eyes": Table(
            (0xF178, 0xF378, 0xF578, 0xF778), 2, 1, 32, 16, 0xECB8,
            "olive skin, gold iris: open / a white sliver / fully closed / open again",
        )
    },
    261: {
        "eyes": Table(
            (0xB08, 0x1308, 0x1608), 0, 2, 32, 32, None,
            "purple iris under a heavy black brow on pale skin: open / half / closed",
        )
    },
    277: {
        "eyes": Table(
            (0xB08, 0x1308, 0x1608), 0, 2, 32, 32, None,
            "as object 261 but on yellower skin: open / half / closed",
        )
    },
    357: {
        "eyes": Table(
            (0x3928, 0x3D28, 0x4128), 2, 1, 32, 32, 0x2EE8,
            "a bandaged face: open with a white highlight / half / closed",
        )
    },
    195: {
        "eyes": Table(
            (0x478, 0x15F8, 0x1C78), 2, 1, 32, 32, 0x1A8,
            "blue eye under a brown brow on yellow skin: open / half / closed",
        )
    },
}

#: Why each of these needed attesting, kept so the next person does not redo the search.
NOTES = {
    29: "the code names one mouth; the other two exist on her grid but no state of this actor binds them",
    195: "the palette-seeded walk starts 0xD0 short of the table; its frame 0 is byte-identical to object 51's",
    75: "its pointer run lists the closed eye first, and two of its mouth entries are not mouths",
    155: "the palette-seeded walk starts at 0xEEB8, 0x2C0 short of the table",
    261: "its face is RGBA16 and needs no palette, so the seed had no anchor at all",
    277: "same as 261",
    357: "two frames of bandage texture sit between the palette and the eyes",
}


def for_object(object_id: int | None, game: str = "oot") -> dict[str, Table]:
    """The attested tables for an object, or an empty dict when there are none."""
    if object_id is None or game != "oot":
        return {}
    return OOT.get(object_id, {})
