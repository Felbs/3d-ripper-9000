"""Next Level Games ``.glg`` models (Super Mario Strikers) - one Scene a file, every model
placed by its packets' matrices, textures from the ``.glt`` bundle beside the file (then
any bundle on the disc) by name hash."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import nlg_gl
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "nlg_glg"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".glg") and nlg_gl.is_glg(head, size)


class _Bundles:
    """Texture hash -> (bundle path, offset, size) across the source, the model's own
    folder first; decoded images cached."""

    def __init__(self, src) -> None:
        self.src = src
        self.paths = [p for p in src.by_path if p.lower().endswith(".glt")]
        self.entries: dict[str, dict[int, tuple[int, int]]] = {}
        self.cache: dict[tuple[str, int], np.ndarray | None] = {}

    def _entries(self, path: str) -> dict[int, tuple[int, int]]:
        if path not in self.entries:
            try:
                self.entries[path] = nlg_gl.glt_entries(self.src.get(path))
            except Exception:  # noqa: BLE001 - one bad bundle must not stop the lookup
                self.entries[path] = {}
        return self.entries[path]

    def image(self, h: int, folder: str) -> np.ndarray | None:
        order = [p for p in self.paths if posixpath.dirname(p) == folder]
        order += [p for p in self.paths if posixpath.dirname(p) != folder]
        for p in order:
            e = self._entries(p).get(h)
            if e is None:
                continue
            key = (p, h)
            if key not in self.cache:
                try:
                    img = nlg_gl.decode_glt_texture(self.src.get(p), *e)
                except Exception:  # noqa: BLE001 - a bad texture leaves the material bare
                    img = None
                if len(self.cache) > 256:
                    self.cache.clear()
                self.cache[key] = img
            if self.cache[key] is not None:
                return self.cache[key]
        return None


_cache: dict[int, _Bundles] = {}


def _bundles(src) -> _Bundles | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    t = _cache.get(key)
    if t is None or t.src is not src:
        _cache.clear()
        t = _cache[key] = _Bundles(src)
    return t


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    folder = posixpath.dirname(path)
    scene = Scene(name=stem)
    models = nlg_gl.parse_glg(data, scene.warnings)
    bundles = _bundles(src)
    materials: dict[int, int] = {}
    missing: set[int] = set()
    for model in models:
        for pk in model.packets:
            if pk.texture not in materials:
                key = f"{pk.texture:08x}"
                img = bundles.image(pk.texture, folder) if bundles is not None else None
                if img is not None:
                    scene.textures[key] = img
                elif pk.texture:
                    missing.add(pk.texture)
                materials[pk.texture] = len(scene.materials)
                scene.materials.append(
                    MaterialDef(name=key, texture=key if img is not None else None)
                )
            scene.primitives.append(
                Primitive(
                    material=materials[pk.texture],
                    positions=np.ascontiguousarray(pk.positions, dtype=np.float32),
                    indices=pk.triangles.reshape(-1).astype(np.uint32),
                    normals=None
                    if pk.normals is None
                    else np.ascontiguousarray(pk.normals, dtype=np.float32),
                    uvs=None if pk.uvs is None else np.ascontiguousarray(pk.uvs, dtype=np.float32),
                    colors=None
                    if pk.colors is None
                    else np.ascontiguousarray(pk.colors, dtype=np.uint8),
                )
            )
    if missing:
        scene.warnings.append(f"{len(missing)} textures not found")
    scene.extras["models"] = [f"{m.id:08x}" for m in models]
    return [scene] if scene.primitives else []
