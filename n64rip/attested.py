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


class RestPose(NamedTuple):
    """The animation whose frame 0 is a skeleton's authored rest pose."""

    bank: int        # object id of the file holding the animation
    offset: int      # the AnimationHeader's offset inside that file
    seen: str


#: ``(skeleton header offset, limb count) -> RestPose``
#:
#: Some models carry no animation at all: the actor loads a second object for them, and which
#: one is not recoverable from the model.  Two routes find it.  Where an actor exists, its
#: ``SkelAnime_Init*`` call passes the skeleton in ``$a2`` and the animation in ``$a3``, so one
#: call site yields one animation for that rig and nothing has to be chosen.  Where no actor
#: names the skeleton at all - the eighteen townsfolk on 0x260 - the bank was found by the
#: shape of its animation data (a ``jointIndices`` block sized for ``limbCount + 1`` triples)
#: and confirmed by the room object lists that load model and bank together.
#:
#: **Selecting among several candidates automatically has never worked here.** Seven measures
#: have each picked a best-scoring wrong answer: bounding volume, the standing gate, a
#: consensus vote across a shared skeleton, "prefer short animations", "prefer the first in the
#: file", compactness, and stands_up-count per rotation order. The gates reject nonsense; they
#: do not select. Every row below was chosen by rendering it and looking, and ``seen`` records
#: what was on screen.
#:
#: Keyed on the skeleton, not the object, because that is what the models share - one key here
#: poses eighteen of them.
REST_POSES: dict[tuple[int, int], RestPose] = {
    (0xf0, 15): RestPose(
        197, 0x7d0,
        "the Hylian townsfolk idle: all eleven models on this skeleton stand upright with their "
        "arms at their sides - villagers, women in dresses, the running man",
    ),
    (0x110, 17): RestPose(
        201, 0x21d0,
        "a gold-and-olive Goron standing on both feet, arms hanging at its sides, shoulders "
        "hunched forward. Its rig is the only 17-limb skeleton in the ROM whose tree and whose "
        "limb translations both match object 201's, whose bank this is. WEAKEST ROW HERE: object "
        "201's actor loads its animations from a table rather than naming one next to the "
        "skeleton, so the choice among its ten was made BY EYE - 0x161c and 0x4930 are the curled "
        "rolling ball, five others raise or extend an arm, and 0xd5c and 0x21d0 both stand, "
        "0x21d0 being the more upright and symmetric",
    ),
    (0x260, 38): RestPose(
        41, 0x1300,
        "the Hyrule Castle Town / Kakariko townsfolk idle: sixteen of the eighteen models on this "
        "rig stand upright and symmetric, arms hanging straight down with the hands at the hips, "
        "feet together and flat - the Kokiri children in white or green caps with green boots "
        "(51, 53, 75, 76), the men in sashed shirts and pointed shoes (35, 60, 62, 63), the big "
        "bare-armed man in green trousers (40), the woman in the long lavender gown (61), the "
        "woman in the tiered pink-and-green dress (67), the stout figure in the orange top over a "
        "dark patterned skirt (68), the figure in the wide apron (69), the hooded robed figure "
        "whose two cape flaps hang down the body here (46), and the Hylian guard (87), who "
        "carries his spear HORIZONTALLY across his hips - no animation in bank 41 or 52 stands it "
        "upright at his side. Chosen by rendering against its rivals in the same bank: 41@0x17b4 "
        "holds the arms out clear of the torso and spreads 46's cape sideways, and 41@0x18f0 is a "
        "walk frame with one leg forward and the rear foot off the ground. Two of the eighteen "
        "are posed but not legible characters under any animation in either bank: 88 is object "
        "87's torso with 8 of its 15 limbs pointing at object 87's dlists past its own end of "
        "file (no legs, no head), and 65 is an untextured blocky column with a blade through it.",
    ),
    (0x10c0, 8): RestPose(
        8, 0xf0,
        "an orange cone-shaped body with a dark purple wing out to each side and a tail behind (a "
        "Keese); un-posed it is a flat sliver. The wings sit high in a V, which reads as a "
        "mid-flap frame rather than a rest - but 0xF0 is the object's only animation, so this is "
        "the best available pose, not a demonstrated rest pose",
    ),
    (0x1c80, 23): RestPose(
        24, 0x9c4,
        "an orange-red bulb with a flat ring of long blades radiating evenly around its base, "
        "Peahat-shaped and symmetric from every view; un-posed the same blades all point one way "
        "in a spray. Overlay 383's $a3, and every Animation_Change in that overlay names the same "
        "offset",
    ),
    (0x20e0, 14): RestPose(
        31, 0x9d4,
        "a compact pale-green creature with a pointed snout and a dark eye socket with a magenta "
        "pupil. WEAK: this model was never a heap - all five of its animations and the un-posed "
        "rig render as the same flat wedge, so the row records the actor's own choice rather than "
        "a repair. Overlay 279's $a3",
    ),
    (0x21f8, 15): RestPose(
        197, 0x7d0,
        "a standing robed NPC - long white skirt with two purple bands, a blue-green tunic, hands "
        "together in front, a tan headdress, the face reading correctly from all four sides. "
        "Un-posed it is a spray of blue and white shards. WEAKER PROVENANCE: no overlay in the "
        "ROM initialises skeleton 0x21f8 and this object has no animation of its own, so the bank "
        "is the attested Hylian idle borrowed on an exact match - the limb tree AND all 15 limb "
        "translations are byte-identical to objects 261 and 277 on skeleton 0xf0 - and the only "
        "confirmation is the render",
    ),
    (0x2530, 15): RestPose(
        19, 0xe8,
        "a Cucco: white body, red comb and wattle, yellow beak, both yellow feet under it, tail "
        "feathers behind, correct from front, side and back. Un-posed it is a white blob with a "
        "detached cloud of feather vertices floating above it. The object's only animation, named "
        "by all three of its actors (overlays 243, 370, 414) - and rejected by BOTH gates, "
        "because posing the bird makes it shorter in Y",
    ),
    (0x2a40, 7): RestPose(
        57, 0x2b8,
        "a faceted blue-and-magenta shell with green frond-like fins; posed it is rounder and the "
        "fins fold toward the body, un-posed they splay outward. WEAK: both builds are coherent, "
        "so this is an improvement in arrangement rather than a rescue. Named by both of its "
        "actors (overlays 270 and 350)",
    ),
    (0x4010, 5): RestPose(
        395, 0x1cc,
        "a white cow with yellow horns, a yellow nose ring and dark hooves standing on four legs. "
        "This rig's authored rest IS the zero pose: frame 0 of the animation its actor names has "
        "all five rotation triples exactly zero, so the posed and un-posed builds are "
        "byte-identical and this row only flips the `posed` flag. Written down so the next reader "
        "does not go looking for a pose that does not exist",
    ),
    (0x4f70, 15): RestPose(
        386, 0x3f4,
        "a crowd, not one character: about eight small standing figures in white outfits with "
        "arms, legs and differently coloured hair - blond, orange, red, brown - shoulder to "
        "shoulder, two with an arm raised. Un-posed the whole file is shredded confetti. The two "
        "limb clusters sit ~6200 units apart, so this reads as a heap below ~300px; it only "
        "resolves at 400px. Overlay 368's $a3",
    ),
    (0x6bc0, 19): RestPose(
        351, 0x14b8,
        "a lumpy pale-green rocky body sitting on a magenta base whose flat plates spread out "
        "into an even skirt; un-posed the same plates sit stacked at angles. WEAK, same as object "
        "57: neither build is garbage. Overlay 247's $a3",
    ),
    (0x8318, 30): RestPose(
        12, 0x4c20,
        "a four-legged green lizard at rest - spiny back ridge running out to a tail held behind, "
        "four legs under the body, a red mouth line at the front (a Dodongo). Un-posed the file "
        "is a flat fan of green shards. Overlay 280's SkelAnime_Init $a3",
    ),
    (0xae40, 20): RestPose(
        386, 0x5040,
        "the woman in the long teal-and-white dress with a purple hem stands upright, arms in "
        "front of her, head on her shoulders and hair behind. The rip currently gives this "
        "skeleton 386@0x3f4 - the CROWD animation belonging to the other skeleton in the same "
        "file, which is first in the file and fires the standing gate - and it leaves her head "
        "detached beside the body with one arm flung straight up. Named by overlay file 418 "
        "@0x190",
    ),
    (0x10d70, 14): RestPose(
        335, 0x499c,
        "adult Zelda standing, hands clasped in front of her",
    ),
    (0x14190, 27): RestPose(
        48, 0xebe4,
        "a Moblin standing square on both feet, arms out, its club resting on the ground in front "
        "of it. The animation the rip currently picks (48@0x6a4) has it leaning with the club "
        "hoisted overhead. Note this offset is WRONG on object 48's OTHER skeleton (head merged "
        "into the torso, spear flung diagonally) - that one is key (0x8f38, 27) and must stay "
        "untouched",
    ),
    (0x1e178, 29): RestPose(
        262, 0x203d8,
        "an Iron Knuckle standing upright, legs together, its long-handled axe held vertically at "
        "its side. The animation the rip currently picks (262@0x35c) is shredded scatter with no "
        "body in it - one of five headers in this file that overlay 338 never names and that "
        "belong to no rig here",
    ),
    (0x205c0, 29): RestPose(
        262, 0x203d8,
        "the second 29-limb header in the same file drives identical geometry (both 668 "
        "triangles, cell-for-cell identical renders) - the same standing knight with the axe "
        "vertical. The code names 262@0xc114 for this one, but that is 215 frames of the "
        "throne/rise cutscene and its frame 0 is a hunched crouch",
    ),
}


def rest_pose(skeleton_offset: int, limb_count: int) -> RestPose | None:
    """The attested rest pose for a skeleton, or None."""
    return REST_POSES.get((skeleton_offset, limb_count))
