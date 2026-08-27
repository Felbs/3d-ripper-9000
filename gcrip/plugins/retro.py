"""Retro Studios formats (Metroid Prime, Metroid Prime 2: Echoes): PAK containers expand
to `<name>_0x<id>.<TYPE>` / `0x<id>.<TYPE>` members; CMDL models and MREA area geometry
become Scenes with their TXTR textures decoded from the same PAK. A CMDL that an ANCS
character references gets its CINF skeleton and CSKR weights."""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

from gcrip.formats import retro_cmdl, retro_mrea, retro_pak, retro_scene, retro_skin, retro_txtr
from ripcore.scene import Joint, Scene

NAME = "retro"

_index_cache: dict[tuple[int, int, str], dict] = {}


def detect(path: str, head: bytes, size: int) -> bool:
    if len(head) < 8:
        return False
    magic, version = struct.unpack_from(">II", head, 0)
    if magic == retro_cmdl.MAGIC and version in (2, 3, 4):
        return path.upper().endswith(".CMDL") or size >= 0x60
    if magic == retro_mrea.MAGIC and version in retro_mrea.VERSIONS:
        return path.upper().endswith(".MREA") or size >= 0x80
    return False


def is_container(name: str, head: bytes) -> bool:
    return retro_pak.is_pak(name, head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return retro_pak.expand(data)


def _cached(src: Any, key: str, build):
    k = (id(src), len(getattr(src, "by_path", ())), key)
    v = _index_cache.get(k)
    if v is None:
        v = build()
        if len(_index_cache) > 128:
            _index_cache.clear()
        _index_cache[k] = v
    return v


class _Siblings:
    """Resolves (type, id) -> manifest path among the PAK members next to `path`,
    falling back to every Retro resource in the manifest."""

    def __init__(self, src: Any, path: str):
        self.src = src
        self.dir = path.rsplit("/", 1)[0] if "/" in path else ""
        self.cache: dict[int, np.ndarray | None] = {}

    def _index(self, dir_: str | None) -> dict[tuple[str, int], str]:
        def build():
            idx: dict[tuple[str, int], str] = {}
            for p in getattr(self.src, "by_path", {}):
                if dir_ is not None and p.rsplit("/", 1)[0] != dir_:
                    continue
                parsed = retro_pak.parse_name(p.rsplit("/", 1)[-1])
                if parsed:
                    idx.setdefault(parsed, p)
            return idx

        return _cached(self.src, f"idx:{dir_ or '*'}", build)

    def path_of(self, type_: str, id_: int) -> str | None:
        return self._index(self.dir).get((type_, id_)) or self._index(None).get((type_, id_))

    def has(self, type_: str, id_: int) -> bool:
        return (type_, id_) in self._index(self.dir)

    def get(self, type_: str, id_: int) -> bytes | None:
        p = self.path_of(type_, id_)
        return self.src.get(p) if p else None

    def texture(self, id_: int) -> np.ndarray | None:
        if id_ in self.cache:
            return self.cache[id_]
        raw = self.get("TXTR", id_)
        img = retro_txtr.decode(raw) if raw else None
        self.cache[id_] = img
        return img

    def characters(self) -> dict[int, tuple[int, int]]:
        """CMDL id -> (CSKR id, CINF id) from every ANCS in this PAK."""

        def build():
            out: dict[int, tuple[int, int]] = {}
            for (t, _id), p in list(self._index(self.dir).items()):
                if t != "ANCS":
                    continue
                try:
                    trips = retro_skin.ancs_characters(self.src.get(p), self.has)
                except Exception:  # noqa: BLE001 - a bad ANCS just means no skeleton
                    continue
                for cmdl_id, cskr, cinf in trips:
                    out.setdefault(cmdl_id, (cskr, cinf))
            return out

        return _cached(self.src, f"ancs:{self.dir}", build)


def _skin(scene: Scene, model: retro_cmdl.Model, sib: _Siblings, cmdl_id: int | None):
    """Attach the CINF skeleton and CSKR weights an ANCS character pairs with this CMDL."""
    if cmdl_id is None or not (model.flags & retro_cmdl.FLAG_SKINNED):
        return None
    ref = sib.characters().get(cmdl_id)
    if ref is None:
        return None
    cskr_raw, cinf_raw = sib.get("CSKR", ref[0]), sib.get("CINF", ref[1])
    if not cskr_raw or not cinf_raw:
        return None
    try:
        skel = retro_skin.parse_cinf(cinf_raw)
        groups = retro_skin.parse_cskr(cskr_raw)
    except (retro_skin.SkinError, struct.error, ValueError) as e:
        scene.warnings.append(f"skin: {e}")
        return None
    by_id = {b.id: i for i, b in enumerate(skel.bones)}
    parents = [by_id.get(b.parent) for b in skel.bones]
    parents = [None if p == i else p for i, p in enumerate(parents)]
    # glTF export wants parents before children: emit joints in tree order
    children: dict[int | None, list[int]] = {}
    for i, p in enumerate(parents):
        children.setdefault(p, []).append(i)
    order: list[int] = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        i = stack.pop()
        order.append(i)
        stack.extend(reversed(children.get(i, [])))
    order += [i for i in range(len(skel.bones)) if i not in set(order)]  # cycles, if any
    remap = np.zeros(len(skel.bones), np.uint16)
    pos = np.array([b.position for b in skel.bones], np.float32)
    for new_i, i in enumerate(order):
        remap[i] = new_i
        b = skel.bones[i]
        p = parents[i]
        parent = int(remap[p]) if p is not None and p in order[:new_i] else None
        local = pos[i] - (pos[p] if parent is not None else 0.0)
        scene.joints.append(
            Joint(
                name=skel.names.get(b.id, f"bone{b.id}"),
                parent=parent,
                translation=(float(local[0]), float(local[2]), float(-local[1])),
                rotation=(0.0, 0.0, 0.0, 1.0),
                scale=(1.0, 1.0, 1.0),
            )
        )
    scene.extras["retro_cskr"] = f"0x{ref[0]:08X}"
    scene.extras["retro_cinf"] = f"0x{ref[1]:08X}"
    joints, weights = retro_skin.skin_arrays(groups, skel, len(model.positions))
    return remap[joints], weights


def _extract_cmdl(data: bytes, path: str, src: Any, name: str) -> list[Scene]:
    sib = _Siblings(src, path)
    model = retro_cmdl.parse(data)
    scene = Scene(name=name)
    parsed = retro_pak.parse_name(path.rsplit("/", 1)[-1])
    skin = _skin(scene, model, sib, parsed[1] if parsed else None)
    retro_scene.build_scene(model, name, sib.texture, scene=scene, skin=skin)
    scene.extras["retro_version"] = model.version
    scene.extras["retro_flags"] = model.flags
    if not scene.primitives:
        return []
    return [scene]


def _extract_mrea(data: bytes, path: str, src: Any, name: str) -> list[Scene]:
    sib = _Siblings(src, path)
    area = retro_mrea.parse(data)
    scene = Scene(name=name)
    scene.warnings += area.warnings
    slots: dict[int, int] = {}
    for wm in area.models:
        retro_scene.build_scene(
            wm.model, name, sib.texture, scene=scene, transform=wm.transform, slots=slots
        )
    scene.extras["retro_version"] = area.version
    scene.extras["retro_world_models"] = len(area.models)
    if not scene.primitives:
        return []
    return [scene]


def extract(data: bytes, path: str, src: Any) -> list[Scene]:
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    (magic,) = struct.unpack_from(">I", data, 0)
    if magic == retro_mrea.MAGIC:
        return _extract_mrea(data, path, src, name)
    return _extract_cmdl(data, path, src, name)
