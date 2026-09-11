"""English character names for Ocarina of Time's object ids.

**These are not read from the ROM.**  This build has no name strings at all: `object_`,
`ovl_En_` and `object_zl` return zero hits across all 33,554,432 bytes, and the `name` pointer
in every `gActorOverlayTable` entry is NULL, because the debug strings are compiled out of a
retail build.  So there is nothing to translate - the names here come from **looking at the
models**, which is the only route available.

That makes this table editable data rather than derived fact, and it is deliberately short:
only entries identified with confidence are listed, because a wrong name is worse than none -
it is trusted, and it is not obviously wrong the way a wrong texture is.  An unlisted object
keeps its numeric id, which is always correct.

To extend it, render the thumbnail sheets (`tools/thumb_sheet.py`) and add what you
recognise.  Object ids are stable across Ocarina of Time's releases, so an entry confirmed
here holds for Master Quest and the other images too.
"""

from __future__ import annotations

#: object id -> English name, lower_snake_case so it is safe in a path.
#: Every entry below was confirmed against the model's own render.
OOT: dict[int, str] = {
    20: "link_adult",        # confirmed: his face table is the one in `code`, 8 eyes / 4 mouths
    21: "link_child",
    29: "zelda_child",       # white and pink royal dress; the blink table is in overlay 446
    36: "skulltula",         # the spider
    135: "gerudo",           # purple guard's outfit, red iris under a white brow
    137: "goron",            # brown, thick-set, the round eyeball texture
    138: "sheik",            # blue wrap, blond, red eyes
    152: "gibdo",            # the bandaged mummy
    163: "ruto",             # Zora with six eye states including a blush - the one who proposes
    202: "zora",             # Zora, three eye states, no blush
    225: "ganondorf",        # dark armour, red hair
    251: "mido",             # Kokiri boy, green cap, hands on hips
    255: "king_zora",        # Zora blue with the red cape; eyes in overlay 353
    339: "deku_scrub",
    356: "deku_scrub",
    357: "poe",              # hooded, carries the lantern
    369: "deku_scrub",
    370: "deku_scrub",
    387: "wolfos",           # the wolf
    395: "cow",
    401: "zelda_child_alt",  # the other child Zelda: purple and white dress; drawn by overlay 449
}


def name_for(object_id: int | None, game: str = "oot") -> str | None:
    """The English name for an object id, or None when it is not one we have identified."""
    if object_id is None:
        return None
    return OOT.get(object_id) if game == "oot" else None
