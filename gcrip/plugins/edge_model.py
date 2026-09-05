"""Edge of Reality models - ``MODL`` members (``Models/<hash>.bin`` out of ``models.arc``), the
older discs' bare ``models.arc`` members and dataset entries (``.eorm``) - one Scene a model,
textures bound through the disc's ``Shaders`` and ``Textures`` categories by name hash.

The hash is ``crc32`` of the upper-cased name (``l_hqcf_spanielcut_leanfighter`` ->
``00048712``), which is also how a face template (``af_ft_chin_strong``, ``d_fmt_Growl``: a
model of per-vertex position deltas, mostly zero) finds the base face it deforms
(``af_ft_base_lod``, ``d_ft_base``) and goes out as the deformed face instead of as a
collapsed cloud of deltas."""

from __future__ import annotations

import posixpath
import re
import zlib

import numpy as np

from gcrip.formats import edge_model
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "edge_model"

MORPH_NAME = re.compile(r"^(?P<prefix>[a-z]+)_(?:ft|fmt)_(?P<feature>.+?)(?P<lod>_lod)?$")
MORPH_BASES = ("base", "bases2c", "base_s2c")  # ``af_ft_base`` is not shipped, its s2c is


def name_hash(name: str) -> int:
    return zlib.crc32(name.upper().encode("latin-1")) & 0xFFFFFFFF


def morph_base_names(name: str) -> list[str]:
    """Base-face names a face template of this name may deform, in the order to try."""
    m = MORPH_NAME.match(name)
    if m is None or m["feature"].startswith("base"):
        return []
    lod = m["lod"] or ""
    return [f"{m['prefix']}_ft_{base}{lod}" for base in MORPH_BASES]


def detect(path: str, head: bytes, size: int) -> bool:
    lower = path.lower()
    if lower.endswith(".eorm"):
        return size > 64
    if not lower.endswith(".bin") or size <= 64:
        return False
    # the bare older-disc member has no tag, so it is only believed under a Models folder
    return edge_model.is_model(head[:8]) or ("/models/" in lower and edge_model.is_old_model(head))


def _parse(data: bytes, path: str, keep_all: bool = False) -> edge_model.Model:
    if path.lower().endswith(".eorm") or not edge_model.is_model(data[:8]):
        return edge_model.parse_entry_model(data)
    h = edge_model.header(data)
    assert h is not None
    return edge_model.parse_payload(h.payload, h.version, h.name, keep_all=keep_all)


class _Resources:
    """hash -> shader / texture member paths across the source, filled lazily."""

    def __init__(self, src) -> None:
        self.src = src
        self.shaders: dict[int, str] | None = None
        self.textures: dict[int, str] = {}
        self.cache: dict[int, edge_model.Texture | None] = {}
        self.shader_cache: dict[int, list[int]] = {}
        self.bases: dict[str, edge_model.Model | None] = {}

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
        if out is not None and not out.rgba[..., 3].any():
            # ``af_hh_dummy``, the 8x8 fully transparent stand-in the runtime composites
            # over: binding it would make the model invisible
            out = None
        if len(self.cache) > 256:
            self.cache.clear()
        self.cache[ref] = out
        return out

    def base_model(self, folder: str, name: str) -> edge_model.Model | None:
        """The sibling ``MODL`` member of this name (by its hash), parsed, or None."""
        key = f"{folder}/{name_hash(name):08x}.bin"
        if key not in self.bases:
            model = None
            if key in self.src.by_path:
                try:
                    data = self.src.get(key)
                    model = edge_model.parse_model(data)
                except Exception:  # noqa: BLE001 - an unreadable base leaves the morph as is
                    model = None
            self.bases[key] = model
        return self.bases[key]


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


def _morphed(data: bytes, path: str, model: edge_model.Model, res: _Resources | None):
    """The base face deformed by this morph target, or None when this is not one."""
    if res is None or not edge_model.is_model(data[:8]):
        return None
    bases = morph_base_names(model.name)
    if not bases:
        return None
    deltas = _parse(data, path, keep_all=True)
    if not edge_model.is_morph_target(deltas):
        return None
    folder = posixpath.dirname(path)
    for name in bases:
        base = res.base_model(folder, name)
        if base is None:
            continue
        out = edge_model.apply_morph(base, deltas)
        if out is not None:
            return out
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = _parse(data, path)
    res = _resources(src)
    model = _morphed(data, path, model, res) or model
    stem = posixpath.basename(path).split(".")[0]
    scene = Scene(name=model.name or stem)
    scene.warnings += model.warnings
    materials: dict[int, int] = {}
    for strip in model.strips:
        if not len(strip.indices):
            continue
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
