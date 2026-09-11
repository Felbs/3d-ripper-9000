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

The oracle that found most of these: walk the object file's own display lists, list every
segment-6 tile load with its byte length, and print the **gaps**.  A face frame block fills a
gap exactly, and the gap is a whole number of face tiles - so three 32x32 RGBA16 frames are a
0x1800 hole between two statics and nothing else fits it.  That turns "which window looks most
like an eye" into arithmetic, and it caught rows that had been copied between objects (277 had
261's offsets) and rows sitting 0x40 inside a static (345, 357).  It does not apply everywhere:
object 208's statics all end at one address and everything after is one free tail, so its row
still rests on the look.

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
    29: {
        "mouths": Table(
            (0x7608, 0x9048, 0xa448), 2, 1, 32, 32, 0x6ed0,
            "a closed lip line; a small closed smile; a wide open shout with the tongue",
        ),
    },
    75: {
        "eyes": Table(
            (0x5120, 0x5520, 0x5920), 2, 1, 32, 32, 0x4f20,
            "blue eye under a brown brow: open / closed / half-open looking sideways",
        ),
        "mouths": Table(
            (0x5f60, 0x6360), 2, 1, 32, 16, 0x5d20,
            "a closed lip line; a dark open mouth",
        ),
    },
    155: {
        "eyes": Table(
            (0xf178, 0xf378, 0xf578, 0xf778), 2, 1, 32, 16, 0xecb8,
            "olive skin, gold iris: open / a white sliver / fully closed / open again",
        ),
    },
    163: {
        "mouths": Table(
            (0xe838, 0xfa38, 0x10638), 2, 1, 32, 32, 0xe238,
            "her neutral closed mouth - a brown upper-lip arch over a pale blue lower lip "
            "/ a thinner closed arch / the open mouth with the pink tongue. 0xE838 sits in "
            "its own exact 0x400 gap and only decodes as a mouth through the MOUTH palette "
            "0xE238; through the eye palette 0xE038 it is speckled nonsense, which is why "
            "the walk missed it",
        ),
    },
    179: {
        "eyes": Table(
            (0xb428, 0xd0e8, 0xd4e8, 0xd8e8), 2, 1, 32, 32, 0xb048,
            "gold eye under a red brow: open / half / closed / and a fourth, rounder fully "
            "open eye with a clear dark iris that was left unused in the same 0xC00 gap",
        ),
    },
    188: {
        "mouths": Table(
            (0x3348, 0x3588, 0x4448, 0x4648, 0x4c48), 2, 1, 32, 16, 0x2cf8,
            "closed lips / closed lips slightly parted / open with a pink tongue / a "
            "smiling arch / open with a white tooth row and tongue. The rip shipped only "
            "the second and third of the five. 0x4048 and 0x5248 are blue-and-cream "
            "palette speckle and stay out; the five shipped eyes are all real eyes",
        ),
    },
    195: {
        "eyes": Table(
            (0x478, 0x15f8, 0x1c78), 2, 1, 32, 32, 0x1a8,
            "blue eye under a brown brow on yellow skin: open / half / closed",
        ),
    },
    208: {
        "mouths": Table(
            (0x2970, 0x3570, 0x3770), 2, 1, 32, 16, 0x1f70,
            "a closed red lip line with a highlight bar / a closed smile / a wide open "
            "black mouth filled with a pink tongue. The third was dropped. The 0x100 "
            "blocks at 0x2B70 and 0x3470 are half palette, half mouth - a half-frame "
            "offset - and stay out. NOTE the tile-map oracle does not apply to this "
            "object: its statics all end at 0x2570 and everything after is one free tail, "
            "so this row rests on the look",
        ),
    },
    253: {
        "eyes": Table(
            (0x1a0c, 0x1e0c), 2, 1, 32, 32, 0xd3c,
            "an open blue eye under a brown brow / the closed lid as one curved lash. Only "
            "two expressions: 0x220C is noise. The old row (0x173C, 0x1B3C) started inside "
            "the static 32x32 at 0x160C - frame 0 was a bare patch of cheek and frame 1 an "
            "eye jammed into the corner with a brow across the bottom",
        ),
    },
    255: {
        "eyes": Table(
            (0x1470, 0x1870, 0x1c70, 0x2070), 2, 1, 32, 32, 0x970,
            "purple eye on blue skin: open / half / closed / and a fourth, narrower eye "
            "with the upper lid drawn down, unused in the same 0x1000 gap",
        ),
    },
    261: {
        "eyes": Table(
            (0x5c8, 0xdc8, 0x15c8), 0, 2, 32, 32, None,
            "brow above a full open purple eye with three lashes, on pale skin: open / "
            "half-lidded / closed lid. The old row (0xB08, 0x1308, 0x1608) was 0x540 late: "
            "the eye was clipped off the top of the frame, a stray brow floated in the "
            "lower half, and frame 3 ended in a green-and-magenta palette strip - and its "
            "strides were 0x800 then 0x300, so it could never have been three equal "
            "frames. Found by the file's own tile map: the statics end at 0x5C8 and the "
            "next begins at 0x1DC8, a gap of exactly three 32x32 RGBA16 frames",
        ),
    },
    263: {
        "eyes": Table(
            (0x57c, 0x67c, 0x77c), 2, 1, 16, 16, 0xfc,
            "a dark eye with a pink inner corner under a cream brow, then two closing "
            "lids. The old row (0x4FC, 0x5FC, 0x6FC, 0x7FC) began on an 8x8 static: frame "
            "0 was two brown rectangles and frame 3 was cream over vertical "
            "brown-and-white palette stripes. Gap 0x57C..0x87C is exactly three 16x16 CI8 "
            "frames",
        ),
    },
    268: {
        "eyes": Table(
            (0x5fc, 0x9fc, 0xdfc), 2, 1, 32, 32, 0xfc,
            "a wide open eye - white sclera, black iris - in a deeply wrinkled socket / "
            "half shut with a white sliver / a closed black lash line. The old row (0x6FC, "
            "0xAFC, 0xEFC) was 0x100 late and contained no eye at all: three yellow blurs "
            "of wrinkled skin, the last ending in a checkered noise band. Gap "
            "0x5FC..0x11FC = three frames",
        ),
    },
    277: {
        "eyes": Table(
            (0x7c8, 0xfc8, 0x17c8), 0, 2, 32, 32, None,
            "as object 261 but on yellower skin: open / half / closed. The old row gave "
            "277 the SAME offsets as 261 - it was copied, not measured, and 277's statics "
            "end 0x200 further on. Statics end at 0x7C8, next static at 0x1FC8, gap = "
            "0x1800 = three frames",
        ),
    },
    307: {
        "eyes": Table(
            (0x6320, 0x5f20), 2, 1, 32, 32, 0x4e60,
            "a heavy brown brow with the eye open beneath it, pink sclera and a black "
            "pupil / the same brow over the eye closed as a soft caret. The OPEN frame is "
            "listed first because the model ships wearing frame 0; in the file the closed "
            "frame comes first, at 0x5F20. The rip found his mouths and shipped no eyes at "
            "all; the gap 0x5F20..0x6B20 is 0xC00 = these two 32x32 eyes plus the two "
            "32x16 mouths already found, and only the palette 0x4E60 decodes them - "
            "through 0x4C60 they are confetti",
        ),
    },
    316: {
        "mouths": Table(
            (0xc30, 0xe30), 2, 1, 32, 16, 0x730,
            "a closed brown lip line with a highlight / a wide open mouth, dark red inside "
            "with four white teeth across the top. The rip shipped these as face_eye_0/1 "
            "and in reverse order, so the carpenter ships wearing the open toothy mouth",
        ),
    },
    318: {
        "eyes": Table(
            (0x35d8, 0x39d8), 2, 1, 32, 32, 0x3018,
            "his two closed smiling brows (the expression he ships wearing, and that is "
            "correct for this character) / the angry open eye with a pink sclera. The old "
            "row was 0x40 late, which ruled a band of orange and brown palette blocks "
            "across the bottom of the open-eye frame",
        ),
    },
    345: {
        "eyes": Table(
            (0x30d8, 0x34d8, 0x38d8), 2, 1, 32, 32, 0x2a98,
            "brown brow over an open blue eye on orange skin / half / closed. The old row "
            "was 0x40 early - inside the static at 0x2ED8 - which put ink on row 0 of "
            "frame 0 with a one-row seam under it (the static ending) and cut the lower "
            "lash off the bottom. Gap 0x30D8..0x3CD8 = three frames; the new frames sit "
            "rows 3..27",
        ),
    },
    357: {
        "eyes": Table(
            (0x3968, 0x3d68, 0x4168), 2, 1, 32, 32, 0x2ee8,
            "a bandaged face: open with a white highlight / half / closed. CORRECTED 0x40: "
            "the previous row (0x3928, ...) started inside the 0x800 static at 0x3168 and "
            "every one of its three frames had the bandage ring cut by the BOTTOM edge "
            "(ink to row 31 of 32); the new frames sit rows 3..29, clear of both edges. A "
            "two-row shift that is invisible side by side - the tile map and the ink "
            "margin are the evidence, not the eye",
        ),
    },
}

#: Why each of these needed attesting, kept so the next person does not redo the search.
#: Objects whose attested table is the WHOLE face, not a half to be merged.  Object 316's
#: head samples exactly one face segment, so :func:`extract._face_roles` calls it the eyes and
#: the palette-seeded route hands back the same two offsets under that name.  Without this the
#: carpenter ships the mouth twice - once mislabelled as his eyes, once bound to segment 9,
#: which he never samples.
EXCLUSIVE: set[int] = {316}


NOTES = {
    29:
        "the code names one mouth; the other two exist on her grid but no state of this actor binds them",
    75:
        "its pointer run lists the closed eye first, and two of its mouth entries are not mouths",
    155: "the palette-seeded walk starts at 0xEEB8, 0x2C0 short of the table",
    163:
        "her third mouth decodes only through the MOUTH palette at 0xE238; through the eye palette the walk sees nonsense and stops",
    179:
        "a fourth, unused eye sits in the same gap, so the walk's stride test cuts the run early",
    188:
        "the walk shipped two of her five mouths; the other three sit past two blocks of palette speckle",
    195:
        "the palette-seeded walk starts 0xD0 short of the table; its frame 0 is byte-identical to object 51's",
    208:
        "the 0x100 blocks between its mouths are half palette and half mouth, a half-frame offset the walk cannot step over",
    253:
        "the walk starts inside the static 32x32 at 0x160C, so frame 0 is bare cheek; only two of its three candidate frames are real",
    255: "a fourth, unused eye sits in the same gap, as on 179",
    261:
        "its face is RGBA16 and needs no palette, so the seed had no anchor at all; and the row it replaced was 0x540 late, with strides of 0x800 then 0x300 that could never be three equal frames",
    263:
        "the walk starts on the 8x8 static at 0x4FC, so frame 0 is two brown rectangles and the last frame is palette stripes",
    268:
        "the walk lands 0x100 late and finds three blurs of wrinkled skin with no eye in any of them",
    277:
        "same as 261, and its old row was 261's offsets copied rather than measured - its statics end 0x200 further on",
    307:
        "the closed eye comes first in the file, and the frames only decode through the 0x4E60 palette - through 0x4C60 they are confetti, which is why the walk found no eyes at all",
    316:
        "its head samples ONE face segment, so the role test calls its mouths eyes; see EXCLUSIVE",
    318:
        "the walk lands 0x40 late, which rules a band of palette blocks across the bottom of the open eye",
    345:
        "the walk lands 0x40 early, inside the static at 0x2ED8, which cuts the lower lash off the frame",
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
        "the Hylian townsfolk idle: all eleven models on this skeleton stand upright with "
        "their arms at their sides - villagers, women in dresses, the running man",
    ),
    (0x110, 17): RestPose(
        201, 0x21d0,
        "a gold-and-olive Goron standing on both feet, arms hanging at its sides, shoulders "
        "hunched forward. Its rig is the only 17-limb skeleton in the ROM whose tree and whose "
        "limb translations both match object 201's, whose bank this is. WEAKEST ROW HERE: "
        "object 201's actor loads its animations from a table rather than naming one next to "
        "the skeleton, so the choice among its ten was made BY EYE - 0x161c and 0x4930 are the "
        "curled rolling ball, five others raise or extend an arm, and 0xd5c and 0x21d0 both "
        "stand, 0x21d0 being the more upright and symmetric",
    ),
    (0x260, 38): RestPose(
        41, 0x1300,
        "the Hyrule Castle Town / Kakariko townsfolk idle: sixteen of the eighteen models on "
        "this rig stand upright and symmetric, arms hanging straight down with the hands at "
        "the hips, feet together and flat - the Kokiri children in white or green caps with "
        "green boots (51, 53, 75, 76), the men in sashed shirts and pointed shoes (35, 60, 62, "
        "63), the big bare-armed man in green trousers (40), the woman in the long lavender "
        "gown (61), the woman in the tiered pink-and-green dress (67), the stout figure in the "
        "orange top over a dark patterned skirt (68), the figure in the wide apron (69), the "
        "hooded robed figure whose two cape flaps hang down the body here (46), and the Hylian "
        "guard (87), who carries his spear HORIZONTALLY across his hips - no animation in bank "
        "41 or 52 stands it upright at his side. Chosen by rendering against its rivals in the "
        "same bank: 41@0x17b4 holds the arms out clear of the torso and spreads 46's cape "
        "sideways, and 41@0x18f0 is a walk frame with one leg forward and the rear foot off "
        "the ground. Two of the eighteen are posed but not legible characters under any "
        "animation in either bank: 88 is object 87's torso with 8 of its 15 limbs pointing at "
        "object 87's dlists past its own end of file (no legs, no head), and 65 is an "
        "untextured blocky column with a blade through it.",
    ),
    (0x10c0, 8): RestPose(
        8, 0xf0,
        "an orange cone-shaped body with a dark purple wing out to each side and a tail behind "
        "(a Keese); un-posed it is a flat sliver. The wings sit high in a V, which reads as a "
        "mid-flap frame rather than a rest - but 0xF0 is the object's only animation, so this "
        "is the best available pose, not a demonstrated rest pose",
    ),
    (0x1c80, 23): RestPose(
        24, 0x9c4,
        "an orange-red bulb with a flat ring of long blades radiating evenly around its base, "
        "Peahat-shaped and symmetric from every view; un-posed the same blades all point one "
        "way in a spray. Overlay 383's $a3, and every Animation_Change in that overlay names "
        "the same offset",
    ),
    (0x20e0, 14): RestPose(
        31, 0x9d4,
        "a compact pale-green creature with a pointed snout and a dark eye socket with a "
        "magenta pupil. WEAK: this model was never a heap - all five of its animations and the "
        "un-posed rig render as the same flat wedge, so the row records the actor's own choice "
        "rather than a repair. Overlay 279's $a3",
    ),
    (0x21f8, 15): RestPose(
        197, 0x7d0,
        "a standing robed NPC - long white skirt with two purple bands, a blue-green tunic, "
        "hands together in front, a tan headdress, the face reading correctly from all four "
        "sides. Un-posed it is a spray of blue and white shards. WEAKER PROVENANCE: no overlay "
        "in the ROM initialises skeleton 0x21f8 and this object has no animation of its own, "
        "so the bank is the attested Hylian idle borrowed on an exact match - the limb tree "
        "AND all 15 limb translations are byte-identical to objects 261 and 277 on skeleton "
        "0xf0 - and the only confirmation is the render",
    ),
    (0x2530, 15): RestPose(
        19, 0xe8,
        "a Cucco: white body, red comb and wattle, yellow beak, both yellow feet under it, "
        "tail feathers behind, correct from front, side and back. Un-posed it is a white blob "
        "with a detached cloud of feather vertices floating above it. The object's only "
        "animation, named by all three of its actors (overlays 243, 370, 414) - and rejected "
        "by BOTH gates, because posing the bird makes it shorter in Y",
    ),
    (0x29c0, 15): RestPose(
        347, 0x7c,
        "the fishing-pond fish: an elongated olive-yellow scaly body with a white belly, a "
        "pointed head with a round eye and an open mouth, dorsal and pectoral fins and a "
        "forked tail, clean from all four yaws. The animation the rip currently picks, "
        "347@0x453c, belongs to the 8-limb skeleton in the same file and tears the body into "
        "loose wedges - and it is taken by the STANDING gate, not by the compactness fallback. "
        "Overlay ROM file 453 (actor 0xFE, Fishing) inits three rigs in this file: @0xca4 skel "
        "0x85f8 -> 347@0x453c, @0x12a8 skel 0x29c0 -> 347@0x7c, @0xb194 skel 0x11058 -> "
        "347@0xcfe0. The grey plaque with a dark zigzag on a blue base beside the fish is an "
        "ATTACHMENT - it is in every build including un-posed, and is what makes the shipped "
        "model 98 triangles against the 59 the skeleton itself draws - not a posing defect",
    ),
    (0x2a40, 7): RestPose(
        57, 0x2b8,
        "a faceted blue-and-magenta shell with green frond-like fins; posed it is rounder and "
        "the fins fold toward the body, un-posed they splay outward. WEAK: both builds are "
        "coherent, so this is an improvement in arrangement rather than a rescue. Named by "
        "both of its actors (overlays 270 and 350)",
    ),
    (0x4010, 5): RestPose(
        395, 0x1cc,
        "a white cow with yellow horns, a yellow nose ring and dark hooves standing on four "
        "legs. This rig's authored rest IS the zero pose: frame 0 of the animation its actor "
        "names has all five rotation triples exactly zero, so the posed and un-posed builds "
        "are byte-identical and this row only flips the `posed` flag. Written down so the next "
        "reader does not go looking for a pose that does not exist",
    ),
    (0x4f70, 15): RestPose(
        386, 0x3f4,
        "a crowd, not one character: about eight small standing figures in white outfits with "
        "arms, legs and differently coloured hair - blond, orange, red, brown - shoulder to "
        "shoulder, two with an arm raised. Un-posed the whole file is shredded confetti. The "
        "two limb clusters sit ~6200 units apart, so this reads as a heap below ~300px; it "
        "only resolves at 400px. Overlay 368's $a3",
    ),
    (0x5810, 26): RestPose(
        158, 0x6044,
        "a bell-shaped white robe over two thin legs that end in blue tapered points, both "
        "arms held out level to the sides ending in black cuffs and long blue blades, a "
        "red-and-black patterned mask square on top, symmetric from front and back - the Flare "
        "Dancer (see names.py 158, named from actor placement and a 900px render, not from "
        "this pose). Segments 8 and 9 are unresolved, so the robe is untextured. The animation "
        "the rip currently picks, 158@0x10b4, is the crumple the user reported: the body "
        "folded over with the robe panels splayed radially and both arms up over the head. NOT "
        "an $a3: overlay ROM file 293 passes $a3 = $zero at 0xb44 and assembles no other "
        "segment-6 animation constant at all; it drives the rig from an AnimationInfo array at "
        "overlay offset 0x289c whose five entries, 0x18 apart, are 0x10b4 (speed 1.0), 0x5c64 "
        "(1.0), 0x6044 (0.0), 0x6a18 (1.0), 0x6b64 (0.0). Init plays entry 0, but that is a "
        "50-frame LOOP and its frame 0 is the start of the dance. Entries 2 and 4 carry "
        "playSpeed 0.0 - held static poses - and of those 0x6044 is the upright one; 0x6b64 "
        "holds the arms out but crosses one leg over the other and rolls the mask. All eight "
        "of the file's animations were rendered; the other six are hunched, collapsed or "
        "scattered",
    ),
    (0x6bc0, 19): RestPose(
        351, 0x14b8,
        "a lumpy pale-green rocky body sitting on a magenta base whose flat plates spread out "
        "into an even skirt; un-posed the same plates sit stacked at angles. WEAK, same as "
        "object 57: neither build is garbage. Overlay 247's $a3",
    ),
    (0x8318, 30): RestPose(
        12, 0x4c20,
        "a four-legged green lizard at rest - spiny back ridge running out to a tail held "
        "behind, four legs under the body, a red mouth line at the front (a Dodongo). Un-posed "
        "the file is a flat fan of green shards. Overlay 280's SkelAnime_Init $a3",
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
    (0xc220, 11): RestPose(
        393, 0x49c,
        "the canopy bed's occupant sits on the edge of the mattress: a purple hooded cloak "
        "over the head and shoulders, a dark face with a red jewel, cream trousers with red "
        "stripes and two bare striped-soled feet hanging over the bedside, and a red-brown "
        "staff or broom lying across the lap. Limb 0 is the bed itself - 350 of the 574 "
        "triangles, posts, bedding, rug, pots and the Triforce wall poster - and never moves. "
        "What the rip currently uses, 393@0xc2e4, IS NOT AN ANIMATION: those 16 bytes are "
        "`00060000 0600c240 0600c238 0600c230`, three segment-6 pointers into the region just "
        "past the limb-pointer array (which itself runs 0xc1f4-0xc220), read as frameCount 6 "
        "and staticIndexMax 0x0600 = 1536, so every joint track reads from that pointer region "
        "and the figure collapses into a formless purple lump. `find_animations` accepts it "
        "because the only fields the validator checks are the first pad, the two segment bytes "
        "and a non-negative staticIndexMax. Overlay ROM file 307's SkelAnime_Init $a3 at 0xdc; "
        "393@0xc8ec, which the same actor plays through Animation_Change, has a "
        "value-for-value identical frame 0",
    ),
    (0x10260, 6): RestPose(
        156, 0x101e4,
        "Volvagia's head: at yaw 45 an unmistakable horned skull - the two grey rock horns "
        "swept up and out in a clean V above a molten orange-red mass, with the dark face and "
        "its two pale plates between them. The rip currently poses this rig with 156@0xd7c, "
        "which belongs to the 18-limb skeleton in the same file - read for six limbs its frame "
        "0 is limb 0 at exactly 360 degrees (identity) and limb 1 at 14.8, so the model ships "
        "indistinguishable from un-posed (extents equal to 0.01) while flagged `posed`, with "
        "the two horns hanging straight down like a pair of legs. Overlay ROM file 164's "
        "SkelAnime_Init $a3 at 0x618, and the file layout pairs them beyond doubt: each of the "
        "three 6-limb skeleton headers (0x100e0, 0x101a0, 0x10260) has its animation header "
        "exactly 0x7C in front of it (0x10064, 0x10124, 0x101e4). Frame 0 rotates only the "
        "root (90/270/90) and the two horn limbs (270 about Z), so it re-orients the head "
        "rather than un-crumpling it; at yaw 315 the un-posed build reads better, at yaw 45 "
        "this one reads far better, and neither is garbage",
    ),
    (0x10d70, 14): RestPose(
        335, 0x499c,
        "adult Zelda standing, hands clasped in front of her",
    ),
    (0x14190, 27): RestPose(
        48, 0xebe4,
        "a Moblin standing square on both feet, arms out, its club resting on the ground in "
        "front of it. The animation the rip currently picks (48@0x6a4) has it leaning with the "
        "club hoisted overhead. Note this offset is WRONG on object 48's OTHER skeleton (head "
        "merged into the torso, spear flung diagonally) - that one is key (0x8f38, 27) and "
        "must stay untouched",
    ),
    (0x19f10, 48): RestPose(
        25, 0xf0d8,
        "King Dodongo at rest: a grey-green pebbled armoured lizard on four short legs, a row "
        "of pale spikes running from the neck down the back to the tail, a wide head at the "
        "front with a red open mouth and teeth, tail behind - correct at yaw 0, 90, 180 and "
        "270. Un-posed the file is a flat crumpled wedge with no legs and no head, and the "
        "animation the rip currently picks (25@0x250bc, a 2-frame header that fires the "
        "standing gate) rears the body up on end and crushes it vertically. Overlay ROM file "
        "163's SkelAnime_InitFlex $a3 at 0x880 (actor 0x27, Boss_Dodongo); the next call "
        "passes the same offset",
    ),
    (0x1e178, 29): RestPose(
        262, 0x203d8,
        "an Iron Knuckle standing upright, legs together, its long-handled axe held vertically "
        "at its side. The animation the rip currently picks (262@0x35c) is shredded scatter "
        "with no body in it - one of five headers in this file that overlay 338 never names "
        "and that belong to no rig here",
    ),
    (0x205c0, 29): RestPose(
        262, 0x203d8,
        "the second 29-limb header in the same file drives identical geometry (both 668 "
        "triangles, cell-for-cell identical renders) - the same standing knight with the axe "
        "vertical. The code names 262@0xc114 for this one, but that is 215 frames of the "
        "throne/rise cutscene and its frame 0 is a hunched crouch",
    ),
    (0x30c20, 43): RestPose(
        211, 0x244b4,
        "Twinrova standing: a slim figure in a black-and-gold patterned bodice and striped "
        "leggings with green-tipped shoes, on both feet, both arms held straight out to the "
        "sides with a broom in each hand and a red ornament at the head. The large white slabs "
        "are her hair and flame, untextured because segments 8, 9, 0xA, 0xB and 0xC are "
        "unresolved. Symmetric at all four yaws. The animation the rip currently picks "
        "(211@0x1d10, the first in the file to fire the standing gate) splays the legs and "
        "twists the torso. Overlay ROM file 172's SkelAnime_Init $a3 at 0xf9c, which is the "
        "call for THIS skeleton - the same overlay inits the file's other two rigs at 0xdfc "
        "(with 211@0x6f28) and 0xec8, and this offset must not be given to either",
    ),
}

#: object id -> RestPose, consulted BEFORE the skeleton key.
#:
#: One rig, eighteen models, and their limb TRANSLATIONS are not shared - only the tree is.  So
#: a single row cannot always speak for all of them, and this is the escape hatch.  Keep it
#: empty unless a member is demonstrably broken under the family row AND the replacement is
#: demonstrably wrong for the rest; that is the whole reason the key is the rig in the first
#: place.  The key is the OBJECT ALONE, so an entry poses EVERY skeleton in that object's file -
#: safe for 67, which has exactly one, and NOT safe for a multi-rig object like 211 (3 rigs),
#: 156 (4), 347 (3) or 158 (2).  Key on (object_id, skeleton_offset) before adding a row for any
#: of those.
REST_POSES_BY_OBJECT: dict[int, RestPose] = {
    67: RestPose(
        52, 0x242c,
        "the woman in the tiered pink-and-green dress, standing: the lilac tiers stack into "
        "one bell instead of splitting into two lobes at the hem, arms down at her sides with "
        "the hands in front. REST_POSES[(0x260, 38)] = 41@0x1300 is NOT wrong - it stands "
        "objects 51, 61, 68 and 69 up correctly, rendered side by side - but it cannot work "
        "here. Her lower body is eight entries into ONE display list: limbs 8, 9, 10, 15, 16, "
        "17, 18 and 37 point at 0x6001f68..0x6001fa0, eight bytes apart, a run of "
        "G_RDPPIPESYNCs that all fall through into the same body at 0x1fa8, so each returns "
        "the same 46 triangles and the skirt is one tier mesh drawn eight times down two leg "
        "chains. Her hips are wide - limbs 4 and 11 at (150, -150, +/-500) - but that is NOT "
        "the cause: objects 40, 68 and 69 have byte-identical hips and stand clean. What "
        "differs is the SIZE of the repeated tier - 554 triangles against 327, 236 and 84 - so "
        "on her the eight copies separate visibly whenever a pose keeps the legs apart. All "
        "seven animations in bank 41 and five of the six in bank 52 do; 52@0x242c is the only "
        "one that closes them, and the gain is real but modest - she is a lumpy low-poly stack "
        "either way. It cannot become the family row: rendered over all eighteen it raises "
        "ValueError('negative shift count') in the F3DEX2 interpreter on objects 51, 53, 75, "
        "76 and 78, and it throws object 46's cape up over its head",
    ),
}


def rest_pose(skeleton_offset: int, limb_count: int,
              object_id: int | None = None) -> RestPose | None:
    """The attested rest pose for a skeleton, or None.

    An object-keyed row wins over the rig-keyed one, because a rig shared by models with
    different limb translations cannot always be posed by one animation.
    """
    if object_id is not None:
        found = REST_POSES_BY_OBJECT.get(object_id)
        if found is not None:
            return found
    return REST_POSES.get((skeleton_offset, limb_count))
