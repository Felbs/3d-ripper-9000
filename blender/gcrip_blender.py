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

The add-on only uses the custom properties gcrip writes into the glTF
(gcrip_variant_of, gcrip_texture, gcrip_std_bone, gcrip_joint), so it works on
any gcrip output.
"""

bl_info = {
    "name": "GCRip glTF helpers",
    "author": "gcrip",
    "version": (0, 2, 0),
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
                with contextlib.suppress(Exception), bpy.context.temp_override(
                    window=window, area=area, region=region
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
    GCRIP_PT_panel,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
