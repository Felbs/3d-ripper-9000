"""Blitz Games actors (``.tba`` members of ``.gcp`` packs) - one Scene an actor, textures
bound by CRC through every pack the source of the rip can reach."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import blitz_actor
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "blitz_actor"
EXT = ".tba"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(EXT) and size >= blitz_actor.ACTOR and len(head) > 6 and head[6] == 1


def _crc_of(path: str) -> int | None:
    parts = posixpath.basename(path).split(".")
    if len(parts) >= 3:
        try:
            return int(parts[-2], 16)
        except ValueError:
            return None
    return None


class _Textures:
    """CRC -> decoded texture across the packs in the source, filled lazily."""

    def __init__(self, src) -> None:
        self.src = src
        self.by_crc: dict[int, str] | None = None
        self.cache: dict[int, tuple[str, np.ndarray] | None] = {}

    def _index(self) -> dict[int, str]:
        if self.by_crc is None:
            self.by_crc = {}
            for p in self.src.by_path:
                if p.lower().endswith(".tbt"):
                    crc = _crc_of(p)
                    if crc is not None:
                        self.by_crc.setdefault(crc, p)
        return self.by_crc

    def get(self, crc: int) -> tuple[str, np.ndarray] | None:
        if crc in self.cache:
            return self.cache[crc]
        out = None
        path = self._index().get(crc)
        if path is not None:
            try:
                blob = self.src.get(path)
                out = (posixpath.basename(path).split(".")[0], blitz_actor.texture(blob))
            except Exception:  # noqa: BLE001 - one bad texture must not stop the actor
                out = None
        if len(self.cache) > 512:
            self.cache.clear()
        self.cache[crc] = out
        return out


_cache: dict[int, _Textures] = {}


def _textures(src) -> _Textures | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    t = _cache.get(key)
    if t is None or t.src is not src:
        _cache.clear()
        t = _cache[key] = _Textures(src)
    return t


def extract(data: bytes, path: str, src) -> list[Scene]:
    textures_early = _textures(src)
    try:
        actor = blitz_actor.parse(data)
        if not actor.meshes:
            raise blitz_actor.ActorError("no meshes in the Bratz layout")
    except blitz_actor.ActorError:
        # the 2002 generation (Taz: Wanted) - same engine, older resource layout
        from gcrip.formats import taz_actor

        crcs = set(textures_early._index()) if textures_early is not None else None
        actor = taz_actor.parse(data, crcs)
    stem = posixpath.basename(path).split(".")[0]
    scene = Scene(name=stem)
    scene.warnings += actor.warnings
    textures = textures_early
    materials: dict[tuple[int, int], int] = {}
    for md in actor.meshes:
        key = (md.texture, md.texture2)
        if key not in materials:
            tex_name = None
            if textures is not None and md.texture:
                found = textures.get(md.texture)
                if found is not None:
                    tex_name, rgba = found
                    scene.textures[tex_name] = rgba
            materials[key] = len(scene.materials)
            scene.materials.append(MaterialDef(name=tex_name or f"material_{len(scene.materials)}", texture=tex_name))
        scene.primitives.append(
            Primitive(
                material=materials[key],
                positions=np.ascontiguousarray(md.positions, dtype=np.float32),
                indices=md.indices,
                normals=None if md.normals is None else np.ascontiguousarray(md.normals, dtype=np.float32),
                uvs=None if md.uvs is None else np.ascontiguousarray(md.uvs, dtype=np.float32),
                colors=None if md.colors is None else np.ascontiguousarray(md.colors, dtype=np.uint8),
            )
        )
    if not scene.primitives:
        raise blitz_actor.ActorError(f"{path}: no triangles")
    if len(actor.nodes) > 1:
        for n in actor.nodes:
            scale = tuple(n.scale) if any(n.scale) else (1.0, 1.0, 1.0)
            scene.joints.append(
                Joint(name=n.name, parent=n.parent if n.parent >= 0 else None, translation=tuple(n.position), rotation=tuple(n.rotation), scale=scale)
            )
    return [scene]
