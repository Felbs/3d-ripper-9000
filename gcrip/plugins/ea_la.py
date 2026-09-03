"""EA Los Angeles (Medal of Honor: Frontline, Rising Sun; GoldenEye: Rogue Agent): ``.msh``
static meshes and ``.cpt`` level compartments (gcrip.formats.ea_la).

Frontline (2002): one Scene a file, textures decoded from the ``SHPG`` shapes embedded in
the material tables; a compartment's geometry file binds through the level's ``_Art.cpt``
beside it when its own tables carry no shapes.

Rising Sun / GoldenEye (2003-04): the files wrap EAGL objects whose symbol tables live in
the level's ``symbols.rtc`` (``.msh``) or the ``<name>.rtc`` beside a compartment; one Scene
per embedded model, textures from the ``.gsh`` / ``.csf`` shape files and the ``_Art.cpt``
shape bundle of the level - in the same container first, then the containers beside it
(``comp.viv`` compartments draw on ``level.viv``)."""

from __future__ import annotations

import contextlib
import posixpath
import struct

import numpy as np

from gcrip.formats import ea_la, ea_shape, eagl
from gcrip.plugins import eagl as eagl_plugin
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_la"


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".msh"):
        return ea_la.is_msh(head, size) or ea_la.is_eagl_msh(head, size)
    return low.endswith(".cpt") and (ea_la.is_cpt(head, size) or ea_la.is_eagl_cpt(head, size))


# ---------------------------------------------------------------------------
# 2003-04 EAGL wrappers
# ---------------------------------------------------------------------------

_SHAPE_INDEX_ATTR = "_ea_la_shape_index"


def _level_paths(src, path: str) -> list[str]:
    """Manifest paths in the same container as ``path`` and in the containers / files of the
    directory that container lives in (comp.viv <-> level.viv <-> symbols.rtc)."""
    folder = posixpath.dirname(path)
    parent = posixpath.dirname(folder)
    out = []
    for p in getattr(src, "by_path", {}) or {}:
        holder = posixpath.dirname(p)
        if holder in (folder, parent) or posixpath.dirname(holder) == parent:
            out.append(p)
    return out


def _rtc_tables(src, path: str, msh: bool) -> dict[int, bytes]:
    if src is None or not hasattr(src, "by_path"):
        return {}
    folder = posixpath.dirname(path)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    want = "symbols.rtc" if msh else stem.lower() + ".rtc"
    candidates = [p for p in _level_paths(src, path) if posixpath.basename(p).lower() == want]
    candidates.sort(key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in candidates:
        with contextlib.suppress(Exception):
            tables = ea_la.rtc_tables(src.get(p))
            if tables:
                return tables
    return {}


def _shape_index(src, path: str) -> dict[str, tuple[str, bool]]:
    """shape name -> (manifest path, is a .cpt wrapper) over the level's .gsh / .csf shape
    files and _Art.cpt bundles (header reads only; cached on the source per level)."""
    cache = getattr(src, _SHAPE_INDEX_ATTR, None)
    if cache is None:
        cache = {}
        with contextlib.suppress(Exception):
            setattr(src, _SHAPE_INDEX_ATTR, cache)
    folder = posixpath.dirname(path)
    key = posixpath.dirname(folder)
    if key in cache:
        return cache[key]
    index: dict[str, tuple[str, bool]] = {}
    paths = _level_paths(src, path)
    paths.sort(key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in paths:
        low = p.lower()
        try:
            if low.endswith((".gsh", ".csf")):
                for name in ea_shape.shape_names(src.get(p)[:0x4010]):
                    index.setdefault(name, (p, False))
            elif low.endswith(".cpt"):
                head = src.get(p)[:16]
                if struct.unpack_from(">I", head, 0)[0] == ea_la.CPT_EAGL_VERSION:
                    blob = ea_la.cpt_shapes(src.get(p))
                    if blob:
                        for name in ea_shape.shape_names(blob[:0x4010]):
                            index.setdefault(name, (p, True))
        except Exception:  # noqa: BLE001 - one bad bundle, the rest index
            continue
    cache[key] = index
    return index


def _extract_eagl(data: bytes, path: str, src) -> list[Scene]:
    msh = struct.unpack_from(">I", data, 0)[0] == ea_la.MSH_EAGL_VERSION
    tables = _rtc_tables(src, path, msh)
    objects = [ea_la.eagl_msh_object(data, tables)] if msh else ea_la.eagl_cpt_objects(data, tables)
    lookup = _shape_index(src, path) if src is not None else {}
    own = ea_la.cpt_shapes(data) if not msh else None

    def resolve(name: str, warnings: list[str]) -> np.ndarray | None:
        blobs = []
        if own is not None:
            blobs.append(("embedded shapes", own))
        hit = lookup.get(name)
        if hit is not None:
            p, wrapped = hit
            with contextlib.suppress(Exception):
                blobs.append((p, ea_la.cpt_shapes(src.get(p)) if wrapped else src.get(p)))
        for label, blob in blobs:
            if not blob:
                continue
            try:
                for s in ea_shape.parse(blob):
                    if s.name == name and s.rgba is not None:
                        return s.rgba
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{label}: {e}")
        return None

    scenes: list[Scene] = []
    errors: list[str] = []
    for k, obj_data in enumerate(objects):
        try:
            obj = eagl.parse(obj_data)
            scenes += eagl_plugin.build_scenes(obj, resolve)
        except (eagl.EaglError, struct.error, ValueError) as e:
            errors.append(f"object {k}: {e}")
    if not scenes and errors:
        raise eagl.EaglError("; ".join(errors[:3]))
    # legitimate: a level's _Art.cpt carries its textures (or nothing at all) and no models
    return scenes


def _art_materials(src, path: str) -> tuple[bytes, list[ea_la.Material]] | None:
    """The ``<level>_Art.cpt`` in the parent level.viv of a comp.viv compartment."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    level = stem.split("_ART", 1)[0].split("_Art", 1)[0]
    candidates = [
        p for p in src.by_path if p.lower().endswith("_art.cpt") and level.lower() in p.lower()
    ]
    candidates.sort(key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in candidates:
        try:
            art = src.get(p)
            model = ea_la.parse(art)
        except Exception:  # noqa: BLE001 - a bad art file leaves the compartment untextured
            continue
        if model.materials:
            return art, model.materials
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    version = struct.unpack_from(">I", data, 0)[0]
    if version in (ea_la.MSH_EAGL_VERSION, ea_la.CPT_EAGL_VERSION):
        return _extract_eagl(data, path, src)
    model = ea_la.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    art = None
    if any(m.shared is not None for m in model.materials) and path.lower().endswith(".cpt"):
        art = _art_materials(src, path)
    art_tables: list[list[ea_la.Material]] = [[], []]
    if art is not None:
        for m in art[1]:
            art_tables[m.table].append(m)
    materials: dict[int, int] = {}
    cache: dict[tuple[int, int], str | None] = {}
    for ch in model.chunks:
        if ch.material not in materials:
            key = None
            if 0 <= ch.material < len(model.materials):
                m = model.materials[ch.material]
                blob = data
                if m.shared is not None and art is not None:
                    table = art_tables[m.table]
                    if m.shared < len(table):
                        m, blob = table[m.shared], art[0]
                ck = (id(blob), m.shape)
                if ck not in cache:
                    img = None
                    try:
                        img = ea_la.material_texture(blob, m)
                    except Exception as e:  # noqa: BLE001 - one bad shape, the rest bind
                        scene.warnings.append(f"material {ch.material}: {e}")
                    name = f"shape_{'art_' if blob is not data else ''}{m.shape:x}"
                    if img is not None:
                        scene.textures[name] = img
                    cache[ck] = name if img is not None else None
                key = cache[ck]
            materials[ch.material] = len(scene.materials)
            scene.materials.append(MaterialDef(name=f"material_{ch.material}", texture=key))
        scene.primitives.append(
            Primitive(
                material=materials[ch.material],
                positions=np.ascontiguousarray(ch.positions, dtype=np.float32),
                indices=ch.triangles.reshape(-1).astype(np.uint32),
                normals=ch.normals,
                uvs=ch.uvs,
                colors=ch.colors,
            )
        )
    return [scene] if scene.primitives else []
