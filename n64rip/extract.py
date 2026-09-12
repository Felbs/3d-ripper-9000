"""Whole-ROM extraction: every actor with a skeleton, exported as a rigged glTF.

Mirrors what ``gcrip.rip`` does for a disc, and writes the same ``rip_results.json`` shape, so
the library browser, the quality auditor, the MCP tools and the Blender add-on read an N64 rip
exactly as they read a GameCube one.

Segment binding is the honest part.  An actor's own file is segment 6, which is what makes
most characters work standalone.  Segment 4 is ``gameplay_keep``, a shared bank several actors
borrow textures from, so it is bound when it can be identified.  Segments 8-0F are written by
actor code while the game runs and cannot be bound at all - models that use them come out with
some textures missing, and say so rather than pretending.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from n64rip import (
    actor_code as actor_mod,
    attested,
    anim as anim_mod,
    f3dex2,
    face as face_mod,
    objects as obj_mod,
    skeleton as skel_mod,
    texture as tex_mod,
    zobj,
)
from n64rip.rom import Rom, RomFile
from ripcore import gltf

MIN_TRIANGLES = 4


@dataclass
class ModelResult:
    name: str
    file_index: int
    vrom: str
    out_rel: str = ""
    thumb: str = ""
    triangles: int = 0
    vertices: int = 0
    textures: int = 0
    textures_missing: int = 0
    limbs: int = 0
    drawn_limbs: int = 0
    skinned: bool = True
    unresolved_segments: list[int] = field(default_factory=list)
    posed: bool = False  # a rest pose was applied and it stood the model up
    expressions: list[str] = field(default_factory=list)  # face textures written beside it
    object_id: int | None = None  # its slot in the game's object table, when it has one
    error: str = ""
    warnings: list[str] = field(default_factory=list)


# segment binding now comes from the game's own object table; see n64rip.objects



#: Link's object ids, read from the game's own object table rather than assumed
LINK_OBJECTS = (20, 21)

#: Objects posed from ``link_animetion`` rather than from an ``AnimationHeader``.  Object 32 is
#: NOT Link - it must stay out of LINK_OBJECTS, which decides whose face table to read - but it
#: is built on his skeleton: its 21 limb translations are byte-identical to object 20's and to
#: nothing else in the ROM, objects 20 and 21 contain no AnimationHeaders at all, and its actor
#: reaches its animations through an indirect call consistent with LinkAnimationHeaders.  So
#: frame 0 of link_animetion is its authored rest pose, and it renders as a Link-shaped figure
#: standing with a shield on the left arm and a sword in the right (Dark Link, near-black
#: because segment 0x0C is unresolved) instead of a pile of boxes on its side.
LINK_ANIM_OBJECTS = LINK_OBJECTS + (32,)


#: How many of a file's animations to try when looking for a rest pose.  It used to be four,
#: which is fewer than most characters ship: the one that poses object 359 correctly is its
#: eighth, and object 211 carries thirty.
MAX_POSE_ANIMS = 64


def _pose_quality(ext_before, ext_after):
    """Is this posed extent a better resting shape than the un-posed one?

    Returns ``(stands, better)``.

    ``stands`` is the original gate - a standing character is tallest in Y - which has posed
    a hundred models correctly and is left in charge wherever it fires.

    ``better`` is the weaker fallback, for the creatures that gate cannot speak for: a crab is
    not tallest in Y and never will be.  An un-posed rig is *degenerate* - its chains run
    along one axis, so its smallest dimension is tiny next to its largest - while a rest pose
    occupies three dimensions.  So: the thinnest axis must grow relative to the longest, and
    the longest must not grow at all.  That second half matters; without it the measure
    rewards a pose that simply inflates the model.
    """
    import numpy as np

    a = np.asarray(ext_before, dtype=float)
    b = np.asarray(ext_after, dtype=float)
    stands = anim_mod.stands_up(a, b)
    if float(a.max()) < 1e-6 or float(b.max()) < 1e-6:
        return stands, False
    aspect_before = float(a.min()) / float(a.max())
    aspect_after = float(b.min()) / float(b.max())
    better = aspect_after > aspect_before + 0.02 and float(b.max()) <= float(a.max()) * 1.001
    return stands, better


def _pose(scene, name, data, skel, segments, link_anim, object_id, attachments=None,
          rest_banks=None):
    """A posed rebuild of *scene*, or None if no rest pose improved it.

    A skeleton stores only limb offsets, so an un-posed model has every chain extended along
    one axis - arms several times longer than the torso.  Frame 0 of one of the actor's own
    animations is the pose it was authored in.

    Which one is not recorded anywhere we can read: the actor picks it at runtime.  So every
    animation in the file is tried and the result judged.  A pose that makes the character
    stand is taken at once.  Failing that, the most compact frame 0 is taken **if** it makes
    the model less degenerate - see :func:`_pose_quality` - which is how the crab-shaped and
    four-legged characters get a rest pose at all.
    """
    import numpy as np

    if not scene.primitives:
        return None
    before = np.concatenate([p.positions for p in scene.primitives])
    ext_before = before.max(0) - before.min(0)

    nulls = attested.null_limbs(object_id)

    # An attested rest pose comes first and is taken on sight: it was chosen by rendering,
    # which is the only thing that has ever settled this, and the gates below cannot tell a
    # correct rest pose from a wrong one that merely happens to be compact.
    rest = attested.rest_pose(skel.offset, skel.count, object_id)
    if rest is not None and rest_banks:
        bank = rest_banks.get(rest.bank)
        if bank:
            a = anim_mod.read_animation(bank, rest.offset)
            if a is not None:
                try:
                    root, rots = anim_mod.frame_values(bank, a, skel.count, 0)
                    world = anim_mod.pose_matrices(skel, rots, root, "zyx")
                    cand = zobj.build(name, data, skel, segments, world=world,
                                      rotations=rots, attachments=attachments,
                                      null_limbs=nulls)
                except Exception:  # noqa: BLE001
                    cand = None
                if cand is not None and cand.primitives:
                    return cand, world, rots

    sources = []
    if object_id in LINK_ANIM_OBJECTS and link_anim:
        sources.append(anim_mod.link_frame(link_anim, skel.count, 0))
    for a in anim_mod.find_animations(data)[:MAX_POSE_ANIMS]:
        sources.append(anim_mod.frame_values(data, a, skel.count, 0))

    fallback = None
    for root, rots in sources:
        try:
            world = anim_mod.pose_matrices(skel, rots, root, "zyx")
            cand = zobj.build(name, data, skel, segments, world=world, rotations=rots,
                              attachments=attachments, null_limbs=nulls)
        except Exception:  # noqa: BLE001
            continue
        if not cand.primitives:
            continue
        after = np.concatenate([p.positions for p in cand.primitives])
        ext_after = after.max(0) - after.min(0)
        stands, better = _pose_quality(ext_before, ext_after)
        if stands:
            return cand, world, rots
        if better:
            # among the candidates that qualify, the one that occupies the least space
            score = float(np.prod(np.maximum(ext_after, 1.0)))
            if fallback is None or score < fallback[0]:
                fallback = (score, cand, world, rots)
    if fallback is not None:
        return fallback[1], fallback[2], fallback[3]
    return None


#: A limb whose geometry is entirely the swapped tile is not a head.  Measured over every
#: actor in Ocarina of Time that binds a face: the tile covers between 4.7% and 48.9% of its
#: limb, because a head also carries skin, hair and ears.  The cases that sit at 100% are a
#: glow sprite, a rupee-like ring and a small flame - single quads of 2 to 6 triangles that
#: happen to sample segment 8, and binding a "face" onto them ships a black donut.
MAX_FACE_SHARE = 0.75
MIN_HEAD_TRIANGLES = 16


def _face_batches(data, skel, segments):
    """Every batch the actor draws through a face segment, with where it sits on the head.

    Returns ``[(segment, tile spec, centroid, x span, triangles, limb triangles)]``.
    """
    # The mirror test compares centroids across the head's centre line, so the geometry has
    # to be in the head's own space.  zobj binds the limb matrices on segment 0x0D in place,
    # and once a model has been posed those matrices carry the pose: the two eyes are then
    # mirrored about wherever the head is looking, not about z=0, the test fails, the right
    # eye is read as the mouth and the real mouth is dropped.  Run without the matrices.
    local = f3dex2.Segments({k: v for k, v in segments.bases.items() if k != 0x0D})
    out = []
    for i in skel.order():
        limb = skel.limbs[i]
        if not limb.dlist:
            continue
        try:
            res = f3dex2.run(limb.dlist, local)
        except Exception:  # noqa: BLE001
            continue
        total = sum(len(b.indices) // 3 for b in res.batches if b.indices is not None)
        for b in res.batches:
            tile = b.tile
            if tile.addr is None or not tile.width or not tile.height:
                continue
            seg = (tile.addr >> 24) & 0x0F
            if seg not in face_mod.FACE_SEGMENTS:
                continue
            if b.positions is None or not len(b.positions):
                continue
            spec = (tile.fmt, tile.size, tile.width, tile.height)
            centre = b.positions.mean(axis=0)
            span = float(b.positions[:, 0].max() - b.positions[:, 0].min())
            tris = len(b.indices) // 3 if b.indices is not None else 0
            out.append((seg, spec, centre, span, tris, total))
    return out


def _mirrored(a, b) -> bool:
    """Are these two batches the left and right of one feature?

    A character whose eyes are drawn as two calls issues the same tile twice at centroids
    mirrored across the head's centre line.  Measured on this ROM the pairs agree to within a
    few percent - (255.2, 611.8, -162.0) against (255.2, 611.2, +162.0) - while a genuine
    eye-and-mouth pair sits at very different heights and spans.

    The **tile**, not the palette, decides this.  Judging by palette loses the mouths of three
    characters whose two features share one, and calls both features mouths on three others
    whose eye segments differ.
    """
    _sa, spa, ca, spna, _ta, _la = a
    _sb, spb, cb, spnb, _tb, _lb = b
    if spa != spb or ca[2] * cb[2] >= 0:
        return False
    if abs(abs(ca[2]) - abs(cb[2])) > 0.08 * max(abs(ca[2]), abs(cb[2]), 1e-6):
        return False
    return abs(spna - spnb) <= 0.10 * max(spna, spnb, 1e-6)


#: Retired.  This gate rejected any actor whose swapped tile was the whole of its limb, on
#: the reasoning that a head also carries skin and hair - and it did keep a cart from binding
#: a wheel texture.  But two of the three actors it caught were **Deku Scrubs, whose eyes
#: genuinely are glowing dots on their own two-triangle billboards**, and the user found them
#: on the models with no eyes at all.  The lesson is the usual one here: the judgement was
#: made by looking at 8x8 textures out of context rather than at the characters.
#:
#: Nothing replaces it.  A segment-8 binding recovers whatever the game itself points that
#: segment at, and the noise gates already reject anything that is not a coherent image; a
#: wheel bound to the slot the game binds a wheel to is not a defect.
MAX_FACE_SHARE = 1.01
MIN_HEAD_TRIANGLES = 0


def _face_roles(data, skel, segments):
    """Which segments are eyes, which are the mouth, and what tiles each asks for.

    Returns ``(eye_segments, mouth_segments, eye_tiles, mouth_tiles)``.

    The assignment is per actor because the layout is.  The common case is one eye segment
    and one mouth segment.  But a head that draws its left and right eye separately spends
    two segments on the eyes and puts the mouth on a third - and binding by segment number
    alone then paints a mouth where the right eye belongs.  Segments that mirror each other
    are one feature; whatever centred segment is left is the mouth.
    """
    batches = [b for b in _face_batches(data, skel, segments)
               if not (b[5] and b[4] / b[5] > MAX_FACE_SHARE and b[5] < MIN_HEAD_TRIANGLES)]
    if not batches:
        return (), (), set(), set()

    eye_segs: list[int] = []
    for i, a in enumerate(batches):
        for b in batches[i + 1:]:
            if a[0] != b[0] and _mirrored(a, b):
                for s in (a[0], b[0]):
                    if s not in eye_segs:
                        eye_segs.append(s)
    if not eye_segs:
        eye_segs = [min(b[0] for b in batches)]
    rest = sorted({b[0] for b in batches} - set(eye_segs))
    mouth_segs = rest[:1]

    def tiles(segs):
        return {b[1] for b in batches if b[0] in segs}

    return tuple(sorted(eye_segs)), tuple(mouth_segs), tiles(eye_segs), tiles(mouth_segs)


def _wanted_face_tiles(data, skel, segments):
    """``{segment: {(fmt, size, w, h)}}`` - kept for callers that want it by segment.

    Only the **format** here is trustworthy.  Width and height are derived from how many
    texels were actually loaded, and for exactly the actors whose face is missing nothing was
    ever loaded on that segment, so the size has to come from somewhere else.  SETTILE states
    the format outright, so that part is solid.
    """
    want: dict[int, set] = {}
    for seg, spec, _c, _s, tris, total in _face_batches(data, skel, segments):
        if total and tris / total > MAX_FACE_SHARE and total < MIN_HEAD_TRIANGLES:
            continue  # the tile is the whole limb: an effect sprite, not a face
        want.setdefault(seg, set()).add(spec)
    return want


#: frames of one eye agree far above this; unrelated data falls far below it
MIN_EXPRESSION_CORR = 0.45

#: bits a texel, by the display list's size field
BITS = {0: 4, 1: 8, 2: 16, 3: 32}


def _frame_agreement(data, offs, nbytes) -> float:
    """How much of their raw bytes consecutive entries share.

    The frames of an eye set are one drawing with the lid moved, so most of the texture -
    the skin around the eye - is byte-identical between frames.  Unrelated data shares about
    one byte in 256.  That gap is far wider than any measure taken after decoding, and it
    costs nothing to compute.

    It is also the only measure that works on colour-indexed art.  Pearson correlation over
    palette *indices* is close to meaningless, because neighbouring indices are not
    neighbouring colours - which is why scoring that way rejected several eye sets that
    plainly render as eyes.
    """
    import numpy as np

    if len(offs) < 2 or nbytes <= 0:
        return 0.0
    frames = []
    for off in offs:
        if off + nbytes > len(data):
            return 0.0
        frames.append(np.frombuffer(data, np.uint8, nbytes, off))
    for f in frames:
        counts = np.bincount(f, minlength=256)
        if counts.max() / f.size > 0.95:
            return 0.0  # a frame that is one repeated byte is padding
    scores = [float(np.mean(a == b)) for a, b in zip(frames, frames[1:])]
    mean = float(np.mean(scores))
    return 0.0 if mean > 0.9995 else mean


def _pixel_correlation(images) -> float:
    """A fallback for true-colour faces, whose frames are re-shaded rather than copied.

    RGBA16 eyes are drawn with soft edges, so two frames can share few exact bytes while
    plainly being the same picture.  Correlation is meaningful here precisely because the
    values are colours rather than palette indices.
    """
    import numpy as np

    if len(images) < 2:
        return 0.0
    scores = []
    for a, b in zip(images, images[1:]):
        x = a[..., :3].astype(np.float64).ravel()
        y = b[..., :3].astype(np.float64).ravel()
        if x.std() < 1e-6 or y.std() < 1e-6:
            return 0.0
        scores.append(float(np.corrcoef(x, y)[0, 1]))
    mean = float(np.mean(scores))
    return 0.0 if mean > 0.9995 else mean


def _roughness(images) -> float:
    """Mean difference between neighbouring texels, as a fraction of full scale.

    Drawn art is locally smooth - skin, an eyelid, the white of an eye are all runs of
    similar texels - while bytes that are not a picture differ from their neighbours about as
    much as two random numbers do, which lands near 0.33.  Used only to *reject*, and only
    well above anything a real texture reaches, because a face decoded out of unrelated bytes
    is worse than an honestly blank one.
    """
    import numpy as np

    if not images:
        return 1.0
    vals = []
    for im in images:
        a = im[..., :3].astype(np.float64)
        if a.shape[1] < 2:
            continue
        dx = np.abs(np.diff(a, axis=1)).mean()
        dy = np.abs(np.diff(a, axis=0)).mean() if a.shape[0] > 1 else dx
        vals.append((dx + dy) / 2.0 / 255.0)
    return float(np.mean(vals)) if vals else 1.0


def _structure_ratio(images) -> float:
    """Local variation as a fraction of the image's own overall variation.

    Scale-free, which is what :func:`_roughness` is not.  In noise, neighbouring texels differ
    by as much as any two texels do, so the ratio sits near 1; in a drawing they differ far
    less, because a drawing is made of regions.  A low-contrast palette can make genuine noise
    look smooth in absolute terms - that is what let an actor ship twenty-one frames of grey
    confetti - and dividing by the image's own spread sees through it.
    """
    import numpy as np

    if not images:
        return 1.0
    vals = []
    for im in images:
        a = im[..., :3].astype(np.float64)
        if a.shape[0] < 2 or a.shape[1] < 2:
            continue
        local = (np.abs(np.diff(a, axis=1)).mean() + np.abs(np.diff(a, axis=0)).mean()) / 2.0
        flat = a.reshape(-1, 3)
        spread = np.abs(flat - flat.mean(0)).mean() * 2.0
        vals.append(local / spread if spread > 1e-9 else 1.0)
    return float(np.mean(vals)) if vals else 1.0


#: Noise sits near 1.0.  Re-measured once the face palette was being used to decode the
#: candidates rather than a grey ramp: every table verified by eye comes in at or below 0.30
#: (the busiest, a Deku mouth, averages 0.28), and every table that turned out to be
#: unrelated bytes is above it.  The old 0.45 dated from the wrong-palette measurements and
#: was letting three characters ship mouths made of somebody else's mesh.
MAX_STRUCTURE_RATIO = 0.30


#: uniform random bytes measure about 0.33; every face verified by eye came in under 0.20
MAX_ROUGHNESS = 0.20


def _expression_score(data, offs, nbytes, images) -> float:
    """How much a candidate table looks like one face wearing several expressions.

    Whichever of the two measures suits the artwork; each is decisive where the other is
    blind.  Replaces scoring by pixel variance, which was exactly backwards - noise has more
    variance than any real image, so maximising it selected garbage and put scrambled bytes
    on nineteen faces.
    """
    return max(_frame_agreement(data, offs, nbytes), _pixel_correlation(images))


def _decode_table(data, offs, fmt, size, dims, tlut):
    w, h = dims
    out = []
    for off in offs:
        try:
            img = tex_mod.decode(fmt, size, w, h, data[off:], tlut, 0)
        except Exception:  # noqa: BLE001
            return []
        if img is None:
            return []
        out.append(img)
    return out


def _candidate_dims(want_tiles, fmt, size, run):
    """Every plausible size for one format: what the display list said, and what the
    spacing measures.  They disagree often enough that guessing between them blind is how
    nineteen faces came out as lace, and cheap enough to simply try both and score them."""
    dims = {(w, h) for f, s, w, h in want_tiles if (f, s) == (fmt, size)}
    from_stride = actor_mod.tile_for(actor_mod.modal_stride(run), BITS.get(size, 8))
    if from_stride:
        dims.add(from_stride)
    return dims


def _frame_steps(data, offs, nbytes, images):
    """How well each consecutive pair of entries matches, one number per step."""
    import numpy as np

    steps = []
    for a, b in zip(offs, offs[1:]):
        if a + nbytes > len(data) or b + nbytes > len(data):
            steps.append(0.0)
            continue
        fa = np.frombuffer(data, np.uint8, nbytes, a)
        fb = np.frombuffer(data, np.uint8, nbytes, b)
        steps.append(float(np.mean(fa == fb)))
    if images and len(images) == len(offs) and max(steps, default=0.0) < 0.2:
        # true-colour art is re-shaded rather than copied, so few bytes match; compare pixels
        steps = []
        for a, b in zip(images, images[1:]):
            x = a[..., :3].astype(np.float64).ravel()
            y = b[..., :3].astype(np.float64).ravel()
            steps.append(0.0 if x.std() < 1e-6 or y.std() < 1e-6
                         else float(np.corrcoef(x, y)[0, 1]))
    return steps


#: below this, two entries are not the same feature - measured eye-to-eye steps run 0.5-0.8
#: and unrelated data lands near zero, so the cut is nowhere near either
MIN_STEP = 0.25


#: A frame is unlike the rest of its table when it is this much rougher than the cleanest
#: frame in it *and* rough in absolute terms.  Both halves are needed: the relative test
#: alone cuts the dark open mouth out of Link's four, and the absolute test alone cuts
#: characters whose eyes are simply drawn with more detail than most.
JUNK_FRAME_RELATIVE = 2.0
JUNK_FRAME_FLOOR = 0.30


def _frame_is_face(images):
    """Per frame: does this look like part of the same drawn set as the rest?

    Measured across every table in Ocarina of Time, a real frame sits between 0.09 and 0.31
    on the local-versus-global scale, and a frame of unrelated mesh between 0.28 and 0.45 -
    so neither a fixed cut nor a purely relative one separates them, but the pair does.
    """
    if not images:
        return []
    ratios = [_structure_ratio([im]) for im in images]
    floor = min(ratios)
    return [not (r > floor * JUNK_FRAME_RELATIVE and r > JUNK_FRAME_FLOOR) for r in ratios]


def _coherent_span(steps, ok=None):
    """The longest stretch of a table that holds together: ``(start, end_inclusive)``.

    A pointer run does not begin and end where the eye table does.  It can open on an
    unrelated pointer and it can carry on past the last eye into whatever the actor stored
    next - one character shipped four real frames followed by four of somebody else's mesh.
    Two things end a stretch: a frame that does not look like the others (``ok``), and a step
    between neighbours that do not match.
    """
    n = len(steps) + 1
    if n < 2:
        return 0, max(0, n - 1)
    if ok is None or len(ok) != n:
        ok = [True] * n
    best = (0, 0, 0)
    i = 0
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ok[j + 1] and steps[j] >= MIN_STEP:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, i, j)
        i = j + 1
    if best[0] == 0:  # nothing holds together; keep it whole and let the table gates judge
        return 0, n - 1
    return best[1], best[2]


def _trim_table(data, offs, nbytes, images):
    """Keep a table's coherent span; hand back everything after it.

    The tail matters: an actor's eye and mouth tables sit next to each other in one array, so
    what the eye table sheds is usually the mouth table - at its own size, not the eye's.
    """
    if len(offs) < 3:
        return list(offs), []
    steps = _frame_steps(data, offs, nbytes, images)
    ok = _frame_is_face(images) if len(images) == len(offs) else None
    lo, hi = _coherent_span(steps, ok)
    return list(offs[lo:hi + 1]), list(offs[hi + 1:])


def _size_table(data, offs, want_tiles, fallback_fmt, tlut):
    """Pick the size and format for a table whose offsets are already known.

    Needed for the tail an eye table sheds.  Inheriting the eye's dimensions is wrong - a
    mouth is not the same shape as an eye, and the game does not store it at the same size -
    and that is what left several actors' mouths striped.
    """
    formats = sorted({(f, s) for f, s, _w, _h in want_tiles}) or [fallback_fmt]
    stride = actor_mod.modal_stride(offs)
    best = (0.0, None)
    for fmt, size in formats:
        dims_set = {(w, h) for f, s, w, h in want_tiles if (f, s) == (fmt, size)}
        from_stride = actor_mod.tile_for(stride, BITS.get(size, 8))
        if from_stride:
            dims_set.add(from_stride)
        for dims in sorted(dims_set):
            nbytes = dims[0] * dims[1] * BITS.get(size, 8) // 8
            if offs[-1] + nbytes > len(data):
                continue
            imgs = _decode_table(data, offs, fmt, size, dims, tlut)
            if not imgs:
                continue
            score = _expression_score(data, offs, nbytes, imgs)
            if _roughness(imgs) > MAX_ROUGHNESS or _structure_ratio(imgs) > MAX_STRUCTURE_RATIO:
                continue
            if score > best[0]:
                best = (score, (dims, (fmt, size)))
    return best[1]


def _spans(run, min_len=2):
    """Every contiguous stretch of a run, longest first.

    Needed only for the seeded walk, which runs past the end of the table by design: its
    frames are a fixed stride apart, so the real table is a stretch somewhere inside it and
    the surrounding junk would otherwise drag the whole candidate below the gates.  A pointer
    run read out of an overlay does not need this - it is already exactly the table the actor
    indexes - and giving it the same treatment would widen the search for no gain.
    """
    out = []
    n = len(run)
    for length in range(n, min_len - 1, -1):
        # The table starts where the palette ends, give or take one frame of something else
        # in front of it - two of the actors recovered this way keep a mouth at the seed and
        # their eyes immediately after.  Anything further in is not anchored by anything.
        for i in range(0, min(MAX_SEED_SKIP, n - length) + 1):
            out.append(list(run[i:i + length]))
    return out


def _best_table(data, runs, want_tiles, tlut, exclude=(), spans=False):
    """The table, size and format that best read as one face wearing several expressions.

    Chosen by **length first**, among the candidates that clear the threshold.  Scoring alone
    picks the shortest table every time, because the score is an average over consecutive
    pairs and a two-entry candidate has only its single best pair to average - which reduced
    a nine-expression face to two.
    """
    formats = sorted({(f, s) for f, s, _w, _h in want_tiles})
    if not formats:
        return None
    best = (0, 0.0, None)  # entries, score, payload
    for run in runs:
        cands = _spans(run) if spans else actor_mod.texture_tables(run)
        for offs in cands:
            if any(o in exclude for o in offs):
                continue
            for fmt, size in formats:
                for dims in sorted(_candidate_dims(want_tiles, fmt, size, run)):
                    nbytes = dims[0] * dims[1] * BITS.get(size, 8) // 8
                    if offs[-1] + nbytes > len(data):
                        continue
                    imgs = _decode_table(data, offs, fmt, size, dims, tlut)
                    if not imgs:
                        continue
                    score = _expression_score(data, offs, nbytes, imgs)
                    if score < MIN_EXPRESSION_CORR:
                        continue
                    # indistinguishable from noise; a blank face is better than a wrong one
                    if _roughness(imgs) > MAX_ROUGHNESS:
                        continue
                    if _structure_ratio(imgs) > MAX_STRUCTURE_RATIO:
                        continue
                    if (len(offs), score) > (best[0], best[1]):
                        best = (len(offs), score, (offs, dims, (fmt, size), imgs))
    return best[2]


#: A 256-entry RGBA16 palette is this many bytes, and an actor's face frames begin right
#: after the one they use.
TLUT_BYTES = 0x200

#: how many frames of something else may sit between the palette and the table
MAX_SEED_SKIP = 2

#: how far to walk from the seed before giving up; the trim decides where the table really
#: ends, and no real table measured here runs longer than nine frames
SEED_FRAMES = 10


def _face_palette(data, skel, segments, segment):
    """The palette address the head names on *segment*, as an offset in the object file."""
    for i in skel.order():
        limb = skel.limbs[i]
        if not limb.dlist:
            continue
        try:
            res = f3dex2.run(limb.dlist, segments)
        except Exception:  # noqa: BLE001
            continue
        for b in res.batches:
            tile = b.tile
            if tile.addr is None or not tile.pal_addr:
                continue
            if ((tile.addr >> 24) & 0x0F) == segment:
                return tile.pal_addr & 0x00FFFFFF
    return None


def _tlut_for_segment(data, skel, segments, segment):
    """``(offset, decoded palette)`` for the palette the head names on *segment*.

    Falls back to a grey ramp only when the head names no palette at all - a true-colour
    face - in which case the palette is never consulted.
    """
    pal = _face_palette(data, skel, segments, segment) if segment is not None else None
    if pal is None or pal + TLUT_BYTES > len(data):
        return None, _grey_tlut()
    return pal, tex_mod.decode_tlut(data[pal:], 256)


def _seeded_runs(data, skel, segments, segment, tiles):
    """One candidate table per tile spec, seeded immediately after the face's own palette.

    For an actor with no entry in ``gActorOverlayTable`` there is no pointer array to read, so
    the offsets have to come from somewhere else.  The display list already names the palette
    the face is drawn with, and the frames that use a palette are stored directly after it:
    on four of the actors whose offsets were established by hand, the first eye sits at
    exactly ``palette + 0x200``, byte for byte.

    This is a **seed, not a search** - one deterministic candidate per tile spec, from an
    address the game itself states - so it does not widen the pool the way a scan would.  It
    is only consulted when the overlay route found nothing, and the ordinary gates and the
    per-frame trim still decide what survives: the walk deliberately runs past the end of the
    table and lets the trim cut it back.
    """
    pal = _face_palette(data, skel, segments, segment)
    if pal is None:
        return []
    start = pal + TLUT_BYTES
    runs = []
    for fmt, size, w, h in sorted(tiles):
        nbytes = w * h * BITS.get(size, 8) // 8
        if nbytes <= 0:
            continue
        offs = [start + k * nbytes for k in range(SEED_FRAMES)]
        offs = [o for o in offs if o + nbytes <= len(data)]
        if len(offs) >= 2 and offs not in runs:
            runs.append(offs)
    return runs


def _attested_faces(att, eye_segs, mouth_segs):
    """Build a FaceSet from offsets that were established by hand.

    Used for the few actors no rule reaches - see :mod:`n64rip.attested` for why each one is
    there.  It short-circuits the search entirely rather than competing with it, because the
    frames that were beating the right ones are real artwork and win on every measure.
    """
    eye = att.get("eyes")
    mouth = att.get("mouths")
    return face_mod.FaceSet(
        eyes=list(eye.offsets) if eye else [],
        mouths=list(mouth.offsets) if mouth else [],
        eye_size=(eye.width, eye.height) if eye else (32, 32),
        mouth_size=(mouth.width, mouth.height) if mouth else (32, 32),
        eye_fmt=(eye.fmt, eye.size) if eye else (tex_mod.FMT_CI, tex_mod.SIZE_8),
        mouth_fmt=(mouth.fmt, mouth.size) if mouth else (tex_mod.FMT_CI, tex_mod.SIZE_8),
        eye_segments=eye_segs or (face_mod.EYE_SEGMENT,),
        # A mouths-only attested row belongs on whatever segment the head actually
        # samples.  Object 316 samples one face segment and it is 8; defaulting to 9 binds
        # his mouth to a segment he never reads, and the face goes blank.
        mouth_segments=(mouth_segs
                        or (eye_segs if (mouth and not eye) else ())
                        or (face_mod.MOUTH_SEGMENT,)),
        eye_tlut=eye.tlut if eye else None,
        mouth_tlut=mouth.tlut if mouth else None,
    )


def _attribute_from_pool(data, pool, eye_segs, eye_tiles, skel, segments):
    """Which runtime-object actor draws this object?  The one whose code binds pictures.

    Every actor in *pool* is disassembled and asked what it binds to the eye segments; a
    candidate is kept only when it names at least two offsets that fit the object **and**
    decode, at the format the head requests and through the head's own palette, as something
    that passes the same picture gates as every other route.  Of four candidates for the
    second child Zelda, one passed - and it was her.

    Returns the winning actor's bindings as ``{segment: [offsets]}``, or ``{}``.  This is
    the code route only: offering the pool's pointer arrays by shape would be a search over a
    hundred and thirty overlays, and the whole history of this file says what that produces.
    """
    if not eye_segs or not eye_tiles:
        return {}
    _pal, tlut = _tlut_for_segment(data, skel, segments, eye_segs[0])
    best = (0.0, {})
    for ov, vram in pool:
        try:
            # unbounded on purpose: an actor that really draws this object never points past
            # its end, so a candidate with ANY binding outside the file is somebody else's -
            # even when the bindings that do fit decode as pictures.  That is how a Zelda
            # actor's table was pasted onto object 345 and read as its eyes.
            got = actor_mod.gsp_segments(ov, vram, 1 << 24)
        except Exception:  # noqa: BLE001
            continue
        if not got or any(o >= len(data) for offs_ in got.values() for o in offs_):
            continue
        offs: list[int] = []
        for s in eye_segs:
            for o in got.get(s, ()):
                if o not in offs:
                    offs.append(o)
        if len(offs) < 2:
            continue
        for fmt, size, w, h in sorted(eye_tiles):
            nbytes = w * h * BITS.get(size, 8) // 8
            if any(o + nbytes > len(data) for o in offs):
                continue
            imgs = _decode_table(data, offs, fmt, size, (w, h), tlut)
            if not imgs:
                continue
            if _roughness(imgs) > MAX_ROUGHNESS or _structure_ratio(imgs) > MAX_STRUCTURE_RATIO:
                continue
            score = _expression_score(data, offs, nbytes, imgs)
            if score > best[0]:
                best = (score, {s: list(v) for s, v in got.items() if v})
    return best[1]


def _coded_single(data, coded, segs, tiles, tlut, exclude):
    """A one-frame table, accepted only because the actor's code names it outright.

    Child Zelda has a single mouth texture: her Update stores `sMouthTextures[0]` and her Draw
    binds it, and the array has one entry.  Every other route needs two frames to compare, so
    a genuine one-frame table can never pass - but here the code has stated the binding, so
    the picture gates alone decide.
    """
    offs = [o for s in segs for o in coded.get(s, ()) if o not in exclude]
    if len(offs) != 1:
        return None
    for fmt, size, w, h in sorted(tiles):
        nbytes = w * h * BITS.get(size, 8) // 8
        if offs[0] + nbytes > len(data):
            continue
        imgs = _decode_table(data, offs, fmt, size, (w, h), tlut)
        if not imgs:
            continue
        if _roughness(imgs) > MAX_ROUGHNESS or _structure_ratio(imgs) > MAX_STRUCTURE_RATIO:
            continue
        if _one_dimensional(imgs[0]):
            continue  # a colour ramp is smooth enough to pass every gate, and it is not a mouth
        return (offs, (w, h), (fmt, size), imgs)
    return None


def _one_dimensional(img) -> bool:
    """Does this vary along only one axis?

    A drawn face varies in both directions.  A palette or a shading ramp varies in one, and
    is smooth enough to pass the roughness and structure gates - which is how two characters
    picked up a band of yellow-to-red as a single-frame mouth.  With one frame there is no
    neighbour to compare against, so the picture itself has to carry the evidence.
    """
    import numpy as np

    a = img[..., :3].astype(np.float64)
    if a.shape[0] < 2 or a.shape[1] < 2:
        return True
    dx = float(np.abs(np.diff(a, axis=1)).mean())
    dy = float(np.abs(np.diff(a, axis=0)).mean())
    hi = max(dx, dy)
    return hi < 1e-6 or min(dx, dy) < 0.05 * hi


def _overlay_faces(data, skel, segments, overlays, object_id):
    """This actor's own eye and mouth tables, read from its overlay's pointer runs.

    ``overlays`` maps an object id to ``[(overlay bytes, vram base)]``.

    Four routes, in order of how much they *know*.  The actor's own code, read by
    :func:`actor_code.gsp_segments`, states the binding outright.  A pointer array found by
    shape in the overlay is the same table without knowing which segment it feeds.  A walk
    seeded at the palette the head names is for actors with no overlay at all.  And a short
    attested table covers what none of those reach.

    Three measurements are combined, each taken where it is reliable.  The display list states
    the pixel *format* on segments 8 and 9, which is always explicit.  The size comes from
    whichever of the display list or the table's own spacing scores better, because either can
    be wrong: nothing was ever loaded on a missing face's segment, and not every table is
    packed.  Finally the winning table is cut where it stops correlating, which is where the
    eyes end and the mouths begin.
    """
    eye_segs, mouth_segs, eye_tiles, mouth_tiles = _face_roles(data, skel, segments)
    att = attested.for_object(object_id)
    if att and ("eyes" in att and "mouths" in att or object_id in attested.EXCLUSIVE):
        return _attested_faces(att, eye_segs, mouth_segs)  # nothing left for the routes to add
    if not overlays or object_id is None:
        return _attested_faces(att, eye_segs, mouth_segs) if att else None
    if not eye_tiles and not mouth_tiles:
        return None
    own = overlays.get(object_id, ())
    pool = overlays.get(None, ()) if not own else ()
    runs = []
    # what the actor's code binds to each segment - read from its gSPSegment calls, which is
    # the one place the binding is stated rather than implied.  Tried first, per role.
    coded: dict[int, list[int]] = {}
    for ov, vram in own:
        runs += [r for r in actor_mod.texture_runs(ov, len(data)) if r[-1] < len(data)]
        if vram:
            try:
                for seg, offs in actor_mod.gsp_segments(ov, vram, len(data)).items():
                    bucket = coded.setdefault(seg, [])
                    for o in offs:
                        if o not in bucket:
                            bucket.append(o)
            except Exception:  # noqa: BLE001 - a disassembly failure must not cost the data route
                pass
    if not own and pool:
        coded = _attribute_from_pool(data, pool, eye_segs, eye_tiles, skel, segments)

    def coded_runs(segs):
        out = []
        for s in segs:
            if len(coded.get(s, ())) >= 2 and coded[s] not in out:
                out.append(list(coded[s]))
        return out
    # Judge each candidate through the palette *that role* is drawn with.  A grey ramp makes
    # smooth art look like noise, and so does the wrong palette: the eye's palette applied to
    # the mouth made three characters' mouths - present in their pointer tables all along -
    # decode as confetti and fail every gate.
    eye_pal, tlut = _tlut_for_segment(data, skel, segments, eye_segs[0] if eye_segs else None)
    mouth_pal, mouth_tlut = _tlut_for_segment(
        data, skel, segments, mouth_segs[0] if mouth_segs else None)

    # Code first, data second: a table the actor's code indexes is exact, where a run found
    # by shape may be two tables end to end or carry entries that are not textures at all.
    eye = _best_table(data, coded_runs(eye_segs), eye_tiles, tlut) if coded else None
    if eye is None:
        eye = _best_table(data, runs, eye_tiles, tlut)
    # The seeded walk is a LAST RESORT, for an actor with no pointer table at all.  Offered to
    # an actor that has one it only adds noise: the walk is deliberately long, so scoring its
    # sub-spans hands "length first" a much bigger pool to win from, and characters whose real
    # table was already correct picked up seven frames of speckle apiece.
    # A code-route candidate that then fails the gates must not silence the seeded walk -
    # it did, and cost one character the eyes the walk had already found.
    seeded = not runs
    if eye is None and eye_tiles and seeded:
        eye = _best_table(data, _seeded_runs(data, skel, segments, eye_segs[0], eye_tiles),
                          eye_tiles, tlut, spans=True)
    eyes, spill = ([], [])
    eye_dims, eye_fmt = (32, 32), (tex_mod.FMT_CI, tex_mod.SIZE_8)
    if eye is not None:
        offs, eye_dims, eye_fmt, imgs = eye
        nbytes = eye_dims[0] * eye_dims[1] * BITS.get(eye_fmt[1], 8) // 8
        eyes, spill = _trim_table(data, offs, nbytes, imgs)

    mouth = None
    if mouth_tiles and coded:
        mouth = _best_table(data, coded_runs(mouth_segs), mouth_tiles, mouth_tlut,
                            exclude=set(eyes))
    if mouth is None and mouth_tiles:
        mouth = _best_table(data, runs, mouth_tiles, mouth_tlut, exclude=set(eyes))
    if mouth is None and mouth_tiles and coded:
        mouth = _coded_single(data, coded, mouth_segs, mouth_tiles, mouth_tlut, set(eyes))
    if mouth is None and mouth_tiles and mouth_segs and seeded:
        mouth = _best_table(data, _seeded_runs(data, skel, segments, mouth_segs[0], mouth_tiles),
                            mouth_tiles, mouth_tlut, exclude=set(eyes), spans=True)
    if mouth is not None:
        mouths, mouth_dims, mouth_fmt = mouth[0], mouth[1], mouth[2]
    elif spill:
        # The tail the eye table shed is the mouth table - but it has to be sized on its own
        # terms.  A mouth is neither the shape nor the size of an eye, and inheriting the
        # eye's dimensions is what left several characters' mouths striped.
        sized = _size_table(data, spill, mouth_tiles, eye_fmt, mouth_tlut)
        if sized is None:
            mouths, mouth_dims, mouth_fmt = [], (32, 32), (tex_mod.FMT_CI, tex_mod.SIZE_8)
        else:
            mouths, (mouth_dims, mouth_fmt) = spill, sized
    else:
        mouths, mouth_dims, mouth_fmt = [], (32, 32), (tex_mod.FMT_CI, tex_mod.SIZE_8)

    # An attested table overrides its own role only, so a character whose eyes the code
    # finds can still carry mouths that were established by hand, and vice versa.
    if att.get("eyes"):
        a = att["eyes"]
        eyes, eye_dims, eye_fmt, eye_pal = list(a.offsets), (a.width, a.height), (a.fmt, a.size), a.tlut
    if att.get("mouths"):
        a = att["mouths"]
        mouths, mouth_dims, mouth_fmt, mouth_pal = list(a.offsets), (a.width, a.height), (a.fmt, a.size), a.tlut
    if not eyes and not mouths:
        return None
    return face_mod.FaceSet(
        eyes=list(eyes), mouths=list(mouths),
        eye_size=eye_dims, mouth_size=mouth_dims,
        eye_fmt=eye_fmt, mouth_fmt=mouth_fmt,
        eye_segments=eye_segs or (face_mod.EYE_SEGMENT,),
        mouth_segments=mouth_segs or (face_mod.MOUTH_SEGMENT,),
        eye_tlut=eye_pal, mouth_tlut=mouth_pal,
    )


def _grey_tlut():
    """A neutral palette, used only to judge whether a candidate looks like an image.

    The real palette comes from the model's own display list at decode time; here we only
    need to tell a picture from a flat block of padding.
    """
    import numpy as np

    ramp = np.arange(256, dtype=np.uint8)
    return np.stack([ramp, ramp, ramp, np.full(256, 255, np.uint8)], axis=-1)


def _face_tlut(data, skel, segments, prefer_face=True):
    """The palette the face textures are drawn with.

    A colour-indexed face needs a TLUT, and the display list already names it - so rather than
    guessing where the palette lives, take the one the head pointed at.

    **Which tile is asked matters.** Taking the first colour-indexed tile in limb order
    returns a body or hair palette, and the model itself does not use it - `zobj` decodes each
    tile with that tile's own palette - so only the PNGs written beside the model came out
    wrong, in somebody else's colours. With segments 8 and 9 bound, the face tiles resolve
    like any other, so the face's palette is simply the one on a face tile.
    """
    fallback = None
    for i in skel.order():
        limb = skel.limbs[i]
        if not limb.dlist:
            continue
        try:
            res = f3dex2.run(limb.dlist, segments)
        except Exception:  # noqa: BLE001
            continue
        for b in res.batches:
            tile = b.tile
            if tile.fmt != tex_mod.FMT_CI or tile.pal_addr is None or tile.addr is None:
                continue
            got = segments.resolve(tile.pal_addr)
            if not got:
                continue
            buf, off = got
            tlut = tex_mod.decode_tlut(buf[off:], 256)
            on_face = ((tile.addr >> 24) & 0x0F) in (face_mod.EYE_SEGMENT,
                                                     face_mod.MOUTH_SEGMENT)
            if on_face or not prefer_face:
                return tlut
            if fallback is None:
                fallback = tlut
    return fallback


def _expression_variants(scene, name, data, skel, segments, faces, world, rotations,
                         attachments=None):
    """Add every other expression to *scene* as an alternate of the face primitive.

    The model ships wearing expression 0.  The rest are attached as variant primitives, which
    the exporter writes as their own nodes and the Blender add-on turns into one keyframeable
    integer per face part - so an animator scrubs between eye states the way they would a
    shape key.  A shape key itself cannot do this: the expressions are texture swaps, and
    nothing about the geometry changes between them.
    """
    import numpy as np

    count = max(len(faces.eyes), len(faces.mouths))
    if count < 2:
        return scene
    base_mats = list(scene.materials)
    base_triangles = scene.triangles  # fixed up front: `scene` grows as variants are added
    scene.extras["base_triangles"] = base_triangles
    for k in range(1, count):
        bound = face_mod.segments_for(faces, data, k, k)
        if not bound:
            continue
        segs = f3dex2.Segments({**segments.bases, **bound})
        try:
            alt = zobj.build(name, data, skel, segs, world=world, rotations=rotations, attachments=attachments)
        except Exception:  # noqa: BLE001
            continue
        # the display lists are the same, so material i means the same tile in both builds;
        # anything else and the two are not comparable and the variant is dropped
        if len(alt.materials) != len(base_mats) or alt.triangles != base_triangles:
            continue
        for mi, (m0, mk) in enumerate(zip(base_mats, alt.materials)):
            if not (m0.texture and mk.texture):
                continue
            a, b = scene.textures.get(m0.texture), alt.textures.get(mk.texture)
            if a is None or b is None or (a.shape == b.shape and np.array_equal(a, b)):
                continue  # this material is not part of the face
            tex_name = f"{m0.texture}_expr{k}"
            scene.textures[tex_name] = b
            scene.materials.append(replace(mk, name=f"{m0.name}_expr{k}", texture=tex_name))
            new_mat = len(scene.materials) - 1
            for prim in alt.primitives:
                if prim.material != mi:
                    continue
                scene.primitives.append(replace(
                    prim, material=new_mat,
                    variant_of=m0.name, variant_texture=f"expr_{k:02d}",
                ))
    return scene


def _faces(scene, name, data, skel, segments, code, out_dir, world, rotations,
           object_id=None, overlays=None, attachments=None):
    """Bind a face and write every expression beside the model.

    A character's face is swapped at runtime through segments 8 and 9, so a static rip leaves
    it blank.  Binding expression 0 fills it in; writing the rest as PNGs next to the model
    lets a rigger switch expression by pointing the material at a different image - which is
    what a texture swap needs, since morph targets deform geometry and cannot do this.
    """
    unresolved = set(scene.extras.get("unresolved_segments") or ())
    if not (unresolved & set(face_mod.FACE_SEGMENTS)) or not code:
        return scene, []
    # Where the face textures come from depends on the actor.  Link keeps his in an evenly
    # spaced array that a stride walk finds in `code`.  Almost no NPC does - theirs sit in
    # their own actor overlay as a plain run of segmented pointers, which is readable because
    # segmented addresses are never relocated.  Binding Link's offsets into someone else's
    # object file is what made every other character glitchy, so each actor gets its own.
    faces = None
    if object_id in LINK_OBJECTS:
        found = face_mod.find_faces(code, len(data))
        if face_mod.owns_table(data, found):
            faces = found
    if faces is None:
        faces = _overlay_faces(data, skel, segments, overlays, object_id)
    if faces is None:
        return scene, []
    bound = face_mod.segments_for(faces, data, 0, 0)
    if not bound:
        return scene, []
    seg2 = f3dex2.Segments({**segments.bases, **bound})
    try:
        rebuilt = zobj.build(name, data, skel, seg2, world=world, rotations=rotations, attachments=attachments)
    except Exception:  # noqa: BLE001
        return scene, []
    # A face binding is a TEXTURE binding: it must never change geometry or lose textures.
    # Without this gate the rebuild was accepted whenever it had any primitives at all, and
    # display lists that call through segments 8/9 then execute face-texture bytes as a
    # display list - injecting 95,005 junk triangles across the ROM, about 65% of everything
    # we were shipping, and costing 8 models textures they already had.
    def _textured(sc):
        return sum(1 for m in sc.materials if m.texture)

    def _unresolved(sc):
        return set(sc.extras.get("unresolved_segments") or ())

    if not rebuilt.primitives:
        return scene, []
    if rebuilt.triangles != scene.triangles:
        return scene, []
    if _textured(rebuilt) < _textured(scene):
        return scene, []
    if len(_unresolved(rebuilt)) > len(_unresolved(scene)):
        return scene, []

    rebuilt = _expression_variants(rebuilt, name, data, skel, segments, faces, world, rotations,
                                   attachments=attachments)
    written: list[str] = []
    from PIL import Image

    def _tlut(pal, segs):
        if pal is not None and pal + TLUT_BYTES <= len(data):
            return tex_mod.decode_tlut(data[pal:], 256)
        # Link's path does not record a palette; take the one the head names for the segment
        return _tlut_for_segment(data, skel, seg2, segs[0] if segs else None)[1]

    tex_dir = Path(out_dir) / f"{name}_tex"
    for kind, offs, (w, h), (fmt, size), tlut in (
        ("eye", faces.eyes, faces.eye_size, faces.eye_fmt,
         _tlut(faces.eye_tlut, faces.eye_segments)),
        ("mouth", faces.mouths, faces.mouth_size, faces.mouth_fmt,
         _tlut(faces.mouth_tlut, faces.mouth_segments)),
    ):
        if not offs:
            continue
        tex_dir.mkdir(parents=True, exist_ok=True)
        for k, off in enumerate(offs):
            try:
                img = tex_mod.decode(fmt, size, w, h, data[off:], tlut, 0)
            except Exception:  # noqa: BLE001
                continue
            fname = f"face_{kind}_{k}.png"
            Image.fromarray(img).save(tex_dir / fname)
            written.append(fname)
    return rebuilt, written


def extract_rom(
    rom: Rom,
    out_dir: Path,
    *,
    limit: int | None = None,
    progress=None,
) -> dict:
    """Export every skeleton-bearing file in *rom*.  Returns the rip_results dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    models: list[ModelResult] = []
    # The game's object table says which files are objects and which is gameplay_keep, and it
    # validates against the DMA table, so nothing outside the ROM is needed to find it.
    table = obj_mod.find_object_table(rom)
    shared = obj_mod.keep_segments(rom, table)
    object_ids: dict[int, int] = {}
    if table is not None:
        for oid, fidx in enumerate(table.entries):
            if fidx is not None:
                object_ids.setdefault(fidx, oid)
    # Link keeps no animations in his object file - his live in their own uncompressed one,
    # so posing him needs a separate source from every other actor.
    code_file = None if table is None else rom.read(rom.files[table.file_index])
    # object id -> the bytes of every actor overlay that uses it, for per-actor face textures
    overlays: dict[int, list[tuple[bytes, int]]] = {}
    # Actors whose ActorInit names gameplay_keep, or nothing we recognised, pick their object
    # at runtime - the second child Zelda and one of the Deku Scrubs are drawn by such
    # actors.  Nothing in the data says which; their *code* does, so this pool is offered to
    # any object no actor claims, through the code route only.
    unclaimed_pool: list[tuple[bytes, int]] = []
    if code_file is not None:
        bases = obj_mod.actor_overlay_bases(rom, code_file)
        by_object = obj_mod.find_actor_overlays(rom, code_file)
        for oid, files in by_object.items():
            for fidx in files:
                try:
                    overlays.setdefault(oid, []).append((rom.read(rom.files[fidx]), bases.get(fidx, 0)))
                except Exception:  # noqa: BLE001
                    pass
        claimed = {f for fs in by_object.values() for f in fs}
        runtime = set(by_object.get(obj_mod.GAMEPLAY_KEEP, [])) | (set(bases) - claimed)
        for fidx in sorted(runtime):
            if bases.get(fidx):
                try:
                    unclaimed_pool.append((rom.read(rom.files[fidx]), bases[fidx]))
                except Exception:  # noqa: BLE001
                    pass
        overlays[None] = unclaimed_pool

    # the shared objects an attested rest pose reads its animation from
    rest_banks: dict[int, bytes] = {}
    # Both tables, or an object-keyed override names a bank that is never loaded and the
    # override is a silent no-op.
    for bank_oid in ({rp.bank for rp in attested.REST_POSES.values()}
                     | {rp.bank for rp in attested.REST_POSES_BY_OBJECT.values()}):
        bfi = table.file_for(bank_oid) if table is not None else None
        if bfi is not None:
            try:
                rest_banks[bank_oid] = rom.read(rom.files[bfi])
            except Exception:  # noqa: BLE001
                pass

    link_anim = None
    for f in rom.live:
        if not f.compressed and 2_000_000 < f.size < 3_000_000:
            try:
                link_anim = rom.read(f)
            except Exception:  # noqa: BLE001
                link_anim = None
            break
    files = rom.live[:limit] if limit else rom.live
    for n, f in enumerate(files):
        if progress and n % 50 == 0:
            progress(n, len(files), len(models))
        if f.size < 128:
            continue
        try:
            data = rom.read(f)
        except Exception as exc:  # noqa: BLE001 - a bad entry must not stop the rip
            continue
        try:
            skels = skel_mod.find_skeletons(data)
        except Exception as exc:  # noqa: BLE001
            models.append(ModelResult(f.label, f.index, f"{f.vrom_start:#x}",
                                      error=f"skeleton scan: {exc}"))
            continue
        if not skels:
            continue
        segments = f3dex2.Segments({6: data, **shared})
        for si, sk in enumerate(skels):
            name = f.label if len(skels) == 1 else f"{f.label}_skel{si}"
            res = ModelResult(name, f.index, f"{f.vrom_start:#x}", limbs=sk.count)
            res.object_id = object_ids.get(f.index)
            # Lists the actor draws on a limb outside the skeleton - hair, hats, held items -
            # read from its own code.  The first list per limb is what it draws by default.
            attach = []
            for ov, vram in overlays.get(res.object_id, ()) if res.object_id is not None else ():
                if not vram:
                    continue
                try:
                    for limb_i, dls in actor_mod.attachments(ov, vram, len(data)):
                        if dls and not any(a[0] == limb_i for a in attach):
                            attach.append((limb_i, dls[0]))
                except Exception:  # noqa: BLE001
                    pass
            try:
                scene = zobj.build(name, data, sk, segments, attachments=attach,
                                   null_limbs=attested.null_limbs(res.object_id))
            except Exception as exc:  # noqa: BLE001
                res.error = f"{type(exc).__name__}: {exc}"
                models.append(res)
                continue
            # A skeleton on its own has every joint at identity, so its chains run along one
            # axis - Link comes out 45.9 wide and 23.3 tall.  Frame 0 of a rest animation is
            # the pose the model was authored in.  Applying it is gated on the result actually
            # standing up, because not every animation in a file is a rest pose.
            posed = _pose(scene, name, data, sk, segments, link_anim, res.object_id, attach,
                          rest_banks)
            world = rotations = None
            if posed is not None:
                scene, world, rotations = posed
                res.posed = True
            if scene.triangles < MIN_TRIANGLES:
                continue
            scene, res.expressions = _faces(
                scene, name, data, sk, segments, code_file, out_dir, world, rotations,
                res.object_id, overlays, attach,
            )
            base = out_dir / name
            try:
                st = gltf.export(scene, base, thumbnail=True)
                thumb = gltf.thumbnail(st, base, size=256)
            except Exception as exc:  # noqa: BLE001
                res.error = f"export: {type(exc).__name__}: {exc}"
                models.append(res)
                continue
            res.out_rel = f"{name}.gltf"
            res.thumb = f"{name}_thumb.png" if thumb else ""
            res.triangles = scene.extras.get("base_triangles", scene.triangles)
            res.vertices = scene.vertices
            res.textures = len(scene.textures)
            res.textures_missing = int(scene.extras.get("textures_missing", 0))
            res.drawn_limbs = int(scene.extras.get("drawn_limbs", 0))
            res.unresolved_segments = list(scene.extras.get("unresolved_segments", []))
            res.warnings = list(scene.warnings)
            models.append(res)
    ok = [m for m in models if m.out_rel]
    # The props: every object file that exported no skeleton model - chests, doors, signs,
    # pots, tents - found by the vertex-load gate in n64rip.static.  This includes the eight
    # files whose "skeleton" is a false positive (limb pointers that are raw small integers).
    from n64rip import static as static_mod

    exported_files = {m.file_index for m in ok}
    prop_rows: list[dict] = []
    if table is not None:
        for fidx in sorted(table.object_files - exported_files):
            f = rom.files[fidx]
            if f.size < 128:
                continue
            oid = object_ids.get(fidx)
            seg = static_mod.home_segment(oid)
            name = f"{f.label}_static"
            row = {"name": name, "file_index": fidx, "vrom": f"{f.vrom_start:#x}", "kind": "prop",
                   "object_id": oid, "limbs": 0, "posed": False, "expressions": [], "out_rel": "",
                   "thumb": "", "triangles": 0, "vertices": 0, "textures": 0,
                   "textures_missing": 0, "drawn_limbs": 0, "unresolved_segments": [],
                   "warnings": [], "error": "", "roots": 0}
            try:
                data = rom.read(f)
                segs = f3dex2.Segments({seg: data, **{k: v for k, v in shared.items() if k != seg}})
                sc, roots = static_mod.build(name, data, segs, seg)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {exc}"
                prop_rows.append(row)
                continue
            if sc.triangles < MIN_TRIANGLES:
                continue
            base = out_dir / name
            try:
                st = gltf.export(sc, base, thumbnail=True)
                thumb = gltf.thumbnail(st, base, size=256)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"export: {type(exc).__name__}: {exc}"
                prop_rows.append(row)
                continue
            row.update({"out_rel": f"{name}.gltf", "thumb": f"{name}_thumb.png" if thumb else "",
                        "triangles": sc.triangles, "vertices": sc.vertices,
                        "textures": len(sc.textures),
                        "textures_missing": int(sc.extras.get("textures_missing", 0)),
                        "roots": len(roots), "warnings": list(sc.warnings)})
            prop_rows.append(row)
    # The levels.  Every scene of the game, one glTF each, rooms as nodes, collision and
    # placements riding along.  A separate route because a room has no skeleton to hang on.
    from n64rip import level as level_mod

    level_rows = level_mod.extract_levels(rom, table, out_dir, progress=None)
    report = {
        "rom": rom.name,
        "title": rom.title,
        "code": rom.code,
        "crc": f"{rom.crc1:08x}/{rom.crc2:08x}",
        "seconds": round(time.time() - t0),
        "files": len(rom.files),
        "object_table": None if table is None else {
            "offset": table.offset,
            "in_file": table.file_index,
            "slots": len(table.entries),
            "object_files": len(table.object_files),
            "gameplay_keep": table.file_for(obj_mod.GAMEPLAY_KEEP),
        },
        "models": [asdict(m) for m in models] + prop_rows + level_rows,
        "totals": {
            "exported": len(ok),
            "triangles": sum(m.triangles for m in ok),
            "textures": sum(m.textures for m in ok),
            "textures_missing": sum(m.textures_missing for m in ok),
            "rigged": sum(1 for m in ok if m.limbs > 1),
            "failed": sum(1 for m in models if m.error) + sum(1 for r in level_rows if r["error"]),
            "props": sum(1 for r in prop_rows if r["out_rel"]),
            "prop_triangles": sum(r["triangles"] for r in prop_rows),
            "levels": sum(1 for r in level_rows if r["out_rel"]),
            "level_triangles": sum(r["triangles"] for r in level_rows),
            "collision_polygons": sum(r["collision_polygons"] for r in level_rows),
        },
    }
    (out_dir / "rip_results.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
