"""Guess the humanoid core of any skeleton from joint names + hierarchy.

``rig.standard_bones`` knows Nintendo's J3D naming.  Everything else in the library
(EA's ``LCollarBone/LArm/LForearm/LHand``, Radical's ``Pelvis/Hip_L/Knee_L/Ankle_L``,
Maya-style ``ShoulderLeft/ElbowLeft/WristLeft`` ...) names its joints after the *joint*
rather than the bone, sprinkles twist/IK helpers between them, and parents the legs
wherever it likes.  So this mapper is structural: it finds the hands, feet and head by
keyword, walks the hierarchy from there, and skips helper joints by name.  Only the
Mixamo core comes out (hips, spine chain, neck, head, shoulders, arms, hands, legs, feet,
toes); everything else keeps its name.

Pure Python - shared verbatim with the Blender add-on, which runs it on an armature.
"""

from __future__ import annotations

import re

# token -> role.  Roman-ised Japanese included for the Nintendo rigs the J3D mapper misses.
_ROLES: dict[str, str] = {}
for _role, _toks in {
    "hand": ("hand", "wrist", "palm", "te", "tekubi"),
    "foot": ("foot", "ankle", "asi", "ashi", "asikubi", "ashikubi"),
    "toe": ("toe", "toes", "toebase", "ball", "tsumasaki", "tumasaki"),
    "head": ("head", "atama"),
    "neck": ("neck", "kubi"),
    "clavicle": ("clavicle", "clav", "collar", "collarbone", "kata", "sakotu"),
    "shoulder": ("shoulder",),
    "upperarm": ("upperarm", "uparm", "humerus", "bicep", "biceps", "arm", "ude"),
    "forearm": ("forearm", "forarm", "lowerarm", "loarm", "elbow", "hiji", "radius", "ulna"),
    "hips": ("hips", "pelvis", "koshi", "waist"),
    "spine": ("spine", "chest", "torso", "mune", "abdomen", "stomach", "belly", "sternum", "body"),
    "upleg": ("thigh", "upleg", "upperleg", "femur", "momo", "leg", "hip"),
    "lowerleg": ("knee", "shin", "calf", "lowerleg", "loleg", "tibia", "hiza", "sune"),
}.items():
    for _t in _toks:
        _ROLES[_t] = _role

_HELPER = {
    "twist", "roll", "con", "off", "handle", "ik", "fk", "pole", "target", "nub", "end",
    "eff", "effector", "helper", "attach", "dummy", "null", "locator", "top", "tip", "hoop",
    "shape", "mesh", "geo",
}  # fmt: skip
_SIDE = {"left": "L", "right": "R", "l": "L", "r": "R", "lt": "L", "rt": "R"}
_CORE = {"Hips", "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
         "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"}  # fmt: skip
_TORSO = {"hips", "spine", "neck", "head"}

_SPLIT = re.compile(
    r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)


def tokens(name: str) -> list[str]:
    """'LCollarBone' -> ['l', 'collar', 'bone']; 'J_Leg_L2_Knee' -> ['j','leg','l','2','knee']."""
    out = []
    for t in _SPLIT.split(name):
        if not t:
            continue
        t = t.lower()
        # 'larm', 'rhand', 'lfoot': side letter glued to a keyword
        if t not in _ROLES and t[:1] in ("l", "r") and t[1:] in _ROLES:
            out += [t[0], t[1:]]
        else:
            out.append(t)
    return out


class _J:
    __slots__ = ("i", "name", "parent", "children", "toks", "side", "roles", "helper", "depth")

    def __init__(self, i, name, parent):
        self.i, self.name, self.parent, self.children = i, name, parent, []
        self.toks = tokens(name)
        sides = [_SIDE[t] for t in self.toks if t in _SIDE]
        self.side = sides[0] if sides else None
        self.roles = {_ROLES[t] for t in self.toks if t in _ROLES}
        if "hip" in self.toks:  # 'HipR' is a thigh, 'Hip' is the pelvis
            self.roles.discard("upleg")
            self.roles.add("upleg" if self.side else "hips")
        self.helper = any(t in _HELPER for t in self.toks)
        self.depth = 0


def _build(names, parents):
    js = [_J(i, n, p) for i, (n, p) in enumerate(zip(names, parents, strict=True))]
    for j in js:
        if j.parent is not None and 0 <= j.parent < len(js) and j.parent != j.i:
            js[j.parent].children.append(j.i)
        else:
            j.parent = None
    for j in js:  # depth (parents may come after children in node order)
        d, p = 0, j.parent
        while p is not None and d < len(js):
            d, p = d + 1, js[p].parent
        j.depth = d
    return js


def _ancestors(js, i):
    out, p = [], js[i].parent
    while p is not None and len(out) < len(js):
        out.append(p)
        p = js[p].parent
    return out


def _pick_end(js, role, side, prefer):
    """The hand / foot joint of one side: a sided, non-helper joint carrying ``role``.
    Of a parent/child pair (Wrist > Palm) the parent wins; then the one at the end of the
    longest same-side chain (the real ankle sits under Hip_L/Knee_L, an IK handle named
    Left_Foot hangs off the root), then the one under a torso joint, then the preferred
    keyword, then the shallower one."""
    cands = [j for j in js if role in j.roles and j.side == side and not j.helper]
    if not cands:
        return None
    anc = {j.i: _ancestors(js, j.i) for j in cands}
    cands = [j for j in cands if not any(o.i in anc[j.i] for o in cands)]

    def key(j):
        sided = sum(1 for a in anc[j.i] if js[a].side == side)
        torso = any(js[a].roles & {"hips", "spine"} for a in anc[j.i])
        return (-sided, not torso, not any(t in prefer for t in j.toks), j.depth, j.i)

    cands.sort(key=key)
    return cands[0]


def _nca(js, idxs):
    """Nearest common ancestor (or self) of the given joints, or None."""
    paths = [[i, *_ancestors(js, i)] for i in idxs]
    common = set(paths[0])
    for p in paths[1:]:
        common &= set(p)
    return next((js[i] for i in paths[0] if i in common), None)


def _chain(js, start, side):
    """Non-helper ancestors of ``start`` up to (excluding) the torso / the other side."""
    out = []
    for a in _ancestors(js, start.i):
        j = js[a]
        if j.roles & _TORSO or (j.side and j.side != side):
            break
        if not j.helper:
            out.append(j)
        if len(out) >= 6:
            break
    return out


def guess_bones(names: list[str], parents: list[int | None]) -> dict[int, str]:
    """{joint index: Mixamo bone name (no prefix)} for the humanoid core, or as much of it
    as the skeleton exposes; ``{}`` when it is clearly not a biped."""
    js = _build(list(names), list(parents))
    if len(js) < 8:
        return {}
    out: dict[int, str] = {}
    uplegs = []
    for side, word in (("L", "Left"), ("R", "Right")):
        hand = _pick_end(js, "hand", side, ("hand", "wrist"))
        if hand is not None:
            out[hand.i] = f"{word}Hand"
            chain = _chain(js, hand, side)
            fore = next((j for j in chain if "elbow" in j.toks), None) or next(
                (j for j in chain if "forearm" in j.roles), None
            )
            if fore is None and chain:
                fore = chain[0]
            if fore is not None:
                out[fore.i] = f"{word}ForeArm"
                rest = chain[chain.index(fore) + 1 :]
                # the upper arm: next plain joint; on joint-named rigs the sided shoulder
                # joint itself is where the upper arm starts
                arm = next((j for j in rest if "clavicle" not in j.roles), None) or next(
                    (j for j in rest if j.side == side), None
                )
                if arm is not None:
                    out[arm.i] = f"{word}Arm"
                    after = rest[rest.index(arm) + 1 :]
                    sh = next(
                        (j for j in after if j.roles & {"clavicle", "shoulder"} and j.i not in out),
                        None,
                    )
                    if sh is not None:
                        out[sh.i] = f"{word}Shoulder"
        foot = _pick_end(js, "foot", side, ("foot", "ankle"))
        if foot is not None:
            out[foot.i] = f"{word}Foot"
            toe = next((js[c] for c in foot.children if "toe" in js[c].roles), None)
            if toe is not None:
                out[toe.i] = f"{word}ToeBase"
            chain = _chain(js, foot, side)
            low = next((j for j in chain if "knee" in j.toks), None) or next(
                (j for j in chain if "lowerleg" in j.roles), None
            )
            if low is None and chain:
                low = chain[0]
            if low is not None:
                out[low.i] = f"{word}Leg"
                rest = chain[chain.index(low) + 1 :]
                up = next((j for j in rest if "upleg" in j.roles), None) or (
                    rest[0] if rest else None
                )
                if up is not None:
                    out[up.i] = f"{word}UpLeg"
                    uplegs.append(up)
    # head + neck
    heads = [j for j in js if "head" in j.roles and not j.helper and not j.side]
    # the body's head hangs under a neck/spine/hips joint; a mesh node called
    # "headShape" at the root does not
    heads.sort(
        key=lambda j: (not any(js[a].roles & _TORSO for a in _ancestors(js, j.i)), j.depth, j.i)
    )
    head = heads[0] if heads else None
    neck = None
    if head is not None:
        out[head.i] = "Head"
        neck = next((js[a] for a in _ancestors(js, head.i) if "neck" in js[a].roles), None)
        if neck is not None:
            out[neck.i] = "Neck"
    top = neck or head
    # hips = where the legs and the torso meet (Mixamo: Hips parents Spine + both UpLegs);
    # without legs, the joint named pelvis/hips
    hips = None
    if len(uplegs) == 2:
        hips = _nca(js, [u.i for u in uplegs] + ([top.i] if top is not None else []))
        if hips is not None and hips.i in out:  # one thigh parents the other: use its parent
            hips = js[hips.parent] if hips.parent is not None else None
    if hips is None:
        hips = next((j for j in js if "hips" in j.roles and not j.side and not j.helper), None)
    if hips is not None:
        out[hips.i] = "Hips"
    # spine chain: the joints between the hips and the neck, evenly picked into Spine/1/2
    if top is not None and hips is not None:
        spine = []
        for a in _ancestors(js, top.i):
            j = js[a]
            if j.i == hips.i:
                break
            if j.helper or j.side or j.roles & {"clavicle", "shoulder", "upperarm", "neck", "head"}:
                continue
            spine.append(j)
        spine.reverse()  # hips -> neck order
        spine = [j for j in spine if j.i not in out]
        picks = [spine[0], spine[len(spine) // 2], spine[-1]] if len(spine) >= 3 else spine
        for j, n in zip(picks, ("Spine", "Spine1", "Spine2"), strict=False):
            out[j.i] = n
    elif hips is not None:  # no head: take the spine-named joints going up
        sp = [j for j in js if "spine" in j.roles and not j.side and not j.helper]
        sp = [j for j in sp if j.i not in out]
        sp.sort(key=lambda j: (j.depth, j.i))
        for j, n in zip(sp[:3], ("Spine", "Spine1", "Spine2"), strict=False):
            out[j.i] = n
    return out


def is_humanoid(std: dict) -> bool:
    """The core Mixamo set (hips, both arms + hands, both legs + feet) is all there."""
    return set(std.values()) >= _CORE


def humanoid_hint(names) -> bool:
    """Names-only guess (no hierarchy): both hands, both feet and a torso keyword."""
    seen = set()
    for n in names:
        toks = tokens(n)
        if any(t in _HELPER for t in toks):
            continue
        side = next((_SIDE[t] for t in toks if t in _SIDE), None)
        for t in toks:
            r = _ROLES.get(t)
            if r in ("hand", "foot") and side:
                seen.add(f"{r}{side}")
            elif r in _TORSO:
                seen.add("torso")
    return {"handL", "handR", "footL", "footR", "torso"} <= seen
