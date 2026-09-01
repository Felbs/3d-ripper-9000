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

The add-on only uses the custom properties gcrip writes into the glTF
(gcrip_variant_of, gcrip_texture, gcrip_std_bone, gcrip_joint), so it works on
any gcrip output.
"""

bl_info = {
    "name": "GCRip glTF helpers",
    "author": "gcrip",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > GCRip glTF; 3D View > Sidebar > GCRip",
    "description": "Import gcrip glTF rips with hidden expression meshes, Mixamo bone names, "
    "expression switch panel",
    "category": "Import-Export",
}

import contextlib  # noqa: E402

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


def rename_bones(arm, to_mixamo):
    """Rename bones using the custom props gcrip stored on them. Blender updates vertex
    groups, actions and constraints automatically when a bone is renamed."""
    n = 0
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


def classify(m: dict) -> str:
    """Category of a rip_results.json model entry."""
    path = m.get("path", "")
    name = os.path.basename(path)
    tris = m.get("triangles", 0) or 0
    joints = m.get("joints", 0) or 0
    std = len(m.get("std_bones") or {})
    if _LEVEL_HINTS.search(path) and joints <= 3:
        return "LEVEL"
    if std >= 12:
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


def scan_root(root: str) -> list:
    """[(game_id, title, category, name, gltf, thumb, info), ...] for one rip folder."""
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
                if len(m.get("std_bones") or {}):
                    info += f", {len(m['std_bones'])} Mixamo bones"
                if m.get("animations"):
                    info += f", {len(m['animations'])} clips"
                out.append((gid, title, classify(m), name, gltf, thumb, info))
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
                json.dump({"roots": roots, "records": recs}, fh)
        except Exception as e:  # noqa: BLE001
            print("[gcrip] could not cache index:", e)


def load_index_cache() -> bool:
    try:
        with open(os.path.join(_config_dir(), "library_index.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return False
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
    for gid, _t, c, name, gltf, thumb, info in LIB["records"]:
        if gid != game:
            continue
        if cat != "ALL" and c != cat:
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


class GCRIP_LibProps(bpy.types.PropertyGroup):
    game: EnumProperty(name="Game", items=_game_items, update=_refill)
    category: EnumProperty(name="Category", items=CATEGORIES, default="CHARACTER", update=_refill)
    search: StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_refill)
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
        row.label(text=item.name, icon=icons.get(item.category, "OBJECT_DATA"))
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
        if not os.path.isfile(it.gltf):
            self.report({"ERROR"}, f"missing file: {it.gltf}")
            return {"CANCELLED"}
        before = set(bpy.data.objects)
        bpy.ops.gcrip.import_gltf(
            filepath=it.gltf, mixamo=props.mixamo and it.category == "CHARACTER"
        )
        new = [o for o in bpy.data.objects if o not in before]
        col = bpy.data.collections.get(it.game)
        if col is None:
            col = bpy.data.collections.new(it.game)
            context.scene.collection.children.link(col)
        for o in new:
            for c in o.users_collection:
                c.objects.unlink(o)
            col.objects.link(o)
        roots = [o for o in new if o.parent is None]
        if props.at_cursor and it.category != "LEVEL":
            for o in roots:
                o.location = context.scene.cursor.location
        for o in bpy.data.objects:
            o.select_set(False)
        arms = [o for o in new if o.type == "ARMATURE"]
        pick = arms[0] if arms else (roots[0] if roots else None)
        if pick is not None:
            pick.select_set(True)
            context.view_layer.objects.active = pick
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
        lay.prop(props, "category", text="")
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
from mathutils import Matrix  # noqa: E402

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


def retarget_bvh(arm, bvh_path, ref=0, max_frames=0, name=None):
    """Bake the BVH onto `arm` (Mixamo-named bones) as a new action.

    Returns (action, slot, nframes, fps)."""
    joints, rows, ftime = bvh_parse(bvh_path)
    if max_frames:
        rows = rows[:max_frames]
    profile, rename = bvh_profile([j["name"] for j in joints])
    for j in joints:
        j["name"] = rename.get(j["name"], j["name"])
    frames = [bvh_fk(joints, r) for r in rows]
    alias = {"Chest2": "Chest2_src" if "Chest2_src" in frames[0][0] else "Chest"}
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

    def axes(pos):
        up = _unit(pos("Spine") - pos("Hips"))
        lr = _unit(pos("UpperLeg_L") - pos("UpperLeg_R"))
        sh = _unit(pos("UpperArm_L") - pos("UpperArm_R"))
        fwd = _unit(np.cross(lr, up))
        if np.dot(fwd, _unit(pos("Toes_L") - pos("Foot_L"))) < 0:
            fwd = -fwd
        return {"lr": lr, "sh": sh, "fwd": fwd, "up": up}

    def chain_dir(j, pos, eps):
        if _MOCAP_PRIMARY[j] is None:
            return chain_dir(_MOCAP_DIR_PARENT[j], pos, eps)
        origin, c = pos(j), _MOCAP_PRIMARY[j]
        while c is not None:
            d = pos(c) - origin
            if np.linalg.norm(d) > eps:
                return _unit(d)
            c = _MOCAP_PRIMARY[c]
        raise RuntimeError(f"no distinct joint below {j}")

    src_p = lambda n: src_pos(ref, n)  # noqa: E731
    tgt_p = lambda n: rest_head(_MOCAP_MAP[n])  # noqa: E731
    feet = ("Foot_L", "Foot_R", "Toes_L", "Toes_R")
    src_floor = min(src_p(n)[2] for n in feet)
    tgt_floor = min(tgt_p(n)[2] for n in feet)
    src_h = src_p("Hips")[2] - src_floor
    tgt_h = tgt_p("Hips")[2] - tgt_floor
    AS, AT = axes(src_p), axes(tgt_p)
    W_ref = {}
    for j, b in _MOCAP_MAP.items():
        F_s = _frame3(chain_dir(j, src_p, 0.01 * src_h), AS[_MOCAP_SECONDARY[j]])
        F_t = _frame3(chain_dir(j, tgt_p, 0.01 * tgt_h), AT[_MOCAP_SECONDARY[j]])
        W_ref[b] = F_s @ F_t.T @ rest_rot(b)
    scale = tgt_h / src_h
    origin = src_p("Hips").copy()
    origin[2] = src_floor

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
    inv_map = {b: j for j, b in _MOCAP_MAP.items()}
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
                    desired[:3, 3] = (src_pos(t, "Hips") - origin) * scale
                    desired[2, 3] += tgt_floor
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
        arm = _armatures(fam)[0]
        if "mixamorig:Hips" not in arm.data.bones:
            rename_bones(arm, True)
        missing = [b for b in _MOCAP_MAP.values() if b not in arm.data.bones]
        if missing:
            self.report(
                {"ERROR"}, f"not a humanoid rig - missing {missing[0]} (+{len(missing) - 1})"
            )
            return {"CANCELLED"}
        hidden = hide_static_props(arm, fam)
        if arm.animation_data and mp.mute_game:
            for tr in arm.animation_data.nla_tracks:
                if tr.name != "MOCAP":
                    tr.mute = True
        try:
            act, slot, n, fps = retarget_bvh(arm, path, max_frames=mp.max_frames)
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        track = next((t for t in arm.animation_data.nla_tracks if t.name == "MOCAP"), None)
        if track is None:
            track = arm.animation_data.nla_tracks.new()
            track.name = "MOCAP"
        start = mp.start
        for s in track.strips:
            start = max(start, int(s.frame_end) + 1)
        strip = track.strips.new(act.name, start, act)
        with contextlib.suppress(Exception):
            if slot is not None:
                strip.action_slot = slot
        context.scene.render.fps = fps
        context.scene.render.fps_base = 1.0
        context.scene.frame_end = max(context.scene.frame_end, int(strip.frame_end))
        context.scene.frame_set(start)
        self.report(
            {"INFO"},
            f"{act.name}: {n} frames on NLA track MOCAP at {start}"
            + (f", hid {len(hidden)} static prop mesh(es)" if hidden else ""),
        )
        return {"FINISHED"}


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
        else:
            box.label(text="(no armature)")
        row = lay.row(align=True)
        row.operator("gcrip.hide_variants", icon="HIDE_ON")
        row.operator("gcrip.set_fps", icon="TIME")
        lay.operator("gcrip.add_asset_library", icon="ASSET_MANAGER")


def _menu_import(self, context):
    self.layout.operator(GCRIP_OT_import.bl_idname, text="GCRip glTF (.gltf)")


CLASSES = (
    GCRIP_OT_import,
    GCRIP_OT_hide_variants,
    GCRIP_OT_rename_bones,
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


def unregister():
    global _PCOLL
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
