"""Ubisoft Jade engine (Beyond Good & Evil GGEE41, Prince of Persia: The Sands of
Time GPTE41): the .bf big file is the container, every level is a binarized
ROOT/Bin/ff0xxxxx.bin pack (LZO) with its geometry (and, for PoP, its textures);
BG&E keeps textures in a sibling ff8xxxxx.bin pack.

What comes out of a map pack:
  * one Scene per GEO geometric object - positions, UVs, vertex colours /
    normals where present, one material per element with its texture, found by
    walking the object graph: game object (GAO) -> material (MAT_MSM slot list
    / MAT_MTT levels / MAT_SIN) -> texture key (gcrip.formats.jade_obj);
  * one placed Scene per world (WOW) in the pack: every drawn game object's
    geometry transformed by its world matrix;
  * (PoP) one textures-only Scene per pack holding every texture that decodes.
A BG&E textures pack gives the textures-only Scene, named by texture key.

BG&E levels reference objects the game loads once from its fix world
(_main_fix, ff0084df.bin); that pack is indexed first and chained behind every
level so those materials resolve.

See gcrip.formats.jade / jade_obj for the structures and their sources.
"""

from __future__ import annotations

import hashlib
import re
import struct

import numpy as np

from gcrip.formats import j3d, jade, jade_bf, jade_lzo, jade_obj
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "jade"

_BIN_RE = re.compile(r"(?:^|/)ROOT/Bin/[^/]*?([0-9a-fA-F]{8})\.bin$")

# the fix world list per big file (Ray1Map's Jade_BGE_Manager.FixWorlds)
FIX_KEYS = {"sally.bf": 0xFF0084DF}


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".bf") and jade_bf.is_bf(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return jade_bf.expand(data)


def _bin_key(path: str) -> int | None:
    m = _BIN_RE.search(path)
    return int(m.group(1), 16) if m else None


def detect(path: str, head: bytes, size: int) -> bool:
    key = _bin_key(path)
    if key is None or ".bf/" not in path.lower():
        return False
    return jade_bf.key_type(key) in ("map", "textures") and size > 8


# ---------------------------------------------------------------------------
# fetching the pack bytes
# ---------------------------------------------------------------------------


def _container_bytes(src, container: str) -> bytes:
    payload = getattr(src, "_payload", None)  # gcrip.rip caches whole containers here
    if callable(payload):
        return payload(container)
    return src.get(container)


def _container_of(path: str, src) -> str | None:
    by_path = getattr(src, "by_path", {}) or {}
    entry = by_path.get(path)
    container = getattr(entry, "container", None)
    if container is not None:
        return container
    cut = path.lower().rfind(".bf/")
    return path[: cut + 3] if cut >= 0 else None


class _BfContext:
    """One big file: its table, the fix world and the last level indexed."""

    def __init__(self, container: str, bf: bytes):
        self.container = container
        self.bf = bf
        self.entries = {e.key: e for e in jade_bf.parse(bf)}
        self.fix: tuple[jade_obj.World, dict[str, np.ndarray]] | None = None
        self.fix_tried = False
        self.spe: set[int] = set()
        self.levels: dict[int, tuple[jade_obj.World, dict[str, np.ndarray]]] = {}
        self._global: dict[int, int] | None = None
        self.foreign: dict[int, tuple[jade_obj.World, dict[str, np.ndarray]]] = {}

    def pack(self, key: int) -> bytes | None:
        e = self.entries.get(key)
        if e is None:
            return None
        return jade_lzo.decompress_blocks(self.bf[e.offset : e.offset + e.size])

    # -- Montreal (PoP): keyed packs, so objects another pack needs (the Prince's
    # textures sit in his costume packs) can be found through a key -> pack index
    def global_index(self) -> dict[int, int]:
        if self._global is None:
            index: dict[int, int] = {}
            for pk in self.entries:
                if jade_bf.key_type(pk) != "map":
                    continue
                try:
                    dec = self.pack(pk)
                except jade_lzo.LzoError:
                    continue
                if dec is None or not jade.is_montreal(dec):
                    continue
                for ent in jade.walk_montreal(dec):
                    index.setdefault(ent.key, pk)
            self._global = index
        return self._global

    def resolve(self, key: int) -> tuple[jade_obj.World, dict[str, np.ndarray]] | None:
        """The indexed pack holding `key` (Montreal only), or None."""
        pk = self.global_index().get(key)
        if pk is None:
            return None
        hit = self.foreign.get(pk)
        if hit is None:
            try:
                hit = self._index(pk, None)
            except (jade.JadeError, jade_lzo.LzoError, ValueError):
                return None
            if len(self.foreign) >= 12:
                self.foreign.pop(next(iter(self.foreign)))
            self.foreign[pk] = hit
        return hit

    def load_fix(self, src) -> tuple[jade_obj.World, dict[str, np.ndarray]] | None:
        if self.fix_tried:
            return self.fix
        self.fix_tried = True
        key = FIX_KEYS.get(self.container.rsplit("/", 1)[-1].lower())
        if key is None or key not in self.entries:
            return None
        spe_path = self.container.rsplit("/", 1)[0] + "/jade.spe"
        try:
            spe = src.get(spe_path)
            self.spe = set(struct.unpack(f"<{len(spe) // 4}I", spe[: len(spe) // 4 * 4]))
        except Exception:  # noqa: BLE001 - no special array: nothing is shared
            self.spe = set()
        try:
            self.fix = self._index(key, None)
        except (jade.JadeError, jade_lzo.LzoError, ValueError):
            self.fix = None
        return self.fix

    def _index(self, key: int, fix) -> tuple[jade_obj.World, dict[str, np.ndarray]]:
        dec = self.pack(key)
        if dec is None:
            raise jade.JadeError(f"pack {key:08x} not in {self.container}")
        if jade.is_montreal(dec):
            entries = jade.walk_montreal(dec)
            world = jade_obj.index_montreal(entries)
            textures = _TextureStore(jade.textures_montreal(entries), self)
            world.resolver = lambda k: (self.resolve(k) or (None,))[0]
        else:
            preloaded = set()
            if fix is not None:
                preloaded = set(fix[0].raw) & self.spe
            world = jade_obj.index_montpellier(dec, preloaded)
            textures = {}
            tdec = self.pack((key & 0xFFFFF) | 0xFF800000)
            if tdec is not None:
                textures = jade.textures_montpellier(jade.walk_montpellier(tdec), world.tex_order)
            if fix is not None:
                world.parent = fix[0]
                textures = {**fix[1], **textures}
        return world, textures

    def level(self, key: int, src) -> tuple[jade_obj.World, dict[str, np.ndarray]]:
        hit = self.levels.get(key)
        if hit is not None:
            return hit
        fix = self.load_fix(src)
        if fix is not None and key == FIX_KEYS.get(self.container.rsplit("/", 1)[-1].lower()):
            return fix
        result = self._index(key, fix)
        self.levels = {key: result}  # one level at a time
        return result


class _TextureStore(dict):
    """Textures of a pack, falling back to the pack that holds a foreign key."""

    def __init__(self, base: dict[str, np.ndarray], ctx: _BfContext):
        super().__init__(base)
        self.ctx = ctx
        self.missing: set[str] = set()

    def _fetch(self, name: str) -> np.ndarray | None:
        if name in self.missing or len(name) != 8:
            return None
        try:
            key = int(name, 16)
        except ValueError:
            return None
        hit = self.ctx.resolve(key)
        img = dict.get(hit[1], name) if hit is not None else None  # no second fallback
        if img is None:
            self.missing.add(name)
            return None
        self[name] = img
        return img

    def __contains__(self, name) -> bool:
        return dict.__contains__(self, name) or self._fetch(name) is not None

    def get(self, name, default=None):
        if dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        img = self._fetch(name)
        return default if img is None else img

    def __getitem__(self, name):
        if dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        img = self._fetch(name)
        if img is None:
            raise KeyError(name)
        return img


_contexts: dict[str, _BfContext] = {}


def _context(path: str, data: bytes, src) -> _BfContext | None:
    container = _container_of(path, src)
    if container is None:
        return None
    ctx = _contexts.get(container)
    bf = _container_bytes(src, container)
    stale = ctx is not None and ctx.bf is not bf
    if stale and (len(ctx.bf) != len(bf) or ctx.bf[:4096] != bf[:4096]):
        ctx = None  # same name, other bytes
    if ctx is None:
        if not jade_bf.is_bf(bf):
            return None
        _contexts.clear()  # one big file at a time
        ctx = _BfContext(container, bf)
        _contexts[container] = ctx
    return ctx


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------


def _to_yup(v: np.ndarray) -> np.ndarray:
    """Jade is Z-up; glTF is Y-up."""
    out = np.empty_like(v)
    out[:, 0] = v[:, 0]
    out[:, 1] = v[:, 2]
    out[:, 2] = -v[:, 1]
    return out


def _material_def(sm: jade_obj.SlotMaterial | None, slot: int, textures: dict) -> MaterialDef:
    if sm is None:
        return MaterialDef(name=f"mat{slot}", texture=None)
    tex = f"{sm.texture:08x}" if not jade_obj.is_null(sm.texture) else None
    if tex is not None and tex not in textures:
        tex = None
    return MaterialDef(
        name=f"{sm.key:08x}_{slot}",
        texture=tex,
        base_color=sm.color,
        alpha_blend=sm.alpha,
        clamp_u=sm.clamp_u,
        clamp_v=sm.clamp_v,
    )


def geo_primitives(
    g: jade.Geo, transform: np.ndarray | None = None, instance_colors: np.ndarray | None = None
) -> list[tuple[int, Primitive]]:
    """(material slot, primitive) per element, positions in glTF space; `transform`
    is a Jade-space 4x4 applied first, `instance_colors` the game object's own
    per-vertex lighting (BG&E) that replaces the GEO's."""
    verts = g.vertices.astype(np.float64)
    nrm = g.normals.astype(np.float64) if g.normals is not None else None
    if transform is not None:
        verts = verts @ transform[:3, :3].T + transform[:3, 3]
        if nrm is not None:
            nrm = nrm @ transform[:3, :3].T
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.divide(nrm, ln, out=np.zeros_like(nrm), where=ln > 0)
    verts = _to_yup(verts.astype(np.float32))
    nrm = _to_yup(nrm.astype(np.float32)) if nrm is not None else None
    colors = None
    if instance_colors is not None and len(instance_colors) == len(verts):
        colors = instance_colors.astype(np.float32) / 255.0
    elif g.colors is not None and len(g.colors) == len(verts):
        colors = g.colors.astype(np.float32) / 255.0
        if colors[:, :3].mean() < 0.06:  # BG&E levels: lit per instance, black in the GEO
            colors = None
    if colors is not None:
        colors[:, 3] = 1.0  # the alpha is a lighting channel (0 in BG&E), not opacity
    uvs = g.uvs.astype(np.float32)
    out = []
    for el in g.elements:
        if el.strips:
            corners = np.concatenate(
                [
                    np.concatenate(
                        [s[j3d.triangulate(j3d.PRIM_TRISTRIP, len(s)).reshape(-1)]]
                        if len(s) >= 3
                        else [np.zeros((0, 4), np.int64)]
                    )
                    for s in el.strips
                ]
            )
            if len(corners) == 0:
                continue
            vi, ni, ci, ui = corners[:, 0], corners[:, 1], corners[:, 2], corners[:, 3]
        else:
            t = el.triangles.astype(np.int64)
            if len(t) == 0:
                continue
            vi = t[:, :3].reshape(-1)
            ui = t[:, 3:6].reshape(-1)
            ni = vi
            ci = vi
        vi = np.clip(vi, 0, max(0, len(verts) - 1))
        ui = np.clip(ui, 0, max(0, len(uvs) - 1))
        key = np.stack([vi, ui, ni, ci], axis=1)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        pos = verts[uniq[:, 0]]
        uv = uvs[uniq[:, 1]] if len(uvs) else None
        normals = None
        if nrm is not None:
            normals = nrm[np.clip(uniq[:, 2], 0, len(nrm) - 1)]
        col = None
        if colors is not None:
            col = colors[np.clip(uniq[:, 3], 0, len(colors) - 1)]
        out.append(
            (
                el.material,
                Primitive(
                    material=0,
                    positions=pos.astype(np.float32),
                    indices=inv.reshape(-1).astype(np.uint32),
                    normals=normals,
                    uvs=uv,
                    colors=col,
                ),
            )
        )
    return out


class _SceneBuilder:
    """Accumulates primitives and de-duplicates materials by (material key, slot)."""

    def __init__(self, name: str, world: jade_obj.World | None, textures: dict[str, np.ndarray]):
        self.scene = Scene(name=name)
        self.world = world
        self.textures = textures
        self.index: dict[tuple, int] = {}

    def add(
        self,
        g: jade.Geo,
        mat_key: int | None,
        transform: np.ndarray | None = None,
        instance_colors: np.ndarray | None = None,
    ) -> None:
        self.scene.warnings += [w for w in g.warnings if w not in self.scene.warnings]
        for slot, prim in geo_primitives(g, transform, instance_colors):
            sm = None
            if self.world is not None and mat_key is not None:
                sm = jade_obj.resolve_slot(self.world, mat_key, slot)
            mkey = (sm.key, slot) if sm is not None else (None, slot)
            mi = self.index.get(mkey)
            if mi is None:
                mi = len(self.scene.materials)
                self.index[mkey] = mi
                md = _material_def(sm, slot, self.textures)
                self.scene.materials.append(md)
                if md.texture:
                    self.scene.textures[md.texture] = self.textures[md.texture]
            prim.material = mi
            self.scene.primitives.append(prim)

    def done(self) -> Scene:
        return self.scene


def geo_to_scene(
    g: jade.Geo,
    name: str,
    world: jade_obj.World | None = None,
    mat_key: int | None = None,
    textures: dict[str, np.ndarray] | None = None,
) -> Scene:
    b = _SceneBuilder(name, world, textures or {})
    b.add(g, mat_key)
    return b.done()


def world_scene(w: jade_obj.World, wow: jade_obj.Wow, name: str, textures: dict) -> Scene | None:
    """Every drawn game object of the world, placed by its matrix."""
    b = _SceneBuilder(name, w, textures)
    placed = 0
    for k in wow.gaos:
        g = w.find_gao(k)
        if g is None or g.is_bone or jade_obj.is_null(g.geo) or g.matrix is None:
            continue
        geo = w.geo_of(g.geo)
        if geo is None or geo.triangle_count == 0:
            continue
        b.add(geo, g.mat if not jade_obj.is_null(g.mat) else None, g.matrix, g.vertex_colors)
        placed += 1
    if placed < 2:
        return None
    scene = b.done()
    scene.extras = {"placed_objects": placed, "world": wow.name}
    return scene


def _textures_scene(name: str, textures: dict[str, np.ndarray]) -> Scene:
    """No geometry; one material per texture so the glTF writer emits the PNGs."""
    scene = Scene(name=name)
    seen: dict[str, str] = {}
    uniq: dict[str, np.ndarray] = {}
    for k, img in textures.items():  # identical images under different keys are common
        h = hashlib.sha1(img.tobytes()).hexdigest()
        if h in seen:
            continue
        seen[h] = k
        uniq[k] = img
    scene.textures = uniq
    scene.materials = [MaterialDef(name=k, texture=k) for k in uniq]
    scene.extras = {"textures_only": True}
    return scene


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def _geo_names(w: jade_obj.World) -> dict[int, str]:
    """GEO key -> the name of the first game object drawing it (or its LOD)."""
    out: dict[int, str] = {}
    for g in w.gaos.values():
        name = _safe(g.name[:-4] if g.name.lower().endswith(".gao") else g.name)
        if not name or jade_obj.is_null(g.geo):
            continue
        for k in [g.geo, *w.lods.get(g.geo, [])]:
            out.setdefault(k, name)
    return out


def _pack_scenes(w: jade_obj.World, textures: dict, stem: str) -> list[Scene]:
    scenes: list[Scene] = []
    gm = jade_obj.geo_materials(w)
    names = _geo_names(w)
    for key, g in w.geos.items():
        if g.triangle_count == 0:
            continue
        name = f"{key:08x}_{names[key]}"[:80] if key in names else f"{key:08x}"
        scenes.append(geo_to_scene(g, name, w, gm.get(key), textures))
    for off, g in w.unkeyed_geos:
        if g.triangle_count == 0:
            continue
        scenes.append(geo_to_scene(g, f"geo_{off:06x}", w, None, textures))
    for wow in w.wows:
        s = world_scene(w, wow, f"{stem}_{_safe(wow.name) or 'world'}", textures)
        if s is not None:
            scenes.append(s)
    return scenes


def _entry_key(ctx: _BfContext, path: str, key: int) -> int | None:
    """The big file entry a manifest path names: by key, else by path suffix."""
    if key in ctx.entries:
        return key
    inner = path[len(ctx.container) + 1 :] if path.startswith(ctx.container) else path
    for e in ctx.entries.values():
        if e.path == inner or e.path.endswith("/" + inner) or inner.endswith(e.path):
            return e.key
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    key = _bin_key(path) or 0
    ctx = _context(path, data, src)
    if ctx is not None:
        key = _entry_key(ctx, path, key) or key
    stem = f"{key:08x}"
    if ctx is None or key not in ctx.entries:
        # not inside a big file we can read: treat the bytes as the pack itself
        if not jade_lzo.is_jade_blocks(data):
            raise jade.JadeError("pack is not inside a .bf big file")
        dec = jade_lzo.decompress_blocks(data)
        if jade.is_montreal(dec):
            entries = jade.walk_montreal(dec)
            w = jade_obj.index_montreal(entries)
            textures = jade.textures_montreal(entries)
        else:
            w = jade_obj.index_montpellier(dec)
            textures = jade.textures_montpellier(jade.walk_montpellier(dec), w.tex_order)
        scenes = _pack_scenes(w, textures, stem)
        if textures:
            scenes.append(_textures_scene(f"{stem}_textures", textures))
        return scenes
    kind = jade_bf.key_type(key)
    if kind == "textures":
        map_key = (key & 0xFFFFF) | 0xFF000000
        if map_key not in ctx.entries:
            dec = ctx.pack(key)
            textures = jade.textures_montpellier(jade.walk_montpellier(dec or b""))
        else:
            _w, textures = ctx.level(map_key, src)
            fix = ctx.fix[1] if ctx.fix is not None and map_key != FIX_KEYS.get(
                ctx.container.rsplit("/", 1)[-1].lower()
            ) else {}
            textures = {k: v for k, v in textures.items() if k not in fix}
        return [_textures_scene(f"{stem}_textures", textures)] if textures else []
    w, textures = ctx.level(key, src)
    scenes = _pack_scenes(w, textures, stem)
    if w.montreal and textures:
        scenes.append(_textures_scene(f"{stem}_textures", textures))
    return scenes
