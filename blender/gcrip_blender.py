"""GCRip helper add-on for Blender (4.2+ / 5.x).

Install: Edit > Preferences > Add-ons > Install from Disk... > pick this file.

What it adds
------------
* File > Import > GCRip glTF: the normal glTF importer plus GCRip clean-up:
    - hides the alternate/expression meshes (Blender's importer ignores
      KHR_node_visibility, so without this every eye texture shows at once)
    - sets the scene frame rate to the clips' rate (30 fps)
    - optionally renames humanoid bones to Mixamo names (mixamorig:Hips ...)
* Sidebar (N panel) > GCRip tab:
    - Expressions: a slider per face part (eyes, mouth, brows...) - an integer
      property on the armature that drives which texture variant is visible, so it
      can be keyframed like a shape key - plus one button per texture
    - Bones: rename recognised humanoid bones to Mixamo names and back
    - Fix visibility / fps buttons for files imported with the stock importer
    - "Add rip folder as asset library": after `gcrip blend`, browse every ripped model
      in Blender's Asset Browser and drag it into any scene
* Sidebar > GCRip tab > "GCRip Library": a browser over every rip folder you add
  (the folders holding <GameID>/rip_results.json): game dropdown, category dropdown
  (characters / creatures / items / vehicles / props / levels / effects), search box,
  thumbnail, and a Spawn button that imports the pick at the 3D cursor into a
  collection named after the game. Folders and the scanned index are remembered in
  Blender's user config, so the list is instant after the first scan.
* Sidebar > GCRip tab > "GCRip Mocap": pick a .bvh (Bandai Namco dataset, the
  ComfyUI-MotionCapture SMPLtoBVH output, Mixamo/Rokoko exports) and retarget it onto
  the selected character as an NLA strip. No T-pose needed in the source: the
  retarget builds anatomical frames from joint positions at the first frame.
* Any rig, not just Nintendo's: when a rip carries no bone map (every non-J3D format)
  the add-on guesses the humanoid core from the joint names + hierarchy (the same
  structural mapper as gcrip/humanoid.py) before renaming to Mixamo names, so the
  Library's "mocap-ready" filter and the retarget cover EA / Radical / Maya-style rigs.
* Sidebar > GCRip tab > "GCRip Server": a JSON-lines control channel on 127.0.0.1
  (port 8788) so an assistant can drive this Blender through the MCP bridge in
  tools/blender_mcp.py: browse the library, spawn models, retarget clips, place a
  camera, render, save. Start it from the panel, or launch Blender with
  blender/gcrip_server_boot.py (headless too).

The add-on only uses the custom properties gcrip writes into the glTF
(gcrip_variant_of, gcrip_texture, gcrip_std_bone, gcrip_joint), so it works on
any gcrip output.
"""

bl_info = {
    "name": "GCRip glTF helpers",
    "author": "gcrip",
    "version": (0, 4, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > GCRip glTF; 3D View > Sidebar > GCRip",
    "description": "Import gcrip glTF rips with hidden expression meshes, Mixamo bone names, "
    "expression switch panel, library browser, mocap retarget, control server",
    "category": "Import-Export",
}

import contextlib  # noqa: E402
import re  # noqa: E402

import bpy  # noqa: E402
from bpy.props import BoolProperty, FloatProperty, StringProperty  # noqa: E402
from bpy_extras.io_utils import ImportHelper  # noqa: E402
from mathutils import Vector  # noqa: E402

VARIANT_KEY = "gcrip_variant_of"
TEXTURE_KEY = "gcrip_texture"
STD_KEY = "gcrip_std_bone"
ORIG_KEY = "gcrip_joint"


# ----------------------------------------------------------------- helpers


def _root(obj):
    while obj.parent is not None:
        obj = obj.parent
    return obj


def _family(obj):
    """All objects belonging to the same imported model as `obj`."""
    if obj is None:
        return []
    root = _root(obj)
    out = [root]
    stack = list(root.children)
    while stack:
        o = stack.pop()
        out.append(o)
        stack.extend(o.children)
    return out


def _set_hidden(obj, hidden):
    obj.hide_render = hidden
    obj.hide_viewport = False
    with contextlib.suppress(RuntimeError):  # object not in the view layer
        obj.hide_set(hidden)


def hide_variants(objects):
    n = 0
    for o in objects:
        if o.type == "MESH" and VARIANT_KEY in o:
            _set_hidden(o, True)
            n += 1
    return n


def _armatures(objects):
    return [o for o in objects if o.type == "ARMATURE"]


# ---- humanoid mapper: verbatim copy of gcrip/humanoid.py (tests/test_humanoid.py checks)
# BEGIN HUMANOID
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
# END HUMANOID


def auto_map_bones(arm, force=False):
    """Bones carry no gcrip_std_bone props (a rip from before the mapper, or a format the
    ripper does not map): guess the humanoid core from the bone names + hierarchy and store
    the props `rename_bones` uses.  Returns how many bones were mapped."""
    bones = list(arm.data.bones)
    if not force and any(b.get(STD_KEY) or b.get(ORIG_KEY) for b in bones):
        return 0
    idx = {b.name: i for i, b in enumerate(bones)}
    parents = [idx[b.parent.name] if b.parent else None for b in bones]
    found = guess_bones([b.name for b in bones], parents)
    for i, std in found.items():
        bones[i][STD_KEY] = "mixamorig:" + std
    return len(found)


def rig_mixamo_names(arm):
    """Set of Mixamo bone names present on the armature (without the prefix)."""
    return {b.name.split(":", 1)[1] for b in arm.data.bones if b.name.startswith("mixamorig:")}


def rename_bones(arm, to_mixamo):
    """Rename bones using the custom props gcrip stored on them. Blender updates vertex
    groups, actions and constraints automatically when a bone is renamed."""
    n = 0
    if to_mixamo:
        auto_map_bones(arm)
    for bone in list(arm.data.bones):
        if to_mixamo:
            target = bone.get(STD_KEY)
            if target and bone.name != target:
                bone[ORIG_KEY] = bone.name
                bone.name = target
                n += 1
        else:
            orig = bone.get(ORIG_KEY)
            if orig and bone.name != orig:
                bone[STD_KEY] = bone.name
                bone.name = orig
                n += 1
    return n


def expression_groups(objects):
    """{base material name: (base object or None, [(texture name, clone object), ...])}"""
    groups = {}
    by_name = {o.name: o for o in objects if o.type == "MESH"}
    for o in objects:
        if o.type != "MESH" or VARIANT_KEY not in o or TEXTURE_KEY not in o:
            continue
        base = o[VARIANT_KEY]
        groups.setdefault(base, [])
        groups[base].append((o[TEXTURE_KEY], o))
    out = {}
    for base, clones in groups.items():
        base_obj = by_name.get(base)
        if base_obj is None:  # importer may suffix names: "eyeL.001"
            for name, ob in by_name.items():
                if name.split(".")[0] == base and VARIANT_KEY not in ob:
                    base_obj = ob
                    break
        out[base] = (base_obj, sorted(clones, key=lambda c: _natural(c[0])))
    return out


def _natural(s):
    import re

    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def add_expression_controls(objects):
    """Put an integer property per face part on the model's armature (or root) and drive
    the visibility of the base mesh and its texture clones from it: 0 = the model's
    default texture, 1..N = the alternates, in name order. Scrub it in
    Object Properties > Custom Properties like a shape key, or keyframe it."""
    groups = expression_groups(objects)
    if not groups:
        return 0
    arms = _armatures(objects)
    host = arms[0] if arms else _root(objects[0])
    # freshly imported objects must be known to the depsgraph before drivers reference
    # them, otherwise the first evaluation fails and the drivers stay flagged invalid
    bpy.context.view_layer.update()
    n = 0
    for base, (base_obj, clones) in sorted(groups.items()):
        prop = f"expr_{base}"
        options = ([base_obj] if base_obj else []) + [o for _t, o in clones]
        names = (["default"] if base_obj else []) + [t for t, _o in clones]
        host[prop] = 0
        try:
            ui = host.id_properties_ui(prop)
            ui.update(
                min=0,
                max=len(options) - 1,
                soft_min=0,
                soft_max=len(options) - 1,
                description=", ".join(f"{i}={nm}" for i, nm in enumerate(names)),
            )
        except Exception:  # noqa: BLE001
            pass
        for i, o in enumerate(options):
            for path in ("hide_viewport", "hide_render"):
                o.driver_remove(path)
                fc = o.driver_add(path)
                drv = fc.driver
                drv.type = "SCRIPTED"
                v = drv.variables.new()
                v.name = "ex"
                v.type = "SINGLE_PROP"
                v.targets[0].id = host
                v.targets[0].data_path = f'["{prop}"]'
                drv.expression = f"ex != {i}"
                drv.is_valid = True  # clear the "invalid" flag from the pre-variable evaluation
            with contextlib.suppress(RuntimeError):
                o.hide_set(False)  # the eye icon must not fight the driven monitor icon
        n += 1
    return n


def set_expression(objects, base, texture):
    """Show the clone of `base` that uses `texture` ("" = the model's default) and hide
    the other alternatives."""
    groups = expression_groups(objects)
    if base not in groups:
        return
    base_obj, clones = groups[base]
    arms = _armatures(objects)
    host = arms[0] if arms else _root(objects[0])
    prop = f"expr_{base}"
    if prop in host:  # driven: just move the property
        names = ([""] if base_obj else []) + [t for t, _o in clones]
        if texture in names:
            host[prop] = names.index(texture)
            host.update_tag()
            return
    if base_obj is not None:
        _set_hidden(base_obj, texture != "")
    for tex, o in clones:
        _set_hidden(o, tex != texture)


# ---------------------------------------------------------------- operators


def fit_viewports(objs) -> None:
    """Big scene? Raise every 3D viewport's clip range and frame the import.

    A recompiled level spans hundreds of thousands of units; Blender's default
    clip end (1000) culls all of it, which looks like an empty, unclickable file."""
    radius = 0.0
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            radius = max(radius, abs(w.x), abs(w.y), abs(w.z))
    if radius < 900:  # default clip range already fits
        return
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_end = max(space.clip_end, radius * 8)
                    space.clip_start = max(space.clip_start, radius / 1e5)
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                with (
                    contextlib.suppress(Exception),
                    bpy.context.temp_override(window=window, area=area, region=region),
                ):
                    bpy.ops.view3d.view_all()


class GCRIP_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "gcrip.import_gltf"
    bl_label = "GCRip glTF (.gltf)"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".gltf"
    filter_glob: StringProperty(default="*.gltf;*.glb", options={"HIDDEN"})

    mixamo: BoolProperty(
        name="Mixamo bone names",
        description="Rename recognised humanoid bones to mixamorig:* (for retargeting "
        "Mixamo / other standard animation libraries)",
        default=False,
    )
    fps: FloatProperty(name="Scene FPS", default=30.0, min=1, max=240)
    hide: BoolProperty(name="Hide expression/alternate meshes", default=True)
    controls: BoolProperty(
        name="Expression sliders",
        description="Add a driven expr_<part> property per face part on the armature",
        default=True,
    )

    def execute(self, context):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=self.filepath)
        new = [o for o in bpy.data.objects if o not in before]
        n_hidden = hide_variants(new) if self.hide else 0
        n_ctl = 0
        if self.controls:
            # Drivers created while an operator is running come out permanently flagged
            # invalid (observed in 5.1), so build them right after this operator returns.
            n_ctl = len(expression_groups(new))
            names = [o.name for o in new]

            def _later():
                objs = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
                with contextlib.suppress(Exception):
                    add_expression_controls(objs)
                return None

            bpy.app.timers.register(_later, first_interval=0.0)
        context.scene.render.fps = int(round(self.fps))
        context.scene.render.fps_base = 1.0
        fit_viewports(new)
        n_ren = 0
        if self.mixamo:
            for arm in _armatures(new):
                n_ren += rename_bones(arm, True)
        acts = sum(1 for o in new if o.animation_data and o.animation_data.nla_tracks)
        self.report(
            {"INFO"},
            f"gcrip: {len(new)} objects, {n_hidden} alternates hidden, {n_ctl} expression "
            f"controls, {n_ren} bones renamed, animations on {acts} objects",
        )
        return {"FINISHED"}


class GCRIP_OT_hide_variants(bpy.types.Operator):
    bl_idname = "gcrip.hide_variants"
    bl_label = "Hide alternate meshes"
    bl_description = "Hide expression / alternate meshes of the active model"

    def execute(self, context):
        n = hide_variants(_family(context.active_object) or bpy.data.objects)
        self.report({"INFO"}, f"{n} meshes hidden")
        return {"FINISHED"}


class GCRIP_OT_rename_bones(bpy.types.Operator):
    bl_idname = "gcrip.rename_bones"
    bl_label = "Rename bones"
    to_mixamo: BoolProperty(default=True)

    def execute(self, context):
        n = 0
        for arm in _armatures(_family(context.active_object)):
            n += rename_bones(arm, self.to_mixamo)
        self.report({"INFO"}, f"{n} bones renamed")
        return {"FINISHED"}


class GCRIP_OT_auto_map(bpy.types.Operator):
    """Guess the humanoid core (hips, spine, arms, legs...) of the active rig from its bone
    names + hierarchy and rename those bones to Mixamo names - for rips without a bone map"""

    bl_idname = "gcrip.auto_map"
    bl_label = "Guess humanoid bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arms = _armatures(_family(context.active_object))
        if not arms:
            self.report({"WARNING"}, "select a rigged model")
            return {"CANCELLED"}
        n = auto_map_bones(arms[0], force=True)
        rename_bones(arms[0], True)
        core = is_humanoid({i: s for i, s in enumerate(rig_mixamo_names(arms[0]))})
        self.report(
            {"INFO"} if core else {"WARNING"},
            f"{n} bones mapped" + ("" if core else " - not a full biped (arms/legs/hips)"),
        )
        return {"FINISHED"}


class GCRIP_OT_set_expression(bpy.types.Operator):
    bl_idname = "gcrip.set_expression"
    bl_label = "Set expression"
    bl_options = {"REGISTER", "UNDO"}
    base: StringProperty()
    texture: StringProperty()

    def execute(self, context):
        set_expression(_family(context.active_object), self.base, self.texture)
        return {"FINISHED"}


class GCRIP_OT_set_fps(bpy.types.Operator):
    bl_idname = "gcrip.set_fps"
    bl_label = "Scene to 30 fps"

    def execute(self, context):
        context.scene.render.fps = 30
        context.scene.render.fps_base = 1.0
        return {"FINISHED"}


class GCRIP_OT_add_library(bpy.types.Operator):
    """Register a gcrip rip folder (the one holding <GameID>/ folders and
    blender_assets.cats.txt, made by `gcrip blend`) as a Blender Asset Library so every
    model shows up in the Asset Browser with its thumbnail"""

    bl_idname = "gcrip.add_asset_library"
    bl_label = "Add rip folder as asset library"
    directory: StringProperty(subtype="DIR_PATH")
    name: StringProperty(default="GCRip")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        libs = context.preferences.filepaths.asset_libraries
        for lib in libs:
            if bpy.path.abspath(lib.path).rstrip("\\/") == self.directory.rstrip("\\/"):
                self.report({"INFO"}, f"already registered as '{lib.name}'")
                return {"FINISHED"}
        try:
            bpy.ops.preferences.asset_library_add(directory=self.directory)
            lib = libs[-1]
            lib.name = self.name
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"asset library '{self.name}' added - open an Asset Browser editor")
        return {"FINISHED"}


# ---------------------------------------------------------------- library browser
#
# Scans rip folders (the ones holding <GameID>/rip_results.json and <GameID>/stages/),
# sorts every model into a category, and spawns the chosen one at the 3D cursor.
# Rip folders are remembered in Blender's user config (gcrip/library.json), the scanned
# index is cached next to it, so the list is instant after the first scan.

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

import bpy.utils.previews  # noqa: E402
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty  # noqa: E402

CATEGORIES = [
    ("ALL", "All", ""),
    ("CHARACTER", "Characters", "humanoid rigs (retarget-ready)"),
    ("CREATURE", "Creatures & enemies", "other skinned rigs"),
    ("ITEM", "Items & weapons", ""),
    ("VEHICLE", "Vehicles", ""),
    ("PROP", "Props & scenery", "unrigged objects"),
    ("LEVEL", "Levels & rooms", "recompiled stages and room geometry"),
    ("MISC", "Effects & misc", "particles, shadows, tiny meshes"),
]
_CAT_LABEL = {k: v for k, v, _d in CATEGORIES}
_ITEM_HINTS = re.compile(
    r"(sword|shield|bomb|arrow|rupee|heart|item|\bitm|wep|weapon|\bkey|bottle|coin|\bbow\b|hammer|hook|"
    r"boomerang|potion|shell|banana|\bstar|mushroom|flower|ring\b|gem|crystal|treasure|chest|\bbox)",
    re.I,
)
_VEHICLE_HINTS = re.compile(
    r"(ship|boat|kart|\bcar\b|car_|machine|vehicle|plane|train|bike|wagon|cart)", re.I
)
_LEVEL_HINTS = re.compile(
    r"(/stage/|/map/|/room|/level|/course|/world|/field|/scene|/bg/|/back/|/area)", re.I
)
_EFFECT_HINTS = re.compile(
    r"(ptcl|particle|effect|\beff|_ef\b|shadow|kage|glow|fog|smoke|spark)", re.I
)

LIB = {"roots": [], "records": [], "games": [], "scanned": 0}
_GAME_ITEMS = [("NONE", "(scan a rip folder first)", "")]  # kept alive for the dynamic enum
_PCOLL = None
_LIST_CAP = 3000


def rig_kind(m: dict) -> str:
    """'mixamo' = the ripper mapped >= 12 standard bones, 'guess' = the joint names look
    humanoid (both hands, both feet, a torso) so the add-on will map it on spawn, '' = no."""
    if len(m.get("std_bones") or {}) >= 12:
        return "mixamo"
    if (
        m.get("skinned")
        and (m.get("joints") or 0) >= 8
        and humanoid_hint(m.get("joint_names") or [])
    ):
        return "guess"
    return ""


def classify(m: dict) -> str:
    """Category of a rip_results.json model entry."""
    path = m.get("path", "")
    name = os.path.basename(path)
    tris = m.get("triangles", 0) or 0
    joints = m.get("joints", 0) or 0
    if _LEVEL_HINTS.search(path) and joints <= 3:
        return "LEVEL"
    if rig_kind(m):
        return "CHARACTER"
    if _EFFECT_HINTS.search(name) or tris < 8:
        return "MISC"
    if _VEHICLE_HINTS.search(path):
        return "VEHICLE"
    if m.get("skinned") or joints >= 6:
        return "CREATURE"
    if _ITEM_HINTS.search(path) or (tris <= 400 and joints <= 2):
        return "ITEM"
    return "PROP"


def _config_dir() -> str:
    return bpy.utils.user_resource("CONFIG", path="gcrip", create=True)


def load_config() -> dict:
    try:
        with open(os.path.join(_config_dir(), "library.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {"roots": []}


def save_config(cfg: dict) -> None:
    with open(os.path.join(_config_dir(), "library.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)


INDEX_VERSION = 2  # bump when the record tuple changes -> stale caches are rescanned


def scan_root(root: str) -> list:
    """[(game_id, title, category, name, gltf, thumb, info, rig), ...] for one rip folder;
    ``rig`` is 'mixamo' / 'guess' / '' (see rig_kind)."""
    out = []
    if not os.path.isdir(root):
        return out
    for gid in sorted(os.listdir(root)):
        gdir = os.path.join(root, gid)
        rr = os.path.join(gdir, "rip_results.json")
        title = gid
        if os.path.isfile(rr):
            try:
                with open(rr, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as e:  # noqa: BLE001
                print(f"[gcrip] {rr}: {e}")
                continue
            title = data.get("title") or gid
            for m in data.get("models", []):
                if m.get("error") or m.get("duplicate_of") or not m.get("out_rel"):
                    continue
                if (m.get("triangles") or 0) < 8:  # billboards, particles, collision stubs
                    continue
                gltf = os.path.join(gdir, m["out_rel"].replace("/", os.sep))
                thumb = (
                    os.path.join(gdir, m["thumb"].replace("/", os.sep)) if m.get("thumb") else ""
                )
                arc = m["path"].split("/")
                name = os.path.splitext(arc[-1])[0]
                parent = next(
                    (
                        p
                        for p in reversed(arc[:-1])
                        if p.endswith((".arc", ".szs", ".rarc", ".pak", ".dat"))
                    ),
                    "",
                )
                if parent and parent.split(".")[0].lower() != name.lower():
                    name = f"{parent.split('.')[0]}/{name}"
                info = f"{m.get('triangles', 0)} tris, {m.get('joints', 0)} joints"
                rig = rig_kind(m)
                if rig == "mixamo":
                    info += f", {len(m['std_bones'])} Mixamo bones"
                elif rig == "guess":
                    info += ", humanoid names"
                if m.get("animations"):
                    info += f", {len(m['animations'])} clips"
                out.append((gid, title, classify(m), name, gltf, thumb, info, rig))
        sdir = os.path.join(gdir, "stages")
        if os.path.isdir(sdir):
            for st in sorted(os.listdir(sdir)):
                d = os.path.join(sdir, st)
                if not os.path.isdir(d):
                    continue
                gl = [
                    f for f in os.listdir(d) if f.endswith(".gltf") and not f.endswith("_col.gltf")
                ]
                if not gl:
                    continue
                gltf = os.path.join(d, gl[0])
                thumb = next(
                    (
                        os.path.join(d, f)
                        for f in os.listdir(d)
                        if f.endswith((".top.png", ".check.png"))
                    ),
                    "",
                )
                out.append(
                    (
                        gid,
                        title,
                        "LEVEL",
                        f"stage {st}",
                        gltf,
                        thumb,
                        "recompiled level (flattened, no rigs)",
                        "",
                    )
                )
    return out


def build_index(roots: list, save: bool = True) -> None:
    t0 = time.time()
    recs = []
    seen = set()  # a game ripped into two roots is listed once (first root wins)
    for r in roots:
        new = [rec for rec in scan_root(r) if rec[0] not in seen]
        seen.update(rec[0] for rec in new)
        recs.extend(new)
    LIB["roots"] = list(roots)
    LIB["records"] = recs
    LIB["games"] = sorted({(r[0], r[1]) for r in recs}, key=lambda g: g[1].lower())
    LIB["scanned"] = time.time()
    _GAME_ITEMS[:] = [(g, f"{t} ({g})", "") for g, t in LIB["games"]] or [
        ("NONE", "(scan a rip folder first)", "")
    ]
    print(
        f"[gcrip] library: {len(recs)} models in {len(LIB['games'])} games "
        f"from {len(roots)} root(s), {time.time() - t0:.1f}s"
    )
    if save:
        try:
            with open(
                os.path.join(_config_dir(), "library_index.json"), "w", encoding="utf-8"
            ) as fh:
                json.dump({"version": INDEX_VERSION, "roots": roots, "records": recs}, fh)
        except Exception as e:  # noqa: BLE001
            print("[gcrip] could not cache index:", e)


def load_index_cache() -> bool:
    try:
        with open(os.path.join(_config_dir(), "library_index.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return False
    if data.get("version") != INDEX_VERSION:  # older record layout: rescan the same roots
        roots = data.get("roots") or load_config().get("roots") or []
        if not roots:
            return False
        build_index(roots)
        return bool(LIB["records"])
    LIB["roots"] = data.get("roots", [])
    LIB["records"] = [tuple(r) for r in data.get("records", [])]
    LIB["games"] = sorted({(r[0], r[1]) for r in LIB["records"]}, key=lambda g: g[1].lower())
    _GAME_ITEMS[:] = [(g, f"{t} ({g})", "") for g, t in LIB["games"]] or [
        ("NONE", "(scan a rip folder first)", "")
    ]
    return bool(LIB["records"])


def _game_items(self, context):
    return _GAME_ITEMS


def _refill(self, context):
    """Rebuild the visible list from the current game / category / search."""
    props = context.scene.gcrip_lib
    props.items.clear()
    game, cat, q = props.game, props.category, props.search.strip().lower()
    n = 0
    for gid, _t, c, name, gltf, thumb, info, rig in LIB["records"]:
        if gid != game:
            continue
        if cat != "ALL" and c != cat:
            continue
        if props.humanoid and not rig:
            continue
        if q and q not in name.lower() and q not in gltf.lower():
            continue
        it = props.items.add()
        it.name = name
        it.gltf = gltf
        it.thumb = thumb
        it.info = info
        it.category = c
        it.game = gid
        it.rig = rig
        n += 1
        if n >= _LIST_CAP:
            break
    props.index = 0 if n else -1
    props.count = n
    _load_preview(props)


def _load_preview(props):
    global _PCOLL
    if _PCOLL is None:
        _PCOLL = bpy.utils.previews.new()
    if 0 <= props.index < len(props.items):
        it = props.items[props.index]
        if it.thumb and os.path.isfile(it.thumb) and it.thumb not in _PCOLL:
            _PCOLL.load(it.thumb, it.thumb, "IMAGE")


def _on_index(self, context):
    _load_preview(context.scene.gcrip_lib)


class GCRIP_LibItem(bpy.types.PropertyGroup):
    name: StringProperty()
    gltf: StringProperty()
    thumb: StringProperty()
    info: StringProperty()
    category: StringProperty()
    game: StringProperty()
    rig: StringProperty()


class GCRIP_LibProps(bpy.types.PropertyGroup):
    game: EnumProperty(name="Game", items=_game_items, update=_refill)
    category: EnumProperty(name="Category", items=CATEGORIES, default="CHARACTER", update=_refill)
    search: StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_refill)
    humanoid: BoolProperty(
        name="Mocap-ready only",
        default=False,
        description="Only rigs with a humanoid bone map (retarget targets)",
        update=_refill,
    )
    items: CollectionProperty(type=GCRIP_LibItem)
    index: IntProperty(default=-1, update=_on_index)
    count: IntProperty(default=0)
    mixamo: BoolProperty(
        name="Mixamo bone names",
        default=True,
        description="Rename humanoid bones to mixamorig:* on spawn (needed for mocap retargeting)",
    )
    at_cursor: BoolProperty(name="Spawn at 3D cursor", default=True)


class GCRIP_UL_models(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        icons = {
            "CHARACTER": "OUTLINER_OB_ARMATURE",
            "CREATURE": "MONKEY",
            "ITEM": "OBJECT_DATA",
            "VEHICLE": "AUTO",
            "PROP": "MESH_CUBE",
            "LEVEL": "WORLD",
            "MISC": "PARTICLES",
        }
        row = layout.row(align=True)
        icon = icons.get(item.category, "OBJECT_DATA")
        if item.rig:
            icon = "ARMATURE_DATA" if item.rig == "mixamo" else "BONE_DATA"
        row.label(text=item.name, icon=icon)
        row.label(text=item.info)


class GCRIP_OT_lib_add_root(bpy.types.Operator):
    """Add a rip folder (holds <GameID>/ folders from `gcrip rip` / `gcrip dump`) and scan it"""

    bl_idname = "gcrip.lib_add_root"
    bl_label = "Add rip folder"
    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        cfg = load_config()
        root = self.directory.rstrip("\\/")
        if root not in cfg["roots"]:
            cfg["roots"].append(root)
            save_config(cfg)
        build_index(cfg["roots"])
        _refill(None, context)
        self.report({"INFO"}, f"{len(LIB['records'])} models in {len(LIB['games'])} games")
        return {"FINISHED"}


class GCRIP_OT_lib_scan(bpy.types.Operator):
    """Rescan every remembered rip folder (after new rips or `gcrip stage` runs)"""

    bl_idname = "gcrip.lib_scan"
    bl_label = "Rescan"

    def execute(self, context):
        cfg = load_config()
        if not cfg["roots"]:
            self.report({"WARNING"}, "no rip folders yet - use Add rip folder")
            return {"CANCELLED"}
        build_index(cfg["roots"])
        _refill(None, context)
        self.report({"INFO"}, f"{len(LIB['records'])} models in {len(LIB['games'])} games")
        return {"FINISHED"}


class GCRIP_OT_lib_forget(bpy.types.Operator):
    """Forget all remembered rip folders"""

    bl_idname = "gcrip.lib_forget"
    bl_label = "Forget folders"

    def execute(self, context):
        save_config({"roots": []})
        LIB["records"], LIB["games"] = [], []
        _GAME_ITEMS[:] = [("NONE", "(scan a rip folder first)", "")]
        _refill(None, context)
        return {"FINISHED"}


def _ops_import(gltf, mixamo):
    """Run the GCRip importer; from a timer (control server) the context lacks a window,
    so retry under the first window's context."""
    try:
        bpy.ops.gcrip.import_gltf(filepath=gltf, mixamo=mixamo)
    except RuntimeError:
        wm = bpy.context.window_manager
        if not wm.windows:
            raise
        win = wm.windows[0]
        with bpy.context.temp_override(window=win, screen=win.screen, area=win.screen.areas[0]):
            bpy.ops.gcrip.import_gltf(filepath=gltf, mixamo=mixamo)


def spawn_model(gid, category, gltf, at=None, mixamo=True):
    """Import one library pick into collection <gid>; ``at`` = (x, y, z) for the roots
    (levels stay at the origin).  Returns (new objects, the object to select)."""
    if not os.path.isfile(gltf):
        raise FileNotFoundError(gltf)
    before = set(bpy.data.objects)
    _ops_import(gltf, mixamo=mixamo and category == "CHARACTER")
    # the importer's bone-shape mesh lives in "glTF_not_exported" - leave it there
    new = [
        o
        for o in bpy.data.objects
        if o not in before
        and not any(c.name.startswith("glTF_not_exported") for c in o.users_collection)
    ]
    scene = bpy.context.scene
    col = bpy.data.collections.get(gid)
    if col is None:
        col = bpy.data.collections.new(gid)
        scene.collection.children.link(col)
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        col.objects.link(o)
    roots = [o for o in new if o.parent is None]
    for o in roots:
        o["gcrip_gltf"] = gltf  # so later steps (attach_model) can read the joint tree
    if at is not None and category != "LEVEL":
        for o in roots:
            o.location = at
    for o in bpy.data.objects:
        with contextlib.suppress(RuntimeError):
            o.select_set(False)
    arms = [o for o in new if o.type == "ARMATURE"]
    pick = arms[0] if arms else (roots[0] if roots else None)
    if pick is not None:
        with contextlib.suppress(RuntimeError):
            pick.select_set(True)
            bpy.context.view_layer.objects.active = pick
    return new, pick


class GCRIP_OT_lib_spawn(bpy.types.Operator):
    """Import the highlighted model into the scene"""

    bl_idname = "gcrip.lib_spawn"
    bl_label = "Spawn"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.gcrip_lib
        if not (0 <= props.index < len(props.items)):
            self.report({"WARNING"}, "pick a model in the list")
            return {"CANCELLED"}
        it = props.items[props.index]
        try:
            new, _pick = spawn_model(
                it.game,
                it.category,
                it.gltf,
                at=context.scene.cursor.location.copy() if props.at_cursor else None,
                mixamo=props.mixamo,
            )
        except FileNotFoundError as e:
            self.report({"ERROR"}, f"missing file: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{it.name}: {len(new)} objects")
        return {"FINISHED"}


class GCRIP_PT_library(bpy.types.Panel):
    bl_label = "GCRip Library"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GCRip"
    bl_order = 0

    def draw(self, context):
        lay = self.layout
        props = context.scene.gcrip_lib
        if not LIB["records"] and not load_index_cache():
            lay.label(text="No rips indexed yet", icon="INFO")
            lay.operator("gcrip.lib_add_root", icon="FILE_FOLDER")
            return
        row = lay.row(align=True)
        row.operator("gcrip.lib_add_root", text="", icon="ADD")
        row.operator("gcrip.lib_scan", text="", icon="FILE_REFRESH")
        row.operator("gcrip.lib_forget", text="", icon="X")
        row.label(text=f"{len(LIB['records'])} models, {len(LIB['games'])} games")
        lay.prop(props, "game", text="")
        row = lay.row(align=True)
        row.prop(props, "category", text="")
        row.prop(props, "humanoid", text="", icon="ARMATURE_DATA", toggle=True)
        lay.prop(props, "search", text="", icon="VIEWZOOM")
        if props.count >= _LIST_CAP:
            lay.label(text=f"showing first {_LIST_CAP} - narrow the search", icon="ERROR")
        lay.template_list("GCRIP_UL_models", "", props, "items", props, "index", rows=8)
        if 0 <= props.index < len(props.items):
            it = props.items[props.index]
            if _PCOLL is not None and it.thumb in _PCOLL:
                lay.template_icon(icon_value=_PCOLL[it.thumb].icon_id, scale=7)
            lay.label(text=f"{_CAT_LABEL.get(it.category, it.category)} - {it.info}")
        row = lay.row(align=True)
        row.prop(props, "at_cursor")
        row.prop(props, "mixamo")
        lay.operator("gcrip.lib_spawn", icon="IMPORT")


# ---------------------------------------------------------------- mocap retarget
#
# Retargets a BVH clip (Bandai Namco dataset, SMPL from ComfyUI-MotionCapture, Mixamo/Rokoko
# exports) onto a spawned character with Mixamo bone names. The source needs no T-pose:
# anatomical frames are built from joint positions at the reference frame, then world-space
# rotation deltas are transferred bone by bone. Result = a new action on an NLA track.

import math  # noqa: E402

import numpy as np  # noqa: E402
from mathutils import Matrix, Quaternion  # noqa: E402

_MOCAP_MAP = {
    "Hips": "mixamorig:Hips",
    "Spine": "mixamorig:Spine",
    "Chest": "mixamorig:Spine1",
    "Chest2": "mixamorig:Spine2",
    "Neck": "mixamorig:Neck",
    "Head": "mixamorig:Head",
    "Shoulder_L": "mixamorig:LeftShoulder",
    "UpperArm_L": "mixamorig:LeftArm",
    "LowerArm_L": "mixamorig:LeftForeArm",
    "Hand_L": "mixamorig:LeftHand",
    "Shoulder_R": "mixamorig:RightShoulder",
    "UpperArm_R": "mixamorig:RightArm",
    "LowerArm_R": "mixamorig:RightForeArm",
    "Hand_R": "mixamorig:RightHand",
    "UpperLeg_L": "mixamorig:LeftUpLeg",
    "LowerLeg_L": "mixamorig:LeftLeg",
    "Foot_L": "mixamorig:LeftFoot",
    "Toes_L": "mixamorig:LeftToeBase",
    "UpperLeg_R": "mixamorig:RightUpLeg",
    "LowerLeg_R": "mixamorig:RightLeg",
    "Foot_R": "mixamorig:RightFoot",
    "Toes_R": "mixamorig:RightToeBase",
}
_MOCAP_PRIMARY = {
    "Hips": "Spine",
    "Spine": "Chest",
    "Chest": "Neck",
    "Chest2": "Neck",
    "Neck": "Head",
    "Head": None,
    "Shoulder_L": "UpperArm_L",
    "UpperArm_L": "LowerArm_L",
    "LowerArm_L": "Hand_L",
    "Hand_L": None,
    "Shoulder_R": "UpperArm_R",
    "UpperArm_R": "LowerArm_R",
    "LowerArm_R": "Hand_R",
    "Hand_R": None,
    "UpperLeg_L": "LowerLeg_L",
    "LowerLeg_L": "Foot_L",
    "Foot_L": "Toes_L",
    "Toes_L": None,
    "UpperLeg_R": "LowerLeg_R",
    "LowerLeg_R": "Foot_R",
    "Foot_R": "Toes_R",
    "Toes_R": None,
}
_MOCAP_DIR_PARENT = {
    "Head": "Neck",
    "Hand_L": "LowerArm_L",
    "Hand_R": "LowerArm_R",
    "Toes_L": "Foot_L",
    "Toes_R": "Foot_R",
}
_MOCAP_SECONDARY = {
    "Hips": "lr",
    "Spine": "lr",
    "Chest": "sh",
    "Chest2": "sh",
    "Neck": "sh",
    "Head": "sh",
    "Shoulder_L": "fwd",
    "UpperArm_L": "fwd",
    "LowerArm_L": "fwd",
    "Hand_L": "fwd",
    "Shoulder_R": "fwd",
    "UpperArm_R": "fwd",
    "LowerArm_R": "fwd",
    "Hand_R": "fwd",
    "UpperLeg_L": "lr",
    "LowerLeg_L": "lr",
    "Foot_L": "lr",
    "Toes_L": "lr",
    "UpperLeg_R": "lr",
    "LowerLeg_R": "lr",
    "Foot_R": "lr",
    "Toes_R": "lr",
}
_SMPL_NAMES = {
    "Pelvis": "Hips",
    "Spine1": "Spine",
    "Spine2": "Chest",
    "Spine3": "Chest2_src",
    "Neck": "Neck",
    "Head": "Head",
    "L_Collar": "Shoulder_L",
    "L_Shoulder": "UpperArm_L",
    "L_Elbow": "LowerArm_L",
    "L_Wrist": "Hand_L",
    "R_Collar": "Shoulder_R",
    "R_Shoulder": "UpperArm_R",
    "R_Elbow": "LowerArm_R",
    "R_Wrist": "Hand_R",
    "L_Hip": "UpperLeg_L",
    "L_Knee": "LowerLeg_L",
    "L_Ankle": "Foot_L",
    "L_Foot": "Toes_L",
    "R_Hip": "UpperLeg_R",
    "R_Knee": "LowerLeg_R",
    "R_Ankle": "Foot_R",
    "R_Foot": "Toes_R",
}
_MIXAMO_NAMES = {
    "Hips": "Hips",
    "Spine": "Spine",
    "Spine1": "Chest",
    "Spine2": "Chest2_src",
    "Neck": "Neck",
    "Head": "Head",
    "LeftShoulder": "Shoulder_L",
    "LeftArm": "UpperArm_L",
    "LeftForeArm": "LowerArm_L",
    "LeftHand": "Hand_L",
    "RightShoulder": "Shoulder_R",
    "RightArm": "UpperArm_R",
    "RightForeArm": "LowerArm_R",
    "RightHand": "Hand_R",
    "LeftUpLeg": "UpperLeg_L",
    "LeftLeg": "LowerLeg_L",
    "LeftFoot": "Foot_L",
    "LeftToeBase": "Toes_L",
    "RightUpLeg": "UpperLeg_R",
    "RightLeg": "LowerLeg_R",
    "RightFoot": "Foot_R",
    "RightToeBase": "Toes_R",
}
_YUP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)


def bvh_parse(path):
    joints, stack, cur = [], [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if s.startswith("MOTION"):
            break
        if s.startswith(("ROOT", "JOINT")):
            cur = {
                "name": s.split()[1],
                "parent": stack[-1] if stack else None,
                "offset": np.zeros(3),
                "channels": [],
            }
            joints.append(cur)
        elif s.startswith("End Site"):
            cur = {
                "name": stack[-1]["name"] + "_end",
                "parent": stack[-1],
                "offset": np.zeros(3),
                "channels": [],
            }
            joints.append(cur)
        elif s.startswith("OFFSET"):
            cur["offset"] = np.array([float(v) for v in s.split()[1:4]])
        elif s.startswith("CHANNELS"):
            cur["channels"] = s.split()[2:]
        elif s == "{":
            stack.append(cur)
        elif s == "}":
            stack.pop()
    nframes = int(lines[i].split()[1])
    ftime = float(lines[i + 1].split()[2])
    rows = np.array(
        [[float(v) for v in ln.split()] for ln in lines[i + 2 : i + 2 + nframes] if ln.strip()]
    )
    return joints, rows, ftime


def _rot3(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def bvh_fk(joints, row):
    R, P, k = {}, {}, 0
    for j in joints:
        pos = j["offset"].copy()
        rm = np.eye(3)
        if j["parent"] is not None and any(ch.endswith("position") for ch in j["channels"]):
            pos[:] = 0  # exporters that write the full root position into the channels
        for ch in j["channels"]:
            v = row[k]
            k += 1
            if ch.endswith("position"):
                pos["XYZ".index(ch[0])] += v
            else:
                rm = rm @ _rot3(ch[0], v)
        if j["parent"] is None:
            R[j["name"]], P[j["name"]] = rm, pos
        else:
            pr, pp = R[j["parent"]["name"]], P[j["parent"]["name"]]
            R[j["name"]], P[j["name"]] = pr @ rm, pp + pr @ pos
    return {k: _YUP @ v @ _YUP.T for k, v in R.items()}, {k: _YUP @ v for k, v in P.items()}


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _frame3(d, s):
    x = _unit(d)
    y = _unit(s - np.dot(s, x) * x)
    return np.stack([x, y, np.cross(x, y)], axis=1)


def bvh_profile(joint_names):
    names = set(joint_names)
    if "UpperArm_L" in names and "Hips" in names:
        return "bandai", {}
    if "Pelvis" in names and "L_Collar" in names:
        return "smpl", _SMPL_NAMES
    stripped = {n.split(":")[-1] for n in names}
    if "LeftForeArm" in stripped and "Hips" in stripped:
        return "mixamo", {
            n: _MIXAMO_NAMES[n.split(":")[-1]] for n in names if n.split(":")[-1] in _MIXAMO_NAMES
        }
    raise RuntimeError(f"unknown skeleton: {sorted(names)[:10]}")


def hide_static_props(arm, objs):
    """Meshes weighted only to bones above the hips never move with a retarget - hide them."""
    desc, stack = set(), [arm.data.bones["mixamorig:Hips"]]
    while stack:
        b = stack.pop()
        desc.add(b.name)
        stack.extend(b.children)
    hidden = []
    for o in objs:
        if o.type != "MESH" or not o.vertex_groups:
            continue
        used = {
            o.vertex_groups[g.group].name
            for v in o.data.vertices
            for g in v.groups
            if g.weight > 0.01
        }
        if used and not (used & desc):
            o.hide_render = True
            o.hide_viewport = True
            hidden.append(o.name)
    return hidden


def skinned_meshes(objs):
    """Meshes of the family that carry skin weights (vertex groups) - the ones a retarget
    can move.  Empty for rips whose exporter dropped JOINTS_0/WEIGHTS_0."""
    return [o for o in objs if o.type == "MESH" and o.vertex_groups]


_MOCAP_CORE = (
    "Hips",
    "UpperArm_L",
    "LowerArm_L",
    "Hand_L",
    "UpperArm_R",
    "LowerArm_R",
    "Hand_R",
    "UpperLeg_L",
    "LowerLeg_L",
    "Foot_L",
    "UpperLeg_R",
    "LowerLeg_R",
    "Foot_R",
)
_MOCAP_PARENT = {c: p for p, c in _MOCAP_PRIMARY.items() if c is not None}
_MOCAP_PARENT.update({"UpperLeg_L": "Hips", "UpperLeg_R": "Hips", "Shoulder_L": "Chest2"})
_MOCAP_PARENT.update({"Shoulder_R": "Chest2", "Chest2": "Chest"})


def missing_core_bones(arm):
    """Mixamo core bones the rig lacks (empty = retarget can run)."""
    return [_MOCAP_MAP[j] for j in _MOCAP_CORE if _MOCAP_MAP[j] not in arm.data.bones]


def retarget_bvh(arm, bvh_path, ref=0, max_frames=0, name=None, skip=0, motion_scale=0.0):
    """Bake the BVH onto `arm` (Mixamo-named bones) as a new action.

    Only the core (hips, arms + hands, legs + feet) must exist on both sides; spine
    chain, neck, head, shoulders and toes are used when present and skipped when not.
    Ground travel is scaled to the character's leg length (no foot sliding) unless
    ``motion_scale`` gives scene units per capture unit (e.g. 100 for metres -> cm), which
    keeps several characters' positions consistent with the footage instead.
    ``skip`` drops that many leading BVH frames (a person who walks into shot later);
    ``ref`` is the frame (after the skip) whose pose anchors the alignment - a degenerate
    one (the capture flailing before the person was visible) is stepped past automatically.
    Returns (action, slot, nframes, fps)."""
    joints, rows, ftime = bvh_parse(bvh_path)
    if skip:
        rows = rows[int(skip) :]
    if max_frames:
        rows = rows[:max_frames]
    profile, rename = bvh_profile([j["name"] for j in joints])
    for j in joints:
        j["name"] = rename.get(j["name"], j["name"])
    frames = [bvh_fk(joints, r) for r in rows]
    alias = {"Chest2": "Chest2_src" if "Chest2_src" in frames[0][0] else "Chest"}
    src_have = {j for j in _MOCAP_MAP if alias.get(j, j) in frames[0][0]}
    tgt_have = {j for j, b in _MOCAP_MAP.items() if b in arm.data.bones}
    for label, have in (("clip", src_have), ("rig", tgt_have)):
        lack = [j for j in _MOCAP_CORE if j not in have]
        if lack:
            raise RuntimeError(f"{label} lacks core joints: {', '.join(lack)}")
    both = src_have & tgt_have
    A = np.array(arm.matrix_world)
    RA = A[:3, :3]
    RAi = np.linalg.inv(RA)

    def src_pos(t, n):
        return RAi @ frames[t][1][alias.get(n, n)]

    def src_rot(t, n):
        return RAi @ frames[t][0][alias.get(n, n)] @ RA

    def rest_head(b):
        return np.array(arm.data.bones[b].head_local)

    def rest_rot(b):
        return np.array(arm.data.bones[b].matrix_local)[:3, :3]

    def axes(pos, have):
        top = next(n for n in ("Spine", "Chest", "Chest2", "Neck", "Head") if n in have)
        up = _unit(pos(top) - pos("Hips"))
        lr = _unit(pos("UpperLeg_L") - pos("UpperLeg_R"))
        sh = _unit(pos("UpperArm_L") - pos("UpperArm_R"))
        fwd = _unit(np.cross(lr, up))
        if "Toes_L" in have and np.dot(fwd, _unit(pos("Toes_L") - pos("Foot_L"))) < 0:
            fwd = -fwd
        return {"lr": lr, "sh": sh, "fwd": fwd, "up": up}

    def chain_dir(j, pos, eps, have):
        origin, c = pos(j), _MOCAP_PRIMARY[j]
        while c is not None:  # the next distinct joint down the chain
            if c in have:
                d = pos(c) - origin
                if np.linalg.norm(d) > eps:
                    return _unit(d)
            c = _MOCAP_PRIMARY[c]
        p = _MOCAP_DIR_PARENT.get(j, _MOCAP_PARENT.get(j))  # chain end: keep the parent's
        while p is not None:
            if p in have:
                d = origin - pos(p)
                if np.linalg.norm(d) > eps:
                    return _unit(d)
            p = _MOCAP_PARENT.get(p)
        raise RuntimeError(f"no distinct joint next to {j}")

    tgt_p = lambda n: rest_head(_MOCAP_MAP[n])  # noqa: E731
    feet = ("Foot_L", "Foot_R", "Toes_L", "Toes_R")
    tgt_floor = min(tgt_p(n)[2] for n in feet if n in tgt_have)

    # Height and translation are driven by the thigh centre, not the hips joint: some rigs
    # put "Hips" at the floor (a root that parents legs and spine), others above the pelvis.
    def thighs(pos):
        return 0.5 * (pos("UpperLeg_L") + pos("UpperLeg_R"))

    tgt_h = thighs(tgt_p)[2] - tgt_floor
    if tgt_h <= 1e-6:
        raise RuntimeError("rig's legs have no height above the feet - not a standing biped")
    AT = axes(tgt_p, tgt_have)

    def align(r):
        """Anchor frames from source frame r; raises on a degenerate pose."""
        sp = lambda n: src_pos(r, n)  # noqa: E731
        floor = min(sp(n)[2] for n in feet if n in src_have)
        h = thighs(sp)[2] - floor
        if not np.isfinite(h) or h <= 1e-6:
            raise RuntimeError("legs have no height above the feet")
        AS = axes(sp, src_have)
        if min(np.linalg.norm(v) for v in AS.values()) < 0.5:
            raise RuntimeError("body axes collapsed")
        w = {}
        for j in both:
            b = _MOCAP_MAP[j]
            d_s = chain_dir(j, sp, 0.01 * h, src_have)
            d_t = chain_dir(j, tgt_p, 0.01 * tgt_h, tgt_have)
            # the secondary axis must not be parallel to the bone on either side (a rig
            # whose rest arms point straight forward, say); fall back through the others,
            # always the same choice for source and target so the frames still correspond
            first = _MOCAP_SECONDARY[j]
            for sec in (first, *[k for k in ("lr", "fwd", "sh", "up") if k != first]):
                F_s, F_t = _frame3(d_s, AS[sec]), _frame3(d_t, AT[sec])
                if abs(np.linalg.det(F_s)) >= 0.05 and abs(np.linalg.det(F_t)) >= 0.05:
                    break
            else:
                raise RuntimeError(f"degenerate frame at {j}")
            w[b] = F_s @ F_t.T @ rest_rot(b)
        return sp, floor, h, w

    last_err = None
    for r in range(int(ref), len(rows), 5):
        try:
            src_p, src_floor, src_h, W_ref = align(r)
            ref = r
            break
        except (RuntimeError, ValueError, FloatingPointError) as e:
            last_err = e
    else:
        raise RuntimeError(f"no usable reference pose in the clip ({last_err})")
    scale = tgt_h / src_h
    origin = thighs(src_p).copy()
    origin[2] = src_floor
    hips_off = tgt_p("Hips") - thighs(tgt_p)  # rest offset of the hips joint from the thighs
    hips_rest_rot = rest_rot("mixamorig:Hips")

    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.scale = (1, 1, 1)
    act = bpy.data.actions.new(name or "mocap_" + os.path.splitext(os.path.basename(bvh_path))[0])
    arm.animation_data_create()
    arm.animation_data.action = act
    order = []

    def walk(b):
        order.append(b)
        for c in b.children:
            walk(c)

    for b in arm.data.bones:
        if b.parent is None:
            walk(b)
    Ml = {b.name: np.array(b.matrix_local) for b in arm.data.bones}
    inv_map = {_MOCAP_MAP[j]: j for j in both}
    for t in range(len(rows)):
        M = {}
        for b in order:
            n = b.name
            Mp = M[b.parent.name] if b.parent else np.eye(4)
            rel = (np.linalg.inv(Ml[b.parent.name]) if b.parent else np.eye(4)) @ Ml[n]
            basis = np.eye(4)
            if n in inv_map:
                j = inv_map[n]
                desired = np.eye(4)
                desired[:3, :3] = src_rot(t, j) @ src_rot(ref, j).T @ W_ref[n]
                if n == "mixamorig:Hips":
                    sp_t = lambda k: src_pos(t, k)  # noqa: B023, E731
                    drive = (thighs(sp_t) - origin) * (motion_scale or scale)
                    # height from the feet, not from the capture's world Y: video mocap
                    # drifts upward by metres as a person walks in, feet never lie
                    low = min(sp_t(k)[2] for k in feet if k in src_have)
                    drive[2] = tgt_floor + (thighs(sp_t)[2] - low) * scale
                    turn = desired[:3, :3] @ hips_rest_rot.T  # hips rotation vs rest
                    desired[:3, 3] = drive + turn @ hips_off
                    basis = np.linalg.inv(rel) @ np.linalg.inv(Mp) @ desired
                else:
                    desired[:3, 3] = (Mp @ rel)[:3, 3]
                    basis = np.linalg.inv(rel) @ np.linalg.inv(Mp) @ desired
                    basis[:3, 3] = 0
                pb = arm.pose.bones[n]
                pb.matrix_basis = Matrix(basis.tolist())
                pb.keyframe_insert("rotation_quaternion", frame=t + 1)
                if n == "mixamorig:Hips":
                    pb.keyframe_insert("location", frame=t + 1)
            M[n] = Mp @ rel @ basis
    slot = getattr(arm.animation_data, "action_slot", None)
    arm.animation_data.action = None
    print(
        f"[gcrip] mocap: {profile} skeleton, {len(rows)} frames, "
        f"hips {src_h:.3f} -> {tgt_h:.1f} (x{scale:.2f})"
    )
    return act, slot, len(rows), round(1 / ftime)


class GCRIP_MocapProps(bpy.types.PropertyGroup):
    bvh: StringProperty(
        name="BVH clip",
        subtype="FILE_PATH",
        description="Bandai Namco dataset, ComfyUI-MotionCapture SMPLtoBVH output, "
        "or a Mixamo-named export",
    )
    max_frames: IntProperty(name="Max frames", default=0, min=0, description="0 = whole clip")
    start: IntProperty(name="Start frame", default=1, min=1)
    mute_game: BoolProperty(name="Mute the game's own clips", default=True)


class GCRIP_OT_mocap_retarget(bpy.types.Operator):
    """Retarget the BVH clip onto the selected character (Mixamo bone names) as an NLA strip"""

    bl_idname = "gcrip.mocap_retarget"
    bl_label = "Retarget onto selected character"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_armatures(_family(context.active_object)))

    def execute(self, context):
        mp = context.scene.gcrip_mocap
        path = bpy.path.abspath(mp.bvh)
        if not os.path.isfile(path):
            self.report({"ERROR"}, "pick a .bvh file first")
            return {"CANCELLED"}
        fam = _family(context.active_object)
        try:
            res = mocap_retarget(
                _armatures(fam)[0],
                fam,
                path,
                start=mp.start,
                max_frames=mp.max_frames,
                mute_game=mp.mute_game,
            )
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"{res['action']}: {res['frames']} frames on NLA track MOCAP at {res['start']}"
            + (f", hid {len(res['hidden'])} static prop mesh(es)" if res["hidden"] else ""),
        )
        return {"FINISHED"}


def mocap_retarget(
    arm, family, bvh_path, start=1, max_frames=0, mute_game=True, skip=0, motion_scale=0.0
):
    """Retarget a BVH onto `arm` as a strip on NLA track MOCAP (appended after existing
    strips).  Maps + renames bones to Mixamo names first when needed.  Raises RuntimeError
    with a plain message when the rig or the clip is not a biped."""
    if "mixamorig:Hips" not in arm.data.bones:
        rename_bones(arm, True)
    missing = missing_core_bones(arm)
    if missing:
        raise RuntimeError(
            f"not a humanoid rig - no {missing[0]}"
            + (f" (+{len(missing) - 1} more)" if len(missing) > 1 else "")
        )
    if not skinned_meshes(family):
        raise RuntimeError(
            "the mesh carries no skin weights (this rip's exporter dropped them) - the "
            "skeleton would move but the body would not"
        )
    hidden = hide_static_props(arm, family)
    if arm.animation_data and mute_game:
        for tr in arm.animation_data.nla_tracks:
            if tr.name != "MOCAP":
                tr.mute = True
    act, slot, n, fps = retarget_bvh(
        arm, bvh_path, max_frames=max_frames, skip=skip, motion_scale=motion_scale
    )
    track = next((t for t in arm.animation_data.nla_tracks if t.name == "MOCAP"), None)
    if track is None:
        track = arm.animation_data.nla_tracks.new()
        track.name = "MOCAP"
    for s in track.strips:
        start = max(start, int(s.frame_end) + 1)
    strip = track.strips.new(act.name, start, act)
    with contextlib.suppress(Exception):
        if slot is not None:
            strip.action_slot = slot
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_end = max(scene.frame_end, int(strip.frame_end))
    scene.frame_set(start)
    return {
        "action": act.name,
        "frames": n,
        "fps": fps,
        "start": start,
        "end": int(strip.frame_end),
        "hidden": hidden,
        "armature": arm.name,
    }


class GCRIP_PT_mocap(bpy.types.Panel):
    bl_label = "GCRip Mocap"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GCRip"
    bl_order = 2

    def draw(self, context):
        lay = self.layout
        mp = context.scene.gcrip_mocap
        lay.prop(mp, "bvh", text="")
        row = lay.row(align=True)
        row.prop(mp, "max_frames")
        row.prop(mp, "start")
        lay.prop(mp, "mute_game")
        arms = _armatures(_family(context.active_object))
        if arms:
            lay.label(text=f"target: {arms[0].name}", icon="ARMATURE_DATA")
        else:
            lay.label(text="select a spawned character", icon="INFO")
        lay.operator("gcrip.mocap_retarget", icon="ARMATURE_DATA")


# ---------------------------------------------------------------- control server
#
# A JSON-lines TCP channel on 127.0.0.1 so an assistant (tools/blender_mcp.py, an MCP
# server) can drive this Blender: one request per line {"id", "cmd", "args"}, one reply
# per line {"id", "ok", "result" | "error"}.  Socket threads only queue requests; every
# command runs on Blender's main thread from a timer (GUI) or server_loop() (headless), so
# bpy is never touched off-thread.

import io  # noqa: E402
import queue  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

DEFAULT_PORT = 8788
SERVER = {"sock": None, "port": 0, "clients": 0, "handled": 0, "quit": False}
_CMDS = queue.Queue()
RPC = {}


def rpc(fn):
    RPC[fn.__name__] = fn
    return fn


def _client_thread(conn):
    SERVER["clients"] += 1
    try:
        f = conn.makefile("rwb")
        for line in f:
            req = None
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("request must be a JSON object")
            except ValueError as e:
                resp = {"ok": False, "error": f"bad request: {e}"}
            else:
                reply = queue.Queue()
                _CMDS.put((req, reply))
                try:
                    resp = reply.get(timeout=float(req.get("timeout") or 900))
                except queue.Empty:
                    resp = {"ok": False, "error": "timed out waiting for Blender's main thread"}
            resp["id"] = req.get("id") if isinstance(req, dict) else None
            f.write((json.dumps(resp, default=str) + "\n").encode("utf-8"))
            f.flush()
    except (OSError, ValueError):
        pass
    finally:
        SERVER["clients"] -= 1
        with contextlib.suppress(OSError):
            conn.close()


def _accept_thread(srv):
    while SERVER["sock"] is srv:
        try:
            conn, _addr = srv.accept()
        except OSError:
            break
        threading.Thread(target=_client_thread, args=(conn,), daemon=True).start()


def server_pump():
    """Run queued commands on the main thread; returns how many ran."""
    n = 0
    while True:
        try:
            req, reply = _CMDS.get_nowait()
        except queue.Empty:
            return n
        cmd = req.get("cmd")
        fn = RPC.get(cmd)
        try:
            if fn is None:
                raise KeyError(f"unknown command {cmd!r}; known: {', '.join(sorted(RPC))}")
            result = fn(**(req.get("args") or {}))
            resp = {"ok": True, "result": result}
        except Exception as e:  # noqa: BLE001
            resp = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-1500:],
            }
        reply.put(resp)
        n += 1
        SERVER["handled"] += 1


def _server_timer():
    if SERVER["sock"] is None:
        return None
    server_pump()
    if SERVER["quit"]:
        server_stop()
        return None
    return 0.05


def server_running():
    return SERVER["sock"] is not None


def server_start(port=None):
    """Listen on 127.0.0.1:<port> (default: env GCRIP_BLENDER_PORT, the add-on preference,
    else 8788).  Returns the port."""
    if SERVER["sock"] is not None:
        return SERVER["port"]
    if port is None:
        port = int(os.environ.get("GCRIP_BLENDER_PORT") or 0) or _pref("port", DEFAULT_PORT)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", int(port)))
    srv.listen(8)
    SERVER.update(sock=srv, port=int(port), quit=False)
    threading.Thread(target=_accept_thread, args=(srv,), daemon=True).start()
    if not bpy.app.background:
        bpy.app.timers.register(_server_timer, first_interval=0.1, persistent=True)
    print(f"[gcrip] control server listening on 127.0.0.1:{port}")
    return int(port)


def server_stop():
    srv = SERVER["sock"]
    if srv is None:
        return
    SERVER["sock"] = None
    with contextlib.suppress(OSError):
        srv.close()
    print("[gcrip] control server stopped")


def server_loop():
    """Headless (blender -b): pump until a `shutdown` command arrives."""
    while SERVER["sock"] is not None and not SERVER["quit"]:
        if not server_pump():
            time.sleep(0.02)
    time.sleep(0.3)  # let the client thread write the last reply
    server_stop()


def _pref(name, default):
    try:
        return getattr(bpy.context.preferences.addons[__name__].preferences, name)
    except (KeyError, AttributeError):
        return default


def _ensure_index():
    if not LIB["records"]:
        load_index_cache()
    return LIB["records"]


def _find_records(gid=None, name=None, category=None, query=None, humanoid=False, limit=100):
    q = (query or "").strip().lower()
    nm = (name or "").strip().lower()
    out = []
    for rec in _ensure_index():
        r_gid, _t, cat, r_name, gltf, _th, _info, rig = rec
        if gid and r_gid != gid:
            continue
        if category and category != "ALL" and cat != category:
            continue
        if humanoid and not rig:
            continue
        if nm and nm != r_name.lower() and nm != os.path.basename(gltf).lower():
            continue
        if q and q not in r_name.lower() and q not in gltf.lower() and q not in _t.lower():
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def _rec_dict(rec):
    gid, title, cat, name, gltf, thumb, info, rig = rec
    return {
        "gid": gid,
        "title": title,
        "category": cat,
        "name": name,
        "gltf": gltf,
        "thumb": thumb,
        "info": info,
        "rig": rig,
    }


def _resolve_armature(obj=None):
    scene = bpy.context.scene
    if obj:
        o = bpy.data.objects.get(obj)
        if o is None:
            raise KeyError(f"no object named {obj!r}")
    else:
        o = bpy.context.view_layer.objects.active
        if o is None or not _armatures(_family(o)):
            arms = [ob for ob in scene.objects if ob.type == "ARMATURE"]
            if len(arms) != 1:
                raise RuntimeError("pass object=<name>: no single armature in the scene")
            o = arms[0]
    fam = _family(o)
    arms = _armatures(fam)
    if not arms:
        raise RuntimeError(f"{o.name} has no armature")
    return arms[0], fam


@rpc
def ping():
    scene = bpy.context.scene
    return {
        "blender": bpy.app.version_string,
        "addon": ".".join(str(v) for v in bl_info["version"]),
        "background": bpy.app.background,
        "file": bpy.data.filepath,
        "frame": scene.frame_current,
        "frame_range": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "objects": len(scene.objects),
        "port": SERVER["port"],
        "handled": SERVER["handled"],
    }


@rpc
def games(query=""):
    """Games in the library index: id, title, model count, mocap-ready rig count."""
    _ensure_index()
    q = query.strip().lower()
    per = {}
    for gid, title, _c, _n, _g, _t, _i, rig in LIB["records"]:
        d = per.setdefault(gid, {"gid": gid, "title": title, "models": 0, "rigs": 0})
        d["models"] += 1
        d["rigs"] += bool(rig)
    rows = [d for d in per.values() if not q or q in d["title"].lower() or q in d["gid"].lower()]
    return sorted(rows, key=lambda d: d["title"].lower())


@rpc
def library(gid="", category="", query="", humanoid=False, limit=100):
    """Library rows (game id, category, name, glTF path, rig flag ...) - the same records
    the Library panel lists.  category: CHARACTER | CREATURE | ITEM | VEHICLE | PROP |
    LEVEL | MISC | ALL; humanoid=True keeps only mocap-ready rigs."""
    recs = _find_records(
        gid=gid or None, category=category or None, query=query, humanoid=humanoid, limit=limit
    )
    return [_rec_dict(r) for r in recs]


@rpc
def spawn(gltf="", gid="", name="", at=None, mixamo=True):
    """Import a model: by glTF path, or by game id + model name (as listed by `library`).
    ``at`` = [x, y, z] for the model's root (levels stay at the origin)."""
    if gltf:
        recs = [r for r in _ensure_index() if r[4].lower() == gltf.lower()]
        rec = recs[0] if recs else (gid or "MODEL", "", "CHARACTER", name or gltf, gltf, "", "", "")
    else:
        recs = _find_records(gid=gid or None, name=name) or _find_records(
            gid=gid or None, query=name, limit=2
        )
        if not recs:
            raise KeyError(f"no library model {name!r} in game {gid or 'any'}")
        rec = recs[0]
    new, pick = spawn_model(rec[0], rec[2], rec[4], at=tuple(at) if at else None, mixamo=mixamo)
    arms = [o for o in new if o.type == "ARMATURE"]
    out = {
        "objects": [o.name for o in new],
        "root": pick.name if pick else None,
        "armature": arms[0].name if arms else None,
        "gltf": rec[4],
        "category": rec[2],
    }
    if arms:
        std = rig_mixamo_names(arms[0])
        out["bones"] = len(arms[0].data.bones)
        out["mixamo_bones"] = len(std)
        out["missing_core"] = missing_core_bones(arms[0])
        out["skinned_meshes"] = len(skinned_meshes(new))
        out["mocap_ready"] = not out["missing_core"] and out["skinned_meshes"] > 0
        if not out["skinned_meshes"]:
            out["warning"] = "no skin weights in this rip - the body will not follow the bones"
        out["clips"] = [
            t.name for t in (arms[0].animation_data.nla_tracks if arms[0].animation_data else [])
        ]
    return out


@rpc
def characters():
    """Armatures in the scene with their mocap readiness and NLA tracks."""
    rows = []
    for arm in bpy.context.scene.objects:
        if arm.type != "ARMATURE":
            continue
        tracks = []
        if arm.animation_data:
            for t in arm.animation_data.nla_tracks:
                tracks.append({"name": t.name, "muted": t.mute, "strips": len(t.strips)})
        rows.append(
            {
                "armature": arm.name,
                "root": _root(arm).name,
                "location": list(_root(arm).location),
                "bones": len(arm.data.bones),
                "mixamo_bones": len(rig_mixamo_names(arm)),
                "missing_core": missing_core_bones(arm),
                "skinned_meshes": len(skinned_meshes(_family(arm))),
                "tracks": tracks,
            }
        )
    return rows


@rpc
def map_bones(object="", force=False):  # noqa: A002
    """Guess + apply Mixamo names on a rig without a bone map (what spawn does for you)."""
    arm, _fam = _resolve_armature(object)
    n = auto_map_bones(arm, force=force)
    rename_bones(arm, True)
    return {"armature": arm.name, "mapped": n, "missing_core": missing_core_bones(arm)}


@rpc
def retarget(  # noqa: A002
    bvh, object="", start=1, max_frames=0, mute_game=True, skip=0, motion_scale=0.0
):
    """Retarget a BVH clip onto a character (the active one, the only armature, or
    ``object``) as an NLA strip on track MOCAP."""
    if not os.path.isfile(bvh):
        raise FileNotFoundError(bvh)
    arm, fam = _resolve_armature(object)
    return mocap_retarget(
        arm,
        fam,
        bvh,
        start=start,
        max_frames=max_frames,
        mute_game=mute_game,
        skip=skip,
        motion_scale=motion_scale,
    )


@rpc
def frame(frame=None, start=None, end=None):  # noqa: A002
    scene = bpy.context.scene
    if start is not None:
        scene.frame_start = int(start)
    if end is not None:
        scene.frame_end = int(end)
    if frame is not None:
        scene.frame_set(int(frame))
    return {"frame": scene.frame_current, "range": [scene.frame_start, scene.frame_end]}


def _bounds(objs):
    lo = np.array([1e30] * 3)
    hi = -lo
    for o in objs:
        if o.type != "MESH" or o.hide_render:
            continue
        for c in o.bound_box:
            w = np.array(o.matrix_world @ Vector(c))
            lo, hi = np.minimum(lo, w), np.maximum(hi, w)
    if lo[0] > hi[0]:
        for o in objs:
            w = np.array(o.matrix_world.translation)
            lo, hi = np.minimum(lo, w), np.maximum(hi, w)
    return lo, hi


@rpc
def camera(target="", distance=None, height=None, azimuth=-30.0, track=True, name="GCRipCam"):
    """Aim a camera at a character (its family's bounding box): ``distance``/``height`` in
    scene units (default 2.6x / 0.55x the target's height), ``azimuth`` degrees around Z
    from straight in front of the character (0 = front, 90 = its left side, 180 = behind).
    Adds a sun when the scene has no light.  Track To follows the spine bone."""
    scene = bpy.context.scene
    if target:
        obj = bpy.data.objects.get(target)
        if obj is None:
            raise KeyError(f"no object {target!r}")
        fam = _family(obj)
    else:
        arms = [o for o in scene.objects if o.type == "ARMATURE"]
        if not arms:
            raise RuntimeError("no character to aim at - pass target=<object name>")
        fam = _family(arms[0])
    lo, hi = _bounds(fam)
    centre = (lo + hi) / 2
    h = max(hi[2] - lo[2], 1e-3)
    dist = float(distance) if distance is not None else 2.6 * h
    z = float(height) if height is not None else lo[2] + 0.55 * h
    arms = _armatures(fam)
    # azimuth 0 = straight in front of the character: its facing comes from the Mixamo
    # bones (left-right thigh axis x up), else assume the Blender convention (-Y)
    base = -math.pi / 2
    if arms and not missing_core_bones(arms[0]):
        pb = arms[0].pose.bones
        w = arms[0].matrix_world
        lr = np.array(w @ pb["mixamorig:LeftUpLeg"].head) - np.array(
            w @ pb["mixamorig:RightUpLeg"].head
        )
        up = np.array(w @ pb["mixamorig:Hips"].head) - 0.5 * (
            np.array(w @ pb["mixamorig:LeftFoot"].head)
            + np.array(w @ pb["mixamorig:RightFoot"].head)
        )
        fwd = np.cross(lr, up)
        if np.linalg.norm(fwd[:2]) > 1e-9:
            base = math.atan2(fwd[1], fwd[0])
    a = base + math.radians(float(azimuth))
    cam = bpy.data.objects.get(name)
    if cam is None or cam.type != "CAMERA":
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        scene.collection.objects.link(cam)
    cam.location = (centre[0] + dist * math.cos(a), centre[1] + dist * math.sin(a), z)
    cam.data.clip_end = max(cam.data.clip_end, dist * 50)
    for c in list(cam.constraints):
        cam.constraints.remove(c)
    if not any(o.type == "LIGHT" for o in scene.objects):  # headless scenes start unlit
        sun = bpy.data.objects.new("GCRipSun", bpy.data.lights.new("GCRipSun", "SUN"))
        sun.data.energy = 3.0
        scene.collection.objects.link(sun)
        # ride on the camera (slightly from above-left) so it always lights what is framed
        sun.parent = cam
        sun.matrix_parent_inverse.identity()
        sun.location = (0, 0, 0)
        sun.rotation_euler = (0.35, 0.25, 0)
        if scene.world is None:
            scene.world = bpy.data.worlds.new("World")
        scene.world.color = (0.30, 0.33, 0.38)
    if track:
        con = cam.constraints.new("TRACK_TO")
        con.track_axis, con.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
        if arms:
            con.target = arms[0]
            for b in ("mixamorig:Spine1", "mixamorig:Spine", "mixamorig:Hips"):
                if b in arms[0].data.bones:
                    con.subtarget = b
                    break
        else:
            con.target = fam[0]
    scene.camera = cam
    return {"camera": cam.name, "location": list(cam.location), "target_height": h}


@rpc
def render(
    path,
    frame=None,
    animation=False,
    start=None,
    end=None,
    width=None,
    height=None,
    engine=None,
    samples=None,
):  # noqa: E501
    """Render a still (PNG) or an animation (MP4/H.264) to ``path``.  Defaults: Eevee,
    the scene's resolution and frame range."""
    scene = bpy.context.scene
    r = scene.render
    if engine:
        r.engine = engine
    elif r.engine == "BLENDER_WORKBENCH":
        r.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "SceneEEVEE") else "BLENDER_EEVEE"
    if width:
        r.resolution_x = int(width)
    if height:
        r.resolution_y = int(height)
    r.resolution_percentage = 100
    if samples and hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = int(samples)
    if scene.camera is None:
        camera()
    t0 = time.time()
    if animation:
        if start is not None:
            scene.frame_start = int(start)
        if end is not None:
            scene.frame_end = int(end)
        with contextlib.suppress(AttributeError):  # Blender 5: video formats need this first
            r.image_settings.media_type = "VIDEO"
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "MEDIUM"
        r.filepath = path
        bpy.ops.render.render(animation=True)
        frames = scene.frame_end - scene.frame_start + 1
    else:
        if frame is not None:
            scene.frame_set(int(frame))
        with contextlib.suppress(AttributeError):
            r.image_settings.media_type = "IMAGE"
        r.image_settings.file_format = "PNG"
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        frames = 1
    return {
        "path": path,
        "frames": frames,
        "seconds": round(time.time() - t0, 1),
        "engine": r.engine,
    }


@rpc
def scene():
    sc = bpy.context.scene
    objs = []
    for o in sc.objects:
        objs.append(
            {
                "name": o.name,
                "type": o.type,
                "parent": o.parent.name if o.parent else None,
                "location": [round(v, 2) for v in o.matrix_world.translation],
                "hidden": o.hide_render,
                "collection": o.users_collection[0].name if o.users_collection else None,
            }
        )
    return {
        "file": bpy.data.filepath,
        "frame": sc.frame_current,
        "range": [sc.frame_start, sc.frame_end],
        "fps": sc.render.fps,
        "camera": sc.camera.name if sc.camera else None,
        "engine": sc.render.engine,
        "resolution": [sc.render.resolution_x, sc.render.resolution_y],
        "collections": [c.name for c in sc.collection.children],
        "objects": objs,
    }


@rpc
def save(path=""):
    if path:
        bpy.ops.wm.save_as_mainfile(filepath=path)
    else:
        if not bpy.data.filepath:
            raise RuntimeError("untitled file - pass path=")
        bpy.ops.wm.save_mainfile()
    return {"file": bpy.data.filepath}


@rpc
def open_file(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    return {"file": bpy.data.filepath, "objects": len(bpy.context.scene.objects)}


@rpc
def delete(objects=None, family=True):
    """Delete objects by name (with their imported family by default), or everything when
    ``objects`` is empty."""
    sc = bpy.context.scene
    if objects:
        doomed = set()
        for n in objects:
            o = bpy.data.objects.get(n)
            if o is None:
                raise KeyError(f"no object {n!r}")
            doomed.update(_family(o) if family else [o])
    else:
        doomed = set(sc.objects)
    for o in doomed:
        bpy.data.objects.remove(o, do_unlink=True)
    for col in list(sc.collection.children):
        if not col.all_objects:
            bpy.data.collections.remove(col)
    with contextlib.suppress(Exception):
        bpy.data.orphans_purge(do_recursive=True)
    return {"deleted": len(doomed), "objects": len(sc.objects)}


def _action_fcurves(action):
    """F-curves of an action on Blender 4 (action.fcurves) and 5 (layers/strips/slots)."""
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        return list(fcs)
    out = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", []):
                out.extend(cb.fcurves)
    return out


@rpc
def hold_prop(
    gltf="",
    gid="",
    name="",
    object="",  # noqa: A002
    hand="auto",
    release_frame=None,
    flight_frames=0,
    size=0.16,
    toss=1.4,
    grasp=True,
    palm="auto",
):
    """Put a prop (a library pick by gid+name, or a glTF) in a character's hand for the whole
    clip and, if ``release_frame`` (scene frame) is given, let go of it there: it flies a
    ballistic arc from the hand's own velocity (times ``toss``) and lands on the ground,
    in ``flight_frames`` frames when given, else when gravity says so.  ``hand`` = left |
    right | auto (the hand that stays closest to the head before the release - the one
    doing the drinking).  ``size`` = prop height as a fraction of the character's height."""
    arm, fam = _resolve_armature(object)
    sc = bpy.context.scene
    if gltf:
        rec = next((r for r in _ensure_index() if r[4].lower() == gltf.lower()), None)
        rec = rec or (gid or "PROP", "", "ITEM", name or os.path.basename(gltf), gltf, "", "", "")
    else:
        recs = _find_records(gid=gid or None, name=name) or _find_records(
            gid=gid or None, query=name, limit=1
        )
        if not recs:
            raise KeyError(f"no library model {name!r} in game {gid or 'any'}")
        rec = recs[0]
    new, _pick = spawn_model(rec[0], "ITEM", rec[4], at=None, mixamo=False)
    roots = [o for o in new if o.parent is None]
    if not roots:
        raise RuntimeError("prop import produced no objects")
    prop = roots[0]
    for o in roots[1:]:
        o.parent = prop
    # size it against the character
    lo, hi = _bounds(fam)
    char_h = max(hi[2] - lo[2], 1e-3)
    plo, phi = _bounds(new)
    prop_h = max(phi[2] - plo[2], phi[0] - plo[0], phi[1] - plo[1], 1e-3)
    s = size * char_h / prop_h
    prop.scale = (s, s, s)
    hands = {"left": "mixamorig:LeftHand", "right": "mixamorig:RightHand"}
    for b in hands.values():
        if b not in arm.pose.bones:
            raise RuntimeError(f"rig has no {b}")
    f0, f1 = sc.frame_start, int(release_frame) if release_frame else sc.frame_end
    if hand == "auto":
        head = next(
            (
                b
                for b in ("mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2")
                if b in arm.pose.bones
            ),
            None,
        )
        score = {"left": 0.0, "right": 0.0}
        for f in range(f0, max(f0 + 1, f1), 5):
            sc.frame_set(f)
            hp = (
                np.array(arm.matrix_world @ arm.pose.bones[head].head)
                if head
                else np.array([0, 0, 1e9])
            )
            for k, b in hands.items():
                score[k] += np.linalg.norm(np.array(arm.matrix_world @ arm.pose.bones[b].tail) - hp)
        hand = min(score, key=score.get)
    hand_bone = hands[hand]
    pb = arm.pose.bones[hand_bone]

    def hand_matrix(f):
        sc.frame_set(f)
        return arm.matrix_world @ pb.matrix

    # attach: the prop stands upright against the palm, wrapped by the fingers.  The palm
    # normal is the thinnest axis of the hand mesh (PCA of the vertices weighted to the
    # hand bone), signed towards the body; the prop's up axis = fingers x palm normal.
    m0 = hand_matrix(f0)
    tail = np.array(m0 @ Vector((0, pb.length, 0)))
    fingers = _unit(tail - np.array(m0.translation))
    pts = []
    for o in fam:
        if o.type != "MESH" or hand_bone not in o.vertex_groups:
            continue
        gi = o.vertex_groups[hand_bone].index
        for v in o.data.vertices:
            if any(g.group == gi and g.weight > 0.3 for g in v.groups):
                pts.append(np.array(o.matrix_world @ v.co))
    head_p = np.array(m0.translation)
    thickness = 0.0
    curl = 0.0
    if len(pts) >= 12:
        P = np.array(pts)
        C = P - P.mean(axis=0)
        _w, vecs = np.linalg.eigh(C.T @ C)
        normal = _unit(vecs[:, 0])  # least-variance axis = across the palm
        proj = (P - head_p) @ normal
        thickness = float(np.ptp(proj))
        # which side is the palm: fingers curl towards it, so the far end of the hand
        # (last 30% along the bone) sits off the bone axis on the palm side
        along = (P - head_p) @ fingers
        far = along > 0.7 * along.max()
        if far.sum() >= 4:
            curl = float(np.mean(proj[far]) - np.mean(proj))
    else:
        normal = _unit(np.cross(fingers, (0, 0, 1)))
    # which side of the hand plane is the palm: a thumb bone sits on the palm side; else
    # the fingers curl towards it; else assume it faces the body.  ``palm="flip"``
    # overrides all of that when the guess is wrong.
    side_key = "l" if hand == "left" else "r"
    thumb = next(
        (
            b
            for b in arm.pose.bones
            if any(k in b.name.lower() for k in ("thumb", "oya"))
            and b.name.lower().rstrip("0123456789").endswith(side_key)
            or (b.parent is not None and b.parent.name == hand_bone and "thumb" in b.name.lower())
        ),
        None,
    )
    sign_from = "body"
    if thumb is not None:
        tip = np.array(arm.matrix_world @ thumb.tail)
        if np.dot(normal, tip - (head_p + fingers * (0.5 * pb.length))) < 0:
            normal = -normal
        sign_from = f"thumb {thumb.name}"
    elif abs(curl) > 0.02 * max(thickness, 1e-6):
        if curl < 0:
            normal = -normal
        sign_from = "finger curl"
    else:
        body = np.array(arm.matrix_world @ arm.pose.bones["mixamorig:Hips"].head)
        if np.dot(normal, body - tail) < 0:
            normal = -normal
    if palm == "flip":
        normal = -normal
        sign_from += " (flipped)"
    # Grasp: video mocap knows where the wrist is, not how it twists, so a holding hand
    # tends to come out palm-up.  While the prop is held, roll the hand about its own
    # axis each frame so the palm faces the body line (spine at the hand's height: the
    # chest when the arm is down, the face when drinking).  The wrist keys go into the
    # armature's active action, which replaces just that channel on top of the MOCAP NLA
    # strip; after the release the mocap's own values are keyed so nothing lingers.
    grasp_frames = 0
    last = int(release_frame) if release_frame else sc.frame_end
    n_local = (m0.to_3x3().inverted() @ Vector(normal)).normalized()
    if grasp:
        hips_pb = arm.pose.bones["mixamorig:Hips"]
        top_pb = next(
            (
                arm.pose.bones[b]
                for b in ("mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2")
                if b in arm.pose.bones
            ),
            None,
        )
        mocap = {}
        for f in range(f0, sc.frame_end + 1):  # pass 1: the mocap's own hand pose
            sc.frame_set(f)
            mocap[f] = (arm.matrix_world @ pb.matrix).copy()
        for f in range(f0, sc.frame_end + 1):  # pass 2: roll while holding, key everything
            sc.frame_set(f)
            M = mocap[f]
            if f <= last and top_pb is not None:
                a = Vector(M.col[1][:3]).normalized()
                n_w = (M.to_3x3() @ n_local).normalized()
                p0 = arm.matrix_world @ hips_pb.head
                p1 = arm.matrix_world @ top_pb.head
                axis = p1 - p0
                length = axis.length
                axis.normalize()
                hand_p = M.translation
                t = max(0.0, min(length, (hand_p - p0).dot(axis)))
                d = (p0 + axis * t) - hand_p
                d -= a * d.dot(a)
                n_p = n_w - a * n_w.dot(a)
                if d.length > 1e-6 and n_p.length > 1e-6:
                    d.normalize()
                    n_p.normalize()
                    ang = math.atan2(n_p.cross(d).dot(a), n_p.dot(d))
                    M = (
                        Matrix.Translation(hand_p)
                        @ Matrix.Rotation(ang, 4, a)
                        @ M.to_3x3().to_4x4()
                    )
                    grasp_frames += 1
            pb.matrix = arm.matrix_world.inverted() @ M
            pb.keyframe_insert("rotation_quaternion", frame=f)
        sc.frame_set(f0)
    # The prop stands across the palm, perpendicular to the fingers (they wrap around it),
    # pointing up in the HELD pose: everything is built in the hand's own frame from the
    # rest-pose measurements, and the up sign is picked at a frame in the middle of the
    # hold, after the grasp roll - not at the rest pose, where a palm-down hand fooled it.
    width = min(phi[0] - plo[0], phi[1] - plo[1]) * s
    # rest the prop on the palm: mid-hand along the bone, pushed out past the hand's own
    # thickness plus the prop's radius, so it touches the palm instead of filling the hand
    palm_mid = head_p + fingers * (0.5 * pb.length)
    centre = palm_mid + normal * (0.5 * thickness + 0.5 * width)
    # The drink stays upright in the world while held: it follows the palm point but keeps
    # its own orientation (a real hand turns the wrist to keep a can level, which the
    # capture cannot see), leaning towards the head when raised to drink.  Keyed every
    # frame; the model's origin is wherever the game put it (a bottle's is at its base),
    # so the grip point is 45% up the mesh, not the origin.
    centre_local = m0.inverted() @ Vector(centre)
    g = Vector(((plo[0] + phi[0]) / 2, (plo[1] + phi[1]) / 2, plo[2] + 0.45 * (phi[2] - plo[2])))
    head_pb = next(
        (arm.pose.bones[b] for b in ("mixamorig:Head", "mixamorig:Neck") if b in arm.pose.bones),
        None,
    )

    def held_matrix(f):
        p = hand_matrix(f) @ centre_local
        rot = Matrix.Identity(3)
        if head_pb is not None:
            d = (arm.matrix_world @ head_pb.head) - p
            reach = 0.35 * char_h
            horiz = Vector((d.x, d.y, 0.0))
            if 1e-6 < d.length < reach and horiz.length > 1e-6:
                tilt = math.radians(55.0) * (1.0 - d.length / reach)
                rot = Matrix.Rotation(tilt, 3, Vector((0, 0, 1)).cross(horiz.normalized()))
        return Matrix.Translation(p) @ rot.to_4x4() @ Matrix.Translation(-g * s)

    prop.rotation_mode = "XYZ"
    for f in range(f0, last + 1):
        sc.frame_set(f)
        prop.matrix_world = held_matrix(f) @ Matrix.Diagonal((s, s, s, 1))
        prop.keyframe_insert("location", frame=f)
        prop.keyframe_insert("rotation_euler", frame=f)
    sc.frame_set(f0)
    out = {
        "prop": prop.name,
        "grasp_frames": grasp_frames,
        "palm_side": sign_from,
        "hand": hand,
        "attached_to": hand_bone,
        "scale": round(s, 4),
        "hand_thickness": round(thickness, 1),
        "finger_curl": round(curl, 2),
        "palm_normal": [round(float(v), 2) for v in normal],
    }
    if release_frame:
        fr = int(release_frame)
        fps = sc.render.fps or 30
        w_r = held_matrix(fr)
        w_p = held_matrix(max(f0, fr - 4))
        span = max(1, fr - max(f0, fr - 4))
        vel = (np.array(w_r.translation) - np.array(w_p.translation)) / span * float(toss)
        vmax = 12.0 * (max(hi[2] - lo[2], 1e-3) / 1.7) / (sc.render.fps or 30)  # 12 m/s cap
        if np.linalg.norm(vel) > vmax:
            vel *= vmax / np.linalg.norm(vel)
        upm = char_h / 1.7  # scene units per metre, from the character's height
        g = 9.81 * upm / (fps * fps)
        p0 = np.array(w_r.translation)
        ground = lo[2]
        z0 = p0[2] - ground
        if flight_frames and flight_frames > 0:
            T = int(flight_frames)
            vel[2] = (0.5 * g * T * T - z0) / T
        else:
            vz = vel[2]
            T = int(max(3, (vz + (vz * vz + 2 * g * z0) ** 0.5) / g))
        rot0 = np.array(w_r.to_euler())
        spin = np.array([0.15, 0.07, 0.2])
        for i in range(T + 1):
            p = p0 + vel * i
            p[2] = p0[2] + vel[2] * i - 0.5 * g * i * i
            if p[2] < ground:
                p[2] = ground
            prop.location = tuple(p)
            prop.rotation_euler = tuple(rot0 + spin * i)
            prop.keyframe_insert("location", frame=fr + i)
            prop.keyframe_insert("rotation_euler", frame=fr + i)
        out.update(
            {
                "release_frame": fr,
                "flight_frames": T,
                "lands_frame": fr + T,
                "velocity": [round(float(v), 2) for v in vel],
            }
        )
        sc.frame_set(f0)
    return out


_GLTF_YUP = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def _gltf_node_world(path, name):
    """Rest-pose world matrix (Blender axes) of the glTF node called ``name`` - or of the
    skin's root joint when ``name`` is None - straight from the file's node tree.  None when
    the file or node is not there."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            g = json.load(fh)
    except (OSError, ValueError):
        return None
    nodes = g.get("nodes", [])
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    if name is None:
        joints = (g.get("skins") or [{}])[0].get("joints") or []
        idx = next((j for j in joints if j not in parent), None)
        if idx is None:
            idx = next((i for i in range(len(nodes)) if i not in parent), None)
    else:
        idx = next((i for i, n in enumerate(nodes) if n.get("name") == name), None)
    if idx is None:
        return None

    def local(n):
        if "matrix" in n:
            m = n["matrix"]  # column-major
            return Matrix([[m[c * 4 + r] for c in range(4)] for r in range(4)])
        t = n.get("translation", [0, 0, 0])
        q = n.get("rotation", [0, 0, 0, 1])  # x y z w
        s = n.get("scale", [1, 1, 1])
        rot = Quaternion((q[3], q[0], q[1], q[2])).to_matrix().to_4x4()
        return Matrix.Translation(t) @ rot @ Matrix.Diagonal((s[0], s[1], s[2], 1))

    m = Matrix.Identity(4)
    i = idx
    while i is not None:
        m = local(nodes[i]) @ m
        i = parent.get(i)
    return _GLTF_YUP @ m @ _GLTF_YUP.transposed()


@rpc
def attach_model(  # noqa: A002
    gid="", name="", gltf="", object="", bone="mixamorig:Head", orient="auto", skin="auto"
):
    """Hang another rip on a character's bone - games often keep heads, faces or hands as
    separate models (Twilight Princess Link: Kmdl/al + Kmdl/al_head + Bmdl/al_face).  The
    attachment's own bone with the same original name as ``bone`` (or its root bone) is
    aligned onto the character's bone in the rest pose and follows it from then on."""
    arm, _fam = _resolve_armature(object)
    if bone not in arm.pose.bones:
        raise KeyError(f"{arm.name} has no bone {bone}")
    if gltf:
        rec = next((r for r in _ensure_index() if r[4].lower() == gltf.lower()), None)
        rec = rec or (
            gid or "PART",
            "",
            "CREATURE",
            name or os.path.basename(gltf),
            gltf,
            "",
            "",
            "",
        )
    else:
        recs = _find_records(gid=gid or None, name=name) or _find_records(
            gid=gid or None, query=name, limit=1
        )
        if not recs:
            raise KeyError(f"no library model {name!r} in game {gid or 'any'}")
        rec = recs[0]
    new, _pick = spawn_model(rec[0], "CREATURE", rec[4], at=None, mixamo=False)
    roots = [o for o in new if o.parent is None]
    if not roots:
        raise RuntimeError("import produced no objects")
    part = next((o for o in roots if o.type == "ARMATURE"), roots[0])
    for o in roots:
        if o is not part:
            o.parent = part
    # a face rip carries its expression clips as NLA tracks - all playing at once they
    # mangle the mesh; park the part in its rest pose (unmute a track to use a clip)
    for o in new:
        if o.animation_data:
            o.animation_data.action = None
            for tr in o.animation_data.nla_tracks:
                tr.mute = True
    # some rips' skin weights are wrong (TP's al_face folds half the face away even at
    # rest): when the skinned rest shape strays from the raw mesh, attach it rigid
    rigid = []
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    for o in new:
        if o.type != "MESH" or not any(m.type == "ARMATURE" for m in o.modifiers):
            continue
        raw = np.array([v.co for v in o.data.vertices])
        ev = o.evaluated_get(dg)
        skinned = np.array([v.co for v in ev.data.vertices])
        if len(raw) and len(raw) == len(skinned):
            size = max(np.ptp(raw, axis=0).max(), 1e-6)
            stray = np.abs(skinned - raw).max() / size
            if skin == "rigid" or (skin == "auto" and stray > 0.15):
                for m in o.modifiers:
                    if m.type == "ARMATURE":
                        m.show_render = m.show_viewport = False
                rigid.append((o.name, round(float(stray), 2)))
    sc = bpy.context.scene
    sc.frame_set(sc.frame_start)
    body_pb = arm.pose.bones[bone]
    # everything below is measured in the character's REST pose (a strip may already be
    # playing at frame_start)
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    wb = arm.matrix_world @ body_pb.matrix
    orig = arm.data.bones[bone].get(ORIG_KEY) or bone.split(":")[-1]
    # Align with the game's own joint frames from the glTF node trees, not Blender's bone
    # axes: the importer points each bone at its children, so the same joint ends up with
    # different bone axes in two rigs.  The part was authored in the joint's frame, so its
    # root joint goes exactly where the character's joint is.
    node_m = _gltf_node_world(arm.get("gcrip_gltf"), str(orig))
    matched = None
    if node_m is not None:
        root_m = _gltf_node_world(rec[4], None) or Matrix.Identity(4)
        part.matrix_world = arm.matrix_world @ node_m @ root_m.inverted()
        matched = f"joint {orig}"
    else:  # no glTF at hand: fall back to matching bone axes
        local = Matrix.Identity(4)
        if part.type == "ARMATURE":
            cands = [b for b in part.data.bones if b.name.lower() == str(orig).lower()]
            if not cands:
                cands = [b for b in part.data.bones if b.parent is None]
            if cands:
                matched = cands[0].name
                local = cands[0].matrix_local
        part.matrix_world = wb @ local.inverted()
    turned = 0.0
    if orient == "forward" or (orient == "auto" and "face" in (name or rec[3]).lower()):
        # face parts are not always authored in the head joint's frame: turn the part about
        # the vertical axis through its root until its mesh (which lies in front of the
        # root) points the way the character faces
        bpy.context.view_layer.update()
        pb = arm.pose.bones
        lr = np.array(arm.matrix_world @ pb["mixamorig:LeftUpLeg"].head) - np.array(
            arm.matrix_world @ pb["mixamorig:RightUpLeg"].head
        )
        fwd = np.cross(lr, (0, 0, 1))
        pts = [
            np.array(o.matrix_world @ v.co)
            for o in new
            if o.type == "MESH"
            for v in o.data.vertices
        ]
        if len(pts) and np.linalg.norm(fwd[:2]) > 1e-6:
            root_p = np.array(part.matrix_world.translation)
            d = np.mean(pts, axis=0) - root_p
            a = math.atan2(fwd[1], fwd[0]) - math.atan2(d[1], d[0])
            rot = Matrix.Rotation(a, 4, "Z")
            part.matrix_world = (
                Matrix.Translation(root_p) @ rot @ Matrix.Translation(-root_p) @ part.matrix_world
            )
            turned = round(math.degrees(a), 1)
    con = part.constraints.new("CHILD_OF")
    con.target, con.subtarget = arm, bone
    con.inverse_matrix = wb.inverted()
    arm.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    return {
        "part": part.name,
        "objects": [o.name for o in new],
        "bone": bone,
        "part_bone": matched,
        "turned_degrees": turned,
        "rigid": rigid,
        "gltf": rec[4],
    }


_CAM_TO_BL = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)  # Y-up world -> Z-up
_MANO_WRIST, _MANO_INDEX, _MANO_MIDDLE, _MANO_PINKY = 0, 5, 9, 17


def _palm_normal_local(arm, fam, hand_bone, palm="auto"):
    """The palm normal of a hand bone in bone-local space at rest: thinnest axis of the
    hand mesh (PCA of vertices weighted to the bone), signed by a thumb bone, else finger
    curl, else 'towards the body'; ``palm="flip"`` reverses.  Returns (n_local, how)."""
    sc = bpy.context.scene
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    pb = arm.pose.bones[hand_bone]
    m0 = arm.matrix_world @ pb.matrix
    head_p = np.array(m0.translation)
    tail = np.array(m0 @ Vector((0, pb.length, 0)))
    fingers = _unit(tail - head_p)
    pts = []
    for o in fam:
        if o.type != "MESH" or hand_bone not in o.vertex_groups:
            continue
        gi = o.vertex_groups[hand_bone].index
        for v in o.data.vertices:
            if any(g.group == gi and g.weight > 0.3 for g in v.groups):
                pts.append(np.array(o.matrix_world @ v.co))
    curl = 0.0
    thickness = 1.0
    if len(pts) >= 12:
        P = np.array(pts)
        C = P - P.mean(axis=0)
        _w, vecs = np.linalg.eigh(C.T @ C)
        normal = _unit(vecs[:, 0])
        proj = (P - head_p) @ normal
        thickness = float(np.ptp(proj))
        along = (P - head_p) @ fingers
        far = along > 0.7 * along.max()
        if far.sum() >= 4:
            curl = float(np.mean(proj[far]) - np.mean(proj))
    else:
        normal = _unit(np.cross(fingers, (0, 0, 1)))
    side_key = "l" if "Left" in hand_bone else "r"
    thumb = next(
        (
            b
            for b in arm.pose.bones
            if any(k in b.name.lower() for k in ("thumb", "oya"))
            and b.name.lower().rstrip("0123456789").endswith(side_key)
        ),
        None,
    )
    if thumb is not None:
        tip = np.array(arm.matrix_world @ thumb.tail)
        if np.dot(normal, tip - (head_p + fingers * (0.5 * pb.length))) < 0:
            normal = -normal
        how = f"thumb {thumb.name}"
    elif abs(curl) > 0.02 * thickness:
        if curl < 0:
            normal = -normal
        how = "finger curl"
    else:
        body = np.array(arm.matrix_world @ arm.pose.bones["mixamorig:Hips"].head)
        if np.dot(normal, body - tail) < 0:
            normal = -normal
        how = "body guess"
    if palm == "flip":
        normal = -normal
        how += " (flipped)"
    n_local = (m0.to_3x3().inverted() @ Vector(normal)).normalized()
    arm.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    sc.frame_set(sc.frame_start)
    return Vector(n_local), how


@rpc
def apply_hands(  # noqa: A002
    hands_json, camera_json="", object="", person=1, sides="LR", palm="auto", max_gap=15
):
    """Drive a character's hand bones from tracked hands (WiLoR, see comfyui/gcrip_mocap/
    hands.py): each detected frame gives the palm normal and finger direction in camera
    space; ``camera_json`` (R_world_from_cam from the GVHMR file) turns them into the
    mocap world, and the hand bone is rotated so its own palm normal and finger axis
    match.  Frames without a detection are interpolated over gaps up to ``max_gap``
    frames; elsewhere the body capture's wrist stays.  Keys land in the armature's active
    action on top of the MOCAP strip.  ``person`` = the person index in the hands file."""
    arm, fam = _resolve_armature(object)
    with open(hands_json, encoding="utf-8") as fh:
        doc = json.load(fh)
    people = doc.get("people", {})
    rec = people.get(str(person))
    if not rec:
        raise KeyError(f"no person {person} in {hands_json} (has {sorted(people)})")
    R_wc = np.eye(3)
    if camera_json and os.path.isfile(camera_json):
        with open(camera_json, encoding="utf-8") as fh:
            R_wc = np.array(json.load(fh)["R_world_from_cam"], dtype=float)
    R_bl = _CAM_TO_BL @ R_wc  # camera -> Blender world (direction vectors only)
    sc = bpy.context.scene
    out = {}
    for side in sides:
        hand_bone = "mixamorig:LeftHand" if side == "L" else "mixamorig:RightHand"
        if hand_bone not in arm.pose.bones:
            continue
        pb = arm.pose.bones[hand_bone]
        n_local, how = _palm_normal_local(arm, fam, hand_bone, palm)
        side_local = Vector((0, 1, 0)).cross(n_local).normalized()
        L = Matrix(
            (
                (side_local.x, 0.0, n_local.x),
                (side_local.y, 1.0, n_local.y),
                (side_local.z, 0.0, n_local.z),
            )
        )
        # target world rotation per detected frame (scene frame = clip frame + 1)
        targets = {}
        for fs, hands_at in rec.items():
            h = hands_at.get(side)
            if not h:
                continue
            kp = np.array(h["kp3d"], dtype=float)
            fingers = kp[_MANO_MIDDLE] - kp[_MANO_WRIST]
            span = np.cross(kp[_MANO_INDEX] - kp[_MANO_WRIST], kp[_MANO_PINKY] - kp[_MANO_WRIST])
            normal = -span if side == "R" else span  # cross(index, pinky) = back of a right hand
            f_w = _unit(R_bl @ fingers)
            n_w = _unit(R_bl @ normal)
            n_w = _unit(n_w - f_w * np.dot(n_w, f_w))
            s_w = np.cross(f_w, n_w)
            W = Matrix(
                ((s_w[0], f_w[0], n_w[0]), (s_w[1], f_w[1], n_w[1]), (s_w[2], f_w[2], n_w[2]))
            )
            targets[int(fs) + 1] = (W @ L.inverted()).to_quaternion()
        if not targets:
            out[side] = {"bone": hand_bone, "frames": 0}
            continue
        keys = sorted(targets)
        # pass 1: the capture's own hand matrices (an active action would mask the NLA)
        mocap = {}
        for f in range(sc.frame_start, sc.frame_end + 1):
            sc.frame_set(f)
            mocap[f] = (arm.matrix_world @ pb.matrix).copy()
        applied = 0
        for f in range(sc.frame_start, sc.frame_end + 1):
            sc.frame_set(f)
            M = mocap[f]
            q = None
            if f in targets:
                q = targets[f]
            else:
                lo = max((k for k in keys if k < f), default=None)
                hi = min((k for k in keys if k > f), default=None)
                if lo is not None and hi is not None and hi - lo <= max_gap:
                    q = targets[lo].slerp(targets[hi], (f - lo) / (hi - lo))
            if q is not None:
                rot = q.to_matrix()
                # the world rotation includes the armature object's rotation/scale: the
                # bone matrix we set is armature-space, so strip the object part
                M = Matrix.Translation(M.translation) @ rot.to_4x4()
                applied += 1
            pb.matrix = arm.matrix_world.inverted() @ M
            pb.keyframe_insert("rotation_quaternion", frame=f)
        out[side] = {"bone": hand_bone, "detected": len(targets), "frames": applied, "palm": how}
    sc.frame_set(sc.frame_start)
    return out


@rpc
def python(code):
    """Run Python inside Blender with `bpy` and this add-on's globals; returns captured
    stdout and repr() of a variable named `result` if the code sets one."""
    ns = dict(globals())
    ns["bpy"] = bpy
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<gcrip-rpc>", "exec"), ns)  # noqa: S102
    return {"stdout": buf.getvalue()[-20000:], "result": repr(ns.get("result"))[:20000]}


@rpc
def shutdown():
    """Stop the server; a headless Blender exits with it."""
    SERVER["quit"] = True
    return {"stopping": True}


class GCRIP_Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    port: IntProperty(name="Control server port", default=DEFAULT_PORT, min=1024, max=65535)
    autostart: BoolProperty(
        name="Start the control server with Blender",
        default=False,
        description="Listen on 127.0.0.1:<port> whenever this add-on loads",
    )

    def draw(self, context):
        self.layout.prop(self, "port")
        self.layout.prop(self, "autostart")


class GCRIP_OT_server_start(bpy.types.Operator):
    """Listen for the MCP bridge (tools/blender_mcp.py) on 127.0.0.1"""

    bl_idname = "gcrip.server_start"
    bl_label = "Start control server"

    def execute(self, context):
        try:
            port = server_start()
        except OSError as e:
            self.report({"ERROR"}, f"could not listen: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"GCRip control server on 127.0.0.1:{port}")
        return {"FINISHED"}


class GCRIP_OT_server_stop(bpy.types.Operator):
    bl_idname = "gcrip.server_stop"
    bl_label = "Stop control server"

    def execute(self, context):
        server_stop()
        return {"FINISHED"}


class GCRIP_PT_server(bpy.types.Panel):
    bl_label = "GCRip Server"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GCRip"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        lay = self.layout
        if server_running():
            lay.label(
                text=f"listening on 127.0.0.1:{SERVER['port']}  ({SERVER['handled']} commands)",
                icon="LINKED",
            )
            lay.operator("gcrip.server_stop", icon="UNLINKED")
        else:
            lay.label(text="not running", icon="UNLINKED")
            lay.operator("gcrip.server_start", icon="LINKED")
        lay.label(text="MCP bridge: tools/blender_mcp.py", icon="INFO")


def _autostart():
    if os.environ.get("GCRIP_SERVER_AUTOSTART") or _pref("autostart", False):
        with contextlib.suppress(OSError):
            server_start()
    return None


# ------------------------------------------------------------------- panel


class GCRIP_PT_panel(bpy.types.Panel):
    bl_label = "GCRip"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GCRip"

    def draw(self, context):
        lay = self.layout
        obj = context.active_object
        fam = _family(obj)
        if not fam:
            lay.label(text="Select an imported model")
            return
        groups = expression_groups(fam)
        box = lay.box()
        box.label(text="Expressions", icon="MONKEY")
        if not groups:
            box.label(text="(no texture switches in this model)")
        arms = _armatures(fam)
        host = arms[0] if arms else _root(obj)
        for base, (base_obj, clones) in sorted(groups.items()):
            col = box.column(align=True)
            prop = f"expr_{base}"
            if prop in host:
                col.prop(host, f'["{prop}"]', text=base, slider=True)
            else:
                col.label(text=base)
            cur = host.get(prop, None)
            row = col.row(align=True)
            shown = cur == 0 if cur is not None else bool(base_obj and not base_obj.hide_get())
            op = row.operator("gcrip.set_expression", text="default", depress=shown)
            op.base, op.texture = base, ""
            for i, (tex, o) in enumerate(clones):
                if i and i % 4 == 0:
                    row = col.row(align=True)
                on = (cur == i + 1) if cur is not None else not o.hide_get()
                op = row.operator("gcrip.set_expression", text=tex, depress=on)
                op.base, op.texture = base, tex
        box = lay.box()
        box.label(text="Rig", icon="ARMATURE_DATA")
        arms = _armatures(fam)
        if arms:
            std = sum(1 for b in arms[0].data.bones if b.get(STD_KEY) or b.get(ORIG_KEY))
            box.label(text=f"{len(arms[0].data.bones)} bones, {std} mapped to Mixamo names")
            r = box.row(align=True)
            r.operator("gcrip.rename_bones", text="Mixamo names").to_mixamo = True
            r.operator("gcrip.rename_bones", text="Original names").to_mixamo = False
            box.operator("gcrip.auto_map", icon="BONE_DATA")
        else:
            box.label(text="(no armature)")
        row = lay.row(align=True)
        row.operator("gcrip.hide_variants", icon="HIDE_ON")
        row.operator("gcrip.set_fps", icon="TIME")
        lay.operator("gcrip.add_asset_library", icon="ASSET_MANAGER")


def _menu_import(self, context):
    self.layout.operator(GCRIP_OT_import.bl_idname, text="GCRip glTF (.gltf)")


CLASSES = (
    GCRIP_Prefs,
    GCRIP_OT_import,
    GCRIP_OT_hide_variants,
    GCRIP_OT_rename_bones,
    GCRIP_OT_auto_map,
    GCRIP_OT_set_expression,
    GCRIP_OT_set_fps,
    GCRIP_OT_add_library,
    GCRIP_LibItem,
    GCRIP_LibProps,
    GCRIP_UL_models,
    GCRIP_OT_lib_add_root,
    GCRIP_OT_lib_scan,
    GCRIP_OT_lib_forget,
    GCRIP_OT_lib_spawn,
    GCRIP_PT_library,
    GCRIP_MocapProps,
    GCRIP_OT_mocap_retarget,
    GCRIP_PT_mocap,
    GCRIP_OT_server_start,
    GCRIP_OT_server_stop,
    GCRIP_PT_server,
    GCRIP_PT_panel,
)


def register():
    global _PCOLL
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.gcrip_lib = PointerProperty(type=GCRIP_LibProps)
    bpy.types.Scene.gcrip_mocap = PointerProperty(type=GCRIP_MocapProps)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    _PCOLL = bpy.utils.previews.new()  # the index cache loads on first use of the panel
    if not bpy.app.background:
        bpy.app.timers.register(_autostart, first_interval=0.5)


def unregister():
    global _PCOLL
    server_stop()
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    del bpy.types.Scene.gcrip_lib
    del bpy.types.Scene.gcrip_mocap
    if _PCOLL is not None:
        bpy.utils.previews.remove(_PCOLL)
        _PCOLL = None
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
