"""Which tests can actually tell a correct read from a wrong one - and which cannot.

Cracking a format is easy once you can *check* an answer.  The hard part is that most obvious
checks are worthless, and a worthless check does not announce itself: it passes, you believe it,
and you ship a reader that produces confident nonsense.

The Climax `.bad` codec is the cautionary case.  Four separate oracles were tried on it, each
reasonable-looking, and every one turned out to be incapable of distinguishing a good decode
from a bad one.  That cost far more than the decoder variants did.  This registry exists so the
next attempt does not spend its time re-discovering that.

Entries are graded:

``PROVEN``
    It has separated right from wrong on real data, and the entry says where.
``WEAK``
    It carries some signal but rests on an assumption that may not hold; use it to rank
    candidates, never to accept one.
``DISCREDITED``
    It looked reasonable and is not evidence.  The entry says exactly how it failed, because
    "we tried that" is only useful with the reason attached.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVEN = "proven"
WEAK = "weak"
DISCREDITED = "discredited"


@dataclass(frozen=True)
class Oracle:
    name: str
    #: what the test actually asks of the data
    asks: str
    grade: str
    #: where it was used, or how it failed - a grade with no evidence is an opinion
    evidence: str


ORACLES: tuple[Oracle, ...] = (
    Oracle(
        "size identity",
        "a number the file states equals a number computed from the file",
        PROVEN,
        "MULA: 32 + palette + pixel bytes == entry size on 200 of 200 images, and payloads tile "
        "the block to the byte (412,520 and 147,312).  Gun: payload + 32 == file length on 5 of "
        "5.  Darkened Skye: the word at +8 is the file's own length on 17 of 17.  This is the "
        "one that has never misled.",
    ),
    Oracle(
        "unit length",
        "a stored vector that must have length 1.0 does",
        PROVEN,
        "PHM: normals over 1,987 vertices at mean 0.9998, sd 0.0001.  Darkened Skye: 400 "
        "animation quaternions all unit length - and 358 of them distinct, which is the check "
        "that stops one repeated constant looking like a result.",
    ),
    Oracle(
        "known plaintext",
        "the same asset stored raw elsewhere appears verbatim inside the packed blob",
        PROVEN,
        "Tiger Woods: 06 stores course `ter` raw, 2005 packs it, and 47,114 verbatim runs cover "
        "10.8% of the packed archive.  Sixteen-byte coincidences do not happen.  See "
        "gcrip/knownplain.py.  This is the only oracle that has ever cracked a codec here.",
    ),
    Oracle(
        "cross-file agreement",
        "two files that describe each other agree on a number",
        PROVEN,
        "Terminal Reality: soldier.dfm's bone count is 82 and SOLDIER_DEFAULT.SKL holds exactly "
        "82 bones; mentor 68 and 68.  EAGL: a skeleton header's bone count is 51 against exactly "
        "51 __Bone symbols in the same object.",
    ),
    Oracle(
        "semantic plausibility",
        "decoded names describe the thing they are attached to",
        PROVEN,
        "Terminal Reality: resolving each part's bone index through the .SKL gives binoculars2 "
        "-> Bip01 L Hand, waist -> Bip01 Spine, chest-open -> Bip01 Spine2.  A mis-read table "
        "does not produce English.  Strong as confirmation, useless as a search.",
    ),
    Oracle(
        "smoothness against a shuffled copy",
        "an image is smoother than its own pixels in random order",
        PROVEN,
        "Real textures score 3-70x; noise scores about 1x.  Reliable for 'is this an image', but "
        "it cannot settle dimensions or format - it said nothing useful about EA's format 11, "
        "which size arithmetic had to decide.",
    ),
    Oracle(
        "normal agreement",
        "face normals from candidate position columns agree with stored normals",
        WEAK,
        "Valid for CHOOSING among candidates when the normals are already verified - PHM's "
        "position triple scored 0.748 against 0.42-0.56 for every other.  Invalid as a SEARCH: "
        "on Terminal Reality's _dfm every high-scoring fit was planar-degenerate.",
    ),
    Oracle(
        "name repetition",
        "an asset name should not appear hundreds of times",
        WEAK,
        "Climax .bad: rlmudguard appears 186 times, which looks damning - but nothing "
        "establishes that a 643-part table cannot list it once per vehicle configuration.  "
        "Suggestive, never conclusive.",
    ),
    Oracle(
        "name chain length",
        "a declared count of N names implies a run of N back-to-back strings",
        WEAK,
        "Climax .bad: the longest chain is 5 where 643 parts are declared, which looks decisive "
        "until you notice the names are spaced irregularly (5,968 then 3,975 then 1,026 bytes) "
        "so there may be no packed table at all.  Sixteen operand packings scored 2-13 against "
        "it and the result is a weak negative, not a proof.",
    ),
    Oracle(
        "box containment for quantised vertices",
        "decoded positions fall inside the part's declared bounding box",
        DISCREDITED,
        "Proposed twice for Terminal Reality's `_dfm`, as 'the oracle the vertex search lacked'.  "
        "It is **vacuous**: if positions are quantised and dequantised as "
        "box_min + raw/FULL * (box_max - box_min), containment is guaranteed by construction "
        "whatever the stride, byte order or offset.  It can only test a layout that stores "
        "positions as absolute floats - which `_dfm` does not, its tail being 1.9% plausible f32.",
    ),
    Oracle(
        "quantised axis uses its full range",
        "a tight box implies raw u16 positions span 0..65535",
        DISCREDITED,
        "The intended repair for the one above, and no better.  Every candidate stride from 12 to "
        "32 bytes produced a column spanning exactly 0..65535 - and every one sat at "
        "offset stride-1, straddling record boundaries.  With a few thousand samples arbitrary "
        "bytes span the full range, so this passes on noise.",
    ),
    Oracle(
        "triangle locality over a candidate position array",
        "a candidate array is the positions if the triangles that index it are small against "
        "its own bounding box",
        DISCREDITED,
        "It is wrong in the worst way: it finds INDEX ARRAYS, not positions, and prefers them.  "
        "Consecutive indices are "
        "numerically close, so an index buffer read as xyz triples has tiny triangles inside a "
        "wide box: on Piglet's clump tail the best score in the whole 2.2 MB was 0.0077 at an "
        "offset whose vertices read (476,476,478), (478,478,478) - a run of one repeated u16.  "
        "Real geometry scored worse.  The repair is to require the three components of a vertex "
        "to differ - index data has them nearly equal - but a mean over the array is not enough "
        "either, because triples that straddle a boundary lift the average: (331,331,331), "
        "(719,719,719) still came top with that filter in place.  It has to be the FRACTION of "
        "vertices whose components agree, and that is still unverified.",
    ),
    Oracle(
        "printable text",
        "the output decodes to a high fraction of printable characters",
        DISCREDITED,
        "Climax .bad: the tail of a wrong decode is 100% printable and completely meaningless - "
        "`pttept opt peoaws opt peoaw`.  This was the evidence originally given for Hot Wheels, "
        "which therefore needs re-checking against something else.",
    ),
    Oracle(
        "decoder stopped at the declared length",
        "the decode ends on the length the file states",
        DISCREDITED,
        "Only when the walk is allowed to RUN there.  Clipping the last copy to the target - "
        "the ordinary way to end an LZ decode - makes every rule land on it: a wrong split of "
        "Visual Concepts' match word scored 251 of 251 that way and produced garbage.  Take "
        "the clip out and the same rule scores 164, while the right one reaches the exact "
        "length unaided on 246 of 251.  The arrival is the evidence; the stop is not.",
    ),
    Oracle(
        "input fully consumed",
        "a correct decoder consumes its input exactly",
        DISCREDITED,
        "Climax .bad: true for every variant by construction, because the walk runs until "
        "i >= n.  Decoding from a deliberately WRONG start offset consumed 32.69% of the input "
        "against the correct start's 32.69%.  It measures the loop's termination condition and "
        "nothing else - not the framing, not the lengths, not the match positions.",
    ),
)


def by_grade(grade: str) -> tuple[Oracle, ...]:
    return tuple(o for o in ORACLES if o.grade == grade)


def find(name: str) -> Oracle | None:
    return next((o for o in ORACLES if o.name == name), None)
