"""Edge of Reality models - ``MODL`` members (``Models/<hash>.bin`` out of ``models.arc``), the
older discs' bare ``models.arc`` members and dataset entries (``.eorm``) - one Scene a model,
textures bound through the disc's ``Shaders`` and ``Textures`` categories by name hash."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import edge_model
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "edge_model"


def detect(path: str, head: bytes, size: int) -> bool:
    lower = path.lower()
    if lower.endswith(".eorm"):
        return size > 64
    return (
        lower.endswith(".bin")
        and size > 64
        and (edge_model.is_model(head[:8]) or edge_model.is_old_model(head))
    )


def _parse(data: bytes, path: str) -> edge_model.Model:
    if path.lower().endswith(".eorm") or not edge_model.is_model(data[:8]):
        return edge_model.parse_entry_model(data)
    return edge_model.parse_model(data)


class _Resources:
    """hash -> shader / texture member paths across the source, filled lazily."""

    def __init__(self, src) -> None:
        self.src = src
        self.shaders: dict[int, str] | None = None
        self.textures: dict[int, str] = {}
        self.cache: dict[int, edge_model.Texture | None] = {}
        self.shader_cache: dict[int, list[int]] = {}

    def _index(self) -> None:
        if self.shaders is not None:
            return
        self.shaders = {}
        for p in self.src.by_path:
            parts = p.rsplit("/", 2)
            if len(parts) < 3 or parts[1] not in ("Shaders", "Textures"):
                continue
            try:
                h = int(parts[2].split(".")[0].split("_")[0], 16)
            except ValueError:
                continue
            if parts[1] == "Shaders":
                self.shaders.setdefault(h, p)
            elif parts[1] == "Textures":
                self.textures.setdefault(h, p)

    def texture_of(self, shader: int) -> edge_model.Texture | None:
        self._index()
        assert self.shaders is not None
        if shader not in self.shader_cache:
            refs: list[int] = []
            path = self.shaders.get(shader)
            if path is not None:
                try:
                    refs = edge_model.shader_textures(self.src.get(path))
                except Exception:  # noqa: BLE001 - a bad shader leaves the strip untextured
                    refs = []
            # a model whose shader is missing usually has a texture under its own hash
            self.shader_cache[shader] = refs or ([shader] if shader in self.textures else [])
        for ref in self.shader_cache[shader]:
            tex = self.texture(ref)
            if tex is not None:
                return tex
        return None

    def texture(self, ref: int) -> edge_model.Texture | None:
        if ref in self.cache:
            return self.cache[ref]
        out = None
        path = self.textures.get(ref)
        if path is not None:
            try:
                out = edge_model.any_texture(self.src.get(path))
            except Exception:  # noqa: BLE001 - one bad texture must not stop the model
                out = None
        if len(self.cache) > 256:
            self.cache.clear()
        self.cache[ref] = out
        return out


_cache: dict[int, _Resources] = {}


def _resources(src) -> _Resources | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    t = _cache.get(key)
    if t is None or t.src is not src:
        _cache.clear()
        t = _cache[key] = _Resources(src)
    return t


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = _parse(data, path)
    stem = posixpath.basename(path).split(".")[0]
    scene = Scene(name=model.name or stem)
    scene.warnings += model.warnings
    res = _resources(src)
    materials: dict[int, int] = {}
    for strip in model.strips:
        if strip.shader not in materials:
            tex_key = None
            tex = res.texture_of(strip.shader) if res is not None else None
            if tex is not None:
                tex_key = tex.name or f"{strip.shader:08x}"
                scene.textures.setdefault(tex_key, tex.rgba)
            materials[strip.shader] = len(scene.materials)
            scene.materials.append(
                MaterialDef(name=tex_key or f"shader_{strip.shader:08x}", texture=tex_key)
            )
        scene.primitives.append(
            Primitive(
                material=materials[strip.shader],
                positions=np.ascontiguousarray(strip.positions, dtype=np.float32),
                indices=strip.indices,
                normals=None
                if strip.normals is None
                else np.ascontiguousarray(strip.normals, dtype=np.float32),
                uvs=None
                if strip.uvs is None
                else np.ascontiguousarray(strip.uvs, dtype=np.float32),
                colors=None
                if strip.colors is None
                else np.ascontiguousarray(strip.colors, dtype=np.uint8),
            )
        )
    if not scene.primitives:
        return []
    return [scene]
