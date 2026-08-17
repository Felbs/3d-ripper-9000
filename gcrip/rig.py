"""Map J3D joint names onto a standard humanoid bone naming (Mixamo convention).

Nintendo's J3D models use consistent but game-specific joint names (``LarmA_jnt``,
``armL1``, ``udeL1``, ``arm_L1`` ...). Retargeting tools and animation libraries
(Mixamo, most Blender retargeters) match bones by name, so we derive the standard
name for the main humanoid chain: hips, spine, neck, head, shoulders, arms, hands,
legs, feet, toes.

The mapping is mostly structural: hands/feet/head are found by keyword, then the
arm/leg/spine chains are walked up the hierarchy from those, which is far more
robust than trying to interpret every intermediate joint name.

Only the humanoid core is mapped; fingers, hair, clothing and weapon bones keep
their original names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gcrip.formats import j3d

MIXAMO_PREFIX = "mixamorig:"

# keyword -> role. Roman-ised Japanese equivalents included (Nintendo EAD naming).
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hand": ("hand", "wrist", "te", "tekubi"),
    "foot": ("foot", "ankle", "asi", "ashi", "asikubi"),
    "toe": ("toe", "tsumasaki", "tumasaki", "footend"),
    "head": ("head", "atama"),
    "neck": ("neck", "kubi"),
    "shoulder": ("shoulder", "clavicle", "kata"),
    "arm": ("arm", "ude", "elbow", "hiji"),
    "leg": ("leg", "knee", "hiza", "sune", "momo", "thigh", "shin", "clotch", "crotch"),
}
_ROLE_OF_TOKEN = {tok: role for role, toks in _KEYWORDS.items() for tok in toks}

_STRIP_SUFFIX = re.compile(r"(_?jnt|_?bone|_?joint|_?loc)$")
_UPPER_LEG = ("momo", "thigh")


def _has_keyword(s: str) -> bool:
    if s[:1] in ("l", "r") and any(s[1:].startswith(t) for t in _ROLE_OF_TOKEN):
        return True
    return any(s.startswith(t) for t in _ROLE_OF_TOKEN)


@dataclass
class _Info:
    side: str | None  # "L", "R" or None
    role: str | None
    base: str  # cleaned keyword token


def _classify(name: str) -> _Info:
    n = name.lower()
    n = _STRIP_SUFFIX.sub("", n)
    m = re.match(r"^([a-z]{1,3})_(?=[a-z])", n)  # model prefix: cl_, zl_, ...
    if m and m.group(1) not in _ROLE_OF_TOKEN and _has_keyword(n[m.end() :]):
        n = n[m.end() :]
    side = None
    m = re.search(r"(^|[_\W])(left|right)([_\W\d]|$)", n)
    if m:
        side = "L" if m.group(2) == "left" else "R"
        n = n[: m.start()] + n[m.end() :]
    else:
        # leading side letter (Lshoulder, RarmA) or trailing one (armL1, hand_r, momorR)
        lead = re.match(r"^([lr])(?=[a-z]{3,})", n)
        trail = re.search(r"_?([lr])(?=(?:end|[\d]|[a-c])?$)", n)
        if lead and _has_keyword(n[1:]):
            side = lead.group(1).upper()
            n = n[1:]
        elif trail and len(n) > 2:
            side = trail.group(1).upper()
            n = n[: trail.start()] + n[trail.end() :]
    base = re.sub(r"[\d_]+$", "", n)
    base = re.sub(r"[a-c]$", "", base) if base[:-1] in _ROLE_OF_TOKEN else base
    role = None
    for tok, r in sorted(_ROLE_OF_TOKEN.items(), key=lambda kv: -len(kv[0])):
        if base == tok or base.startswith(tok) and len(base) - len(tok) <= 1:
            role = r
            break
    return _Info(side, role, base)


def _ancestors(joints: list[j3d.Joint], i: int) -> list[int]:
    out = []
    p = joints[i].parent
    while p is not None:
        out.append(p)
        p = joints[p].parent
    return out


def standard_bones(joints: list[j3d.Joint]) -> dict[int, str]:
    """Return {joint index: standard name (no prefix)} for recognised humanoid joints,
    e.g. {1: "Hips", 3: "Spine", 8: "LeftHand"}. Empty for non-humanoids."""
    if len(joints) < 6:
        return {}
    info = {j.index: _classify(j.name) for j in joints}
    out: dict[int, str] = {}

    def first(role: str, side: str | None) -> int | None:
        for j in joints:
            inf = info[j.index]
            if inf.role == role and inf.side == side and j.index not in out:
                return j.index
        return None

    for side, word in (("L", "Left"), ("R", "Right")):
        hand = first("hand", side)
        if hand is not None:
            out[hand] = f"{word}Hand"
            p = joints[hand].parent
            # forearm, upper arm: nearest two ancestors carrying the arm role
            arm_chain = [a for a in _ancestors(joints, hand) if info[a].role == "arm"][:2]
            if len(arm_chain) == 2:
                out[arm_chain[0]] = f"{word}ForeArm"
                out[arm_chain[1]] = f"{word}Arm"
                sh = joints[arm_chain[1]].parent
                if sh is not None and info[sh].role == "shoulder" and sh not in out:
                    out[sh] = f"{word}Shoulder"
            elif len(arm_chain) == 1 and p is not None:
                out[arm_chain[0]] = f"{word}Arm"
        foot = first("foot", side)
        if foot is not None:
            out[foot] = f"{word}Foot"
            for c in joints[foot].children:
                if info[c].role == "toe" and c not in out:
                    out[c] = f"{word}ToeBase"
                    break
            leg_chain = [a for a in _ancestors(joints, foot) if info[a].role == "leg"]
            thigh = next((a for a in leg_chain if info[a].base.startswith(_UPPER_LEG)), None)
            if thigh is not None and leg_chain.index(thigh) > 0:
                out[thigh] = f"{word}UpLeg"
                out[leg_chain[leg_chain.index(thigh) - 1]] = f"{word}Leg"
            elif len(leg_chain) >= 2:
                out[leg_chain[0]] = f"{word}Leg"
                out[leg_chain[1]] = f"{word}UpLeg"
            elif len(leg_chain) == 1:
                out[leg_chain[0]] = f"{word}UpLeg"

    head = first("head", None)
    if head is not None:
        out[head] = "Head"
        p = joints[head].parent
        if p is not None and info[p].role == "neck":
            out[p] = "Neck"
    neck = next((i for i, n in out.items() if n == "Neck"), None)

    # Hips: lowest common ancestor of the two up-legs and the neck/head chain.
    top = neck if neck is not None else head
    uplegs = [i for i, n in out.items() if n.endswith("UpLeg")]
    anchors = [a for a in uplegs + ([top] if top is not None else []) if a is not None]
    if len(anchors) >= 2:
        chains = [[a] + _ancestors(joints, a) for a in anchors]
        common = set(chains[0])
        for c in chains[1:]:
            common &= set(c)
        # deepest common ancestor = the first one met walking up from anchor 0
        hips = next((a for a in chains[0] if a in common), None)
        if hips is not None and hips not in out:
            out[hips] = "Hips"
            if top is not None:
                anc = _ancestors(joints, top)
                spine = anc[: anc.index(hips)] if hips in anc else []
                spine.reverse()  # hips -> neck order
                # Mixamo has Spine, Spine1, Spine2 - assign the closest-to-hips first
                spine = [s for s in spine if s not in out]
                for k, s in enumerate(spine[:3]):
                    out[s] = "Spine" if k == 0 else f"Spine{k}"
    return out
