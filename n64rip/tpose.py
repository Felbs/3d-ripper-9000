"""A T-pose for motion capture, generated from a rig that only ever had a stance.

The rest pose the rip ships is frame 0 of the game's own idle animation - the pose the model
was *authored* in, which is what makes it stand up instead of collapsing into a heap.  It is
a stance: feet flexed, shoulders dropped, knees soft.  Motion-capture retargeting wants a
neutral bind pose - arms straight out, legs straight down, feet flat - and no character in the
game contains one.  Setting it by hand worked for Link and does not scale to 167 rigs.

So the T-pose is **generated**, and the only thing it needs is to know which limb is which.
The limbs have no names, but in the posed rest frame every humanoid stands up, so the chains
are where they are:

* the two lowest leaves on opposite sides are the feet; their lowest common ancestor is the
  pelvis and the paths down from it are the legs (Link's legs hang off a pelvis chain two
  joints below his hips; the Zora's hang straight off the root - both read the same way),
* the two leaves furthest sideways, well clear of the floor, are the hands (in a stance they
  hang BELOW the hip joint, so "above the hips" is the wrong filter); their common ancestor
  is the chest and the paths out from it are the arms,
* the highest leaf is the head, reached from the chest,
* the path from the root to the chest is the spine.

Everything else - hair, capes, tails, held things - stays as authored and moves with the joint
it hangs from.  Each classified bone is rotated by the smallest rotation that takes its rest
direction to its target (arms to +/-sideways, legs down, spine up), applied on top of the
authored world rotation so the twist stays what the artist made.  Feet and a leaf head keep
their WORLD orientation instead: in the stance they are already flat on the floor and level,
and inheriting a straightened shin's rotation is what tips a heel up.

**Not wired into the rip.**  The user sets rest poses by hand in their capture tool and wants
the game's authored stance as the starting point, so the published models keep it and their
``limb_NN`` names.  This module is here for the day a generated T-pose is wanted: ``classify``
reads the rig, ``t_pose`` returns the rotations and matrices, and ``joint_names`` the Mixamo
names - 90 of the 167 rigs classify, the rest are not bipeds or fold their arms in ways the
gates refuse.  Animation clips are absolute local rotations per frame, so they would play the
same on the new bind pose.
Which side is "Left" follows +sideways = the character's left; it is stated in the export and
has not been verified against a face.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from n64rip import anim as anim_mod
from n64rip import skeleton as skel_mod

MIXAMO = "mixamorig:"
#: why the last classify() refused - for the export record and for anyone asking
LAST_REASON = ""


def _no(reason: str):
    global LAST_REASON
    LAST_REASON = reason
    return None


@dataclass
class Humanoid:
    """Which limb plays which part.  Every list runs from the body outward."""

    hips: int
    spine: list[int]                 # root's child .. chest, inclusive (may be empty)
    neck_head: list[int]             # chest's child .. head
    legs: dict[str, list[int]]       # "Left"/"Right" -> thigh .. foot (.. toe)
    arms: dict[str, list[int]]       # "Left"/"Right" -> (shoulder,) upper arm, forearm, hand
    side_axis: int                   # 0 (X) or 2 (Z): the world axis that separates the sides
    forward_axis: int
    roles: dict[int, str] = field(default_factory=dict)
    feet: set[int] = field(default_factory=set)


def _children(skel: skel_mod.Skeleton) -> dict[int, list[int]]:
    ch: dict[int, list[int]] = {i: [] for i in range(len(skel.limbs))}
    for limb in skel.limbs:
        if limb.parent is not None:
            ch[limb.parent].append(limb.index)
    return ch


def _subtree(ch: dict[int, list[int]], root: int) -> list[int]:
    out, stack = [], [root]
    while stack:
        i = stack.pop()
        out.append(i)
        stack.extend(ch[i])
    return out


def _path_up(skel: skel_mod.Skeleton, i: int) -> list[int]:
    out = [i]
    while skel.limbs[out[-1]].parent is not None:
        out.append(skel.limbs[out[-1]].parent)
    return out


def _lca(skel: skel_mod.Skeleton, a: int, b: int) -> int | None:
    pa, pb = _path_up(skel, a), set(_path_up(skel, b))
    for i in pa:
        if i in pb:
            return i
    return None


def _down(skel: skel_mod.Skeleton, top: int, leaf: int) -> list[int]:
    """The joints strictly below *top* on the way to *leaf*, body outward."""
    p = _path_up(skel, leaf)
    return list(reversed(p[:p.index(top)]))


def classify(skel: skel_mod.Skeleton, world: dict[int, np.ndarray]) -> Humanoid | None:
    """The humanoid reading of a posed rig, or None if it is not plainly a biped.

    Both candidate side axes (X and Z) are tried and the reading that spreads the hands
    widest wins: the Zora stands with one foot in front of the other, so his feet alone would
    call Z the sideways axis while his arms plainly run along X.
    """
    n = len(skel.limbs)
    if n < 8 or not world or any(i not in world for i in range(n)):
        return _no("too few limbs or no pose")
    best = None
    reasons = []
    for axis in (0, 2):
        h = _classify_axis(skel, world, axis)
        if h is None:
            reasons.append(f"{'XZ'[axis // 2]}: {LAST_REASON}")
            continue
        pos = np.array([world[i][:3, 3] for i in range(n)])
        span = pos[h.arms["Left"][-1], axis] - pos[h.arms["Right"][-1], axis]
        if best is None or span > best[0]:
            best = (span, h)
    if best is None:
        return _no(" / ".join(reasons))
    return best[1]


def _classify_axis(skel: skel_mod.Skeleton, world: dict[int, np.ndarray],
                   side_axis: int) -> Humanoid | None:
    n = len(skel.limbs)
    pos = np.array([world[i][:3, 3] for i in range(n)])
    root = skel.order()[0]
    joints = [i for i in range(n) if i != root]
    height = float(pos[:, 1].max() - pos[:, 1].min())
    if height <= 0:
        return _no("flat")
    low = float(pos[:, 1].min())
    forward_axis = 2 if side_axis == 0 else 0

    # -- feet: the lowest pair on opposite sides at about one height.  Any joint, not only a
    # leaf: child Zelda's dress hem is a leaf lower than either foot.  One foot may be raised
    # mid-step (Ingo, the carpenters), so "one height" is generous.
    floor = [i for i in joints if pos[i, 1] - low < 0.30 * height]
    best = None
    for a in floor:
        for b in floor:
            if not (a < b and abs(pos[a, 1] - pos[b, 1]) < 0.25 * height):
                continue
            lca = _lca(skel, a, b)
            if lca is None or lca in (a, b):
                continue            # adult Zelda's dress hem: two joints of ONE chain
            la, lb = _down(skel, lca, a), _down(skel, lca, b)
            # A pair ON the floor beats one above it (the knees are short chains too); among
            # floor pairs the two SHORTEST chains win - Ganondorf's cape tip reaches the floor
            # and only meets his foot at the chest through a long path.  No sideways gate
            # here: the Zora stands with his feet 14 units apart and adult Zelda's are under
            # one dress; the sides come from the hips, below.
            on_floor = max(pos[a, 1], pos[b, 1]) - low < 0.12 * height
            score = (on_floor, -(len(la) + len(lb)), -(max(pos[a, 1], pos[b, 1]) - low),
                     abs(pos[a, side_axis] - pos[b, side_axis]))
            if best is None or score > best[0]:
                best = (score, a, b, lca, la, lb)
    if best is None:
        return _no("no foot pair")
    _s, fa, fb, pelvis, la, lb = best
    # Sides come from the TOPS of the leg chains, not the feet: adult Zelda's feet sit under
    # one dress and the Zora stands with one foot in front of the other, 14 units apart
    # sideways, while their hip joints are offset like everyone else's.
    if abs(pos[la[0], side_axis] - pos[lb[0], side_axis]) < 0.02 * height:
        return _no("legs not separated sideways")
    if pos[la[0], side_axis] < pos[lb[0], side_axis]:
        la, lb = lb, la
        fa, fb = fb, fa
    legs = {"Left": la, "Right": lb}
    legset = {i for c in legs.values() for i in c}

    # -- hands: the joints furthest to each side, well clear of the floor, off the legs.  In a
    # stance they hang BELOW the hip joint, so "above the hips" is the wrong filter.
    upper = [i for i in joints if pos[i, 1] - low > 0.25 * height and i not in legset
             and i != pelvis]
    if len(upper) < 3:
        return _no("too few joints clear of the floor")
    ha = max(upper, key=lambda i: pos[i, side_axis])
    hb = min(upper, key=lambda i: pos[i, side_axis])
    if pos[ha, side_axis] - pos[hb, side_axis] < 0.15 * height:
        return _no("hands not spread")
    # the widest joint on an arm that hangs down and inward is the SHOULDER; the hand is the
    # leaf at the end of that joint's subtree (the Hylian family, the Kokiri, Sheik, Impa)
    ch = _children(skel)

    def to_leaf(j: int, sign: float) -> int:
        sub = [i for i in _subtree(ch, j) if not ch[i]]
        return max(sub, key=lambda i: sign * pos[i, side_axis] - 0.001 * pos[i, 1]) if sub else j

    ha, hb = to_leaf(ha, 1.0), to_leaf(hb, -1.0)
    # ... and the hand itself must be clear of the floor: a quadruped's front hips are the
    # widest joints at hip height, and the leaves under them are feet.  The span gate above
    # is on the shoulders on purpose - Impa's and Ruto's hands hang almost together.
    if min(pos[ha, 1], pos[hb, 1]) - low < 0.10 * height:
        return _no("hands on the floor")
    # no "hands crossed" gate: Impa and the Gerudo stand with their arms folded, hands past
    # each other; the sides were decided by the shoulders above and stay decided
    chest = _lca(skel, ha, hb)
    if chest is None or chest in (ha, hb, fa, fb) or chest in legset:
        return _no("no chest")
    arms = {"Left": _down(skel, chest, ha), "Right": _down(skel, chest, hb)}
    if any(len(c) < 2 for c in arms.values()):
        return _no("an arm is one joint")
    armset = {i for c in arms.values() for i in c}
    if armset & legset:
        return _no("arms share joints with legs")

    # -- head: the highest joint that is not on an arm or a leg, reached from the chest
    free = [i for i in joints if i not in armset and i not in legset and i != chest]
    if not free:
        return _no("no head")
    top = max(free, key=lambda i: pos[i, 1])
    if pos[top, 1] <= pos[chest, 1] + 0.05 * height:
        return _no("no head above the chest")
    if chest not in _path_up(skel, top):
        return _no("head not reached from the chest")
    neck_head = _down(skel, chest, top)
    if not neck_head:
        return _no("no neck")
    spine = _down(skel, root, chest) if chest != root else []

    roles: dict[int, str] = {root: "Hips"}
    if spine:
        names = ["Spine", "Spine1", "Spine2"]
        for k, i in enumerate(spine):
            roles[i] = names[k] if len(spine) <= 3 else (
                "Spine" if k == 0 else "Spine2" if k == len(spine) - 1 else "Spine1")
    if len(neck_head) == 1:
        roles[neck_head[0]] = "Head"
    else:
        for i in neck_head[:-1]:
            roles[i] = "Neck"
        roles[neck_head[-1]] = "Head"
    feet: set[int] = set()
    for side, chain in legs.items():
        foot_at = len(chain) - 1
        for k in range(len(chain) - 1):
            d = pos[chain[k + 1]] - pos[chain[k]]
            if abs(d[1]) < np.hypot(d[0], d[2]):
                foot_at = k
                break
        names = ["UpLeg", "Leg"]
        for k, i in enumerate(chain):
            if k < foot_at:
                roles[i] = side + (names[k] if k < 2 else "Leg")
            elif k == foot_at:
                roles[i] = side + "Foot"
                feet.add(i)
            else:
                roles[i] = side + ("ToeBase" if k == foot_at + 1 else "Toe_End")
                feet.add(i)
    for side, chain in arms.items():
        # named from the hand backward: the end of the chain is the hand whatever its length
        names = ["Hand", "ForeArm", "Arm", "Shoulder"]
        for k, i in enumerate(reversed(chain)):
            roles[i] = side + (names[k] if k < len(names) else "Shoulder")
        if len(chain) == 2:
            roles[chain[0]] = side + "Arm"
    return Humanoid(root, spine, neck_head, legs, arms, side_axis, forward_axis, roles, feet)


def _align(d: np.ndarray, t: np.ndarray) -> np.ndarray:
    """The smallest rotation taking unit vector d to unit vector t."""
    d = d / (np.linalg.norm(d) or 1.0)
    t = t / (np.linalg.norm(t) or 1.0)
    v = np.cross(d, t)
    c = float(np.dot(d, t))
    s = float(np.linalg.norm(v))
    if s < 1e-8:
        if c > 0:
            return np.eye(3)
        axis = np.cross(d, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(d, [0.0, 1.0, 0.0])
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))


def euler_zyx(m: np.ndarray) -> np.ndarray:
    """``(x, y, z)`` radians with ``rotation_matrix(xyz, 'zyx') == m``: R = Rz Ry Rx."""
    sy = max(-1.0, min(1.0, float(-m[2, 0])))
    y = np.arcsin(sy)
    if abs(np.cos(y)) > 1e-6:
        x = np.arctan2(m[2, 1], m[2, 2])
        z = np.arctan2(m[1, 0], m[0, 0])
    else:
        x = np.arctan2(-m[1, 2], m[1, 1])
        z = 0.0
    return np.array([x, y, z])


def t_pose(skel: skel_mod.Skeleton, world: dict[int, np.ndarray], h: Humanoid,
           root_translation: np.ndarray | None = None) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """``(rotations, world)`` for the T-pose: per-limb ZYX Euler triples and the matrices."""
    n = len(skel.limbs)
    pos = np.array([world[i][:3, 3] for i in range(n)])
    W = {i: world[i][:3, :3] for i in range(n)}
    up = np.array([0.0, 1.0, 0.0])
    side = np.zeros(3)
    side[h.side_axis] = 1.0

    targets: dict[int, np.ndarray] = {}
    chain_next: dict[int, int] = {}
    for chain in list(h.legs.values()) + list(h.arms.values()) + [h.spine, h.neck_head]:
        for k, i in enumerate(chain):
            if k + 1 < len(chain):
                chain_next[i] = chain[k + 1]
    for i in h.spine + h.neck_head:
        targets[i] = up
    for chain in h.legs.values():
        for i in chain:
            if i not in h.feet:
                targets[i] = -up
    for sname, chain in h.arms.items():
        for i in chain:
            targets[i] = side * (1.0 if sname == "Left" else -1.0)
    # the joints that keep their WORLD orientation: feet, and a head with no bone to align
    keep_world = set(h.feet)
    if h.neck_head:
        keep_world.add(h.neck_head[-1])

    D: dict[int, np.ndarray] = {}
    for i in skel.order():
        parent = skel.limbs[i].parent
        inherited = D[parent] if parent is not None and parent in D else np.eye(3)
        if i in keep_world:
            D[i] = np.eye(3)
            continue
        t = targets.get(i)
        nxt = chain_next.get(i)
        if t is None or nxt is None:
            D[i] = inherited
            continue
        d = pos[nxt] - pos[i]
        if np.linalg.norm(d) < 1e-6:
            D[i] = inherited
            continue
        D[i] = _align(inherited @ d, t) @ inherited

    rots = np.zeros((n, 3))
    for i in skel.order():
        parent = skel.limbs[i].parent
        Wn = D[i] @ W[i]
        Wp = (D[parent] @ W[parent]) if parent is not None else np.eye(3)
        rots[i] = euler_zyx(Wp.T @ Wn)
    new_world = anim_mod.pose_matrices(skel, rots, root_translation, "zyx")
    return rots, new_world


def joint_names(h: Humanoid, count: int) -> list[str]:
    """Mixamo-convention names for the classified limbs, ``limb_NN`` for the rest."""
    return [MIXAMO + h.roles[i] if i in h.roles else f"limb_{i:02d}" for i in range(count)]
