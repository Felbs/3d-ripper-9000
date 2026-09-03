"""Smashing Drive phases (gcrip.formats.pov_level): the ``TG_<phase>.BIN`` record of a
phase ``.wad`` becomes one Scene - every ``PHM`` of that wad nobody places (the buildings and
road, already in world coordinates) plus the placed props and traffic, looked up by the
record id of any ``.wad`` on the disc (the phase's own, then ``COMMON.WAD``)."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import pov_level, pov_model, toc_wad
from gcrip.plugins import pov_model as model_plugin
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "pov_level"
_IDS_ATTR = "_pov_wad_ids"


def detect(path: str, head: bytes, size: int) -> bool:
    base = posixpath.basename(path).upper()
    return base.startswith("TG_") and base.endswith(".BIN") and pov_level.is_level(head, size)


def _container(src, path: str) -> str | None:
    entry = src.by_path.get(path) if hasattr(src, "by_path") else None
    parent = getattr(entry, "container", None)
    if parent:
        return parent
    folder = posixpath.dirname(path)
    return folder if folder.lower().endswith(".wad") else None


def _wad_ids(src, wad: str) -> dict[int, str]:
    """record id -> member path of every PHM in a wad (cached on the source)."""
    cache = getattr(src, _IDS_ATTR, None)
    if cache is None:
        cache = {}
        with contextlib.suppress(Exception):
            setattr(src, _IDS_ATTR, cache)
    if wad in cache:
        return cache[wad]
    ids: dict[int, str] = {}
    try:
        for name, m in toc_wad.named(src.get(wad)):
            if m.kind == "PHM":
                ids.setdefault(pov_level.record_id(m.user), f"{wad}/{name}")
    except Exception:  # noqa: BLE001 - a wad that will not open places nothing
        pass
    cache[wad] = ids
    return ids


def _lookup(src, own: str) -> list[dict[int, str]]:
    """Id tables to consult: the phase's wad first, then the others (COMMON.WAD)."""
    wads = [own]
    for p in getattr(src, "by_path", {}) or {}:
        if p.lower().endswith(".wad") and p != own:
            wads.append(p)
    wads.sort(key=lambda p: (p != own, "common" not in p.lower(), p))
    return [_wad_ids(src, w) for w in wads]


def _model(src, path: str, cache: dict, warnings: list[str]):
    if path in cache:
        return cache[path]
    model = None
    try:
        model = pov_model.parse(src.get(path))
    except Exception as e:  # noqa: BLE001 - one bad model, the rest of the level stands
        warnings.append(f"{path}: {e}")
    cache[path] = model
    return model


def extract(data: bytes, path: str, src) -> list[Scene]:
    level = pov_level.parse(data)
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    scene.warnings += level.warnings
    if src is None or not hasattr(src, "by_path"):
        return []  # legitimate: the models live in the wads around the layout
    own = _container(src, path)
    if own is None:
        return []  # legitimate: a layout outside its wad places nothing
    tables = _lookup(src, own)
    placements = level.placements
    placed: set[str] = set()
    instances: list[tuple[str, np.ndarray | None, tuple[float, float, float]]] = []
    missing = 0
    for p in placements:
        target = next((t[p.model] for t in tables if p.model in t), None)
        if target is None:
            missing += 1
            continue
        placed.add(target)
        instances.append((target, p.matrix(), p.position))
    # the phase layout is the one named after its wad (SmashLoadPhase asks for "TG_%s"):
    # the buildings and road go with it, not with the intro / ending / smog scenes
    stem = posixpath.basename(own).rsplit(".", 1)[0].upper()
    phase = posixpath.basename(path).rsplit(".", 1)[0].upper() == f"TG_{stem}"
    if phase:
        for _mid, target in sorted(tables[0].items()):
            if target not in placed:
                instances.append((target, None, (0.0, 0.0, 0.0)))
    if missing:
        scene.warnings.append(f"{missing} placements name a record id no wad carries")
    models: dict = {}
    materials: dict[str, int] = {}
    decoded: dict[str, str | None] = {}
    groups: dict[int, list] = {}
    for target, rot, pos in instances:
        model = _model(src, target, models, scene.warnings)
        if model is None:
            continue
        positions = model.positions if rot is None else model.positions @ rot
        positions = (positions + np.asarray(pos, np.float32)).astype(np.float32)
        normals = model.normals if rot is None else (model.normals @ rot).astype(np.float32)
        for mesh in model.meshes:
            for mi in np.unique(mesh.materials):
                mi = int(mi)
                key = f"{target}#{mi}"
                if key not in materials:
                    tex = None
                    maps = model.materials[mi] if mi < len(model.materials) else []
                    for ti in maps:
                        if ti >= len(model.texture_defs):
                            continue
                        name = model.texture_defs[ti]
                        if name not in decoded:
                            img = model_plugin._texture(src, target, name, scene.warnings)
                            decoded[name] = None
                            if img is not None:
                                scene.textures[name] = img
                                decoded[name] = name
                        if decoded[name]:
                            tex = decoded[name]
                            break
                    # one material a texture: the level shares lamps and road tiles
                    mkey = tex or key
                    if mkey not in materials:
                        scene.materials.append(
                            MaterialDef(name=mkey, texture=tex, double_sided=True)
                        )
                        materials[mkey] = len(scene.materials) - 1
                    materials[key] = materials[mkey]
                sel = mesh.materials == mi
                tri = mesh.triangles[sel]
                used, inv = np.unique(tri.reshape(-1), return_inverse=True)
                groups.setdefault(materials[key], []).append(
                    (
                        positions[used],
                        normals[used],
                        model.uvs[used],
                        model.colors[used],
                        inv.reshape(-1).astype(np.uint32),
                    )
                )
    for mi, parts in groups.items():
        base = 0
        idx = []
        for pos, _n, _u, _c, ind in parts:
            idx.append(ind + base)
            base += len(pos)
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=np.concatenate([p[0] for p in parts]),
                indices=np.concatenate(idx).astype(np.uint32),
                normals=np.concatenate([p[1] for p in parts]),
                uvs=np.concatenate([p[2] for p in parts]),
                colors=np.concatenate([p[3] for p in parts]),
            )
        )
    if not scene.primitives:
        return []  # legitimate: nothing to place and no world-space models in the wad
    scene.extras = {
        "format": "pov_level",
        "phase": phase,
        "cells": len(level.cells),
        "sections": len(level.sections),
        "placed": sum(1 for i in instances if i[1] is not None),
        "world_models": sum(1 for i in instances if i[1] is None),
        "models": len(models),
    }
    return [scene]
