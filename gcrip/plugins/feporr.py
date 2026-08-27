"""Fire Emblem: Path of Radiance (GFEE01) -> Scene.

Container side: ``.cmp``/``.cms`` are LZ10 streams, ``.pak`` (and most decompressed ``.cmp``)
are ``pack`` archives (``gcrip.formats.feporr_pack``).  Expanding them hands the manifest the
inner ``.tpl`` textures (decoded by the core) and the ``.gs`` geometry this plugin turns into
Scenes (``gcrip.formats.feporr_gs``).  Textures come from the ``.tpl`` next to the ``.gs``
(same pack: ``<stem>.tpl`` or ``texpack.tpl``; characters keep ``<unit>.tpl`` beside the pak).
"""

from __future__ import annotations

import numpy as np

from gcrip.formats import feporr_gs as gs
from gcrip.formats import feporr_pack as fp
from gcrip.formats import gx_texture, tpl
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "feporr"

_CONTAINER_EXT = (".cmp", ".cms", ".pak")


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


# --- containers ---------------------------------------------------------------------------


def is_container(name: str, head: bytes) -> bool:
    low = name.lower()
    if not low.endswith(_CONTAINER_EXT):
        return False
    return fp.is_pack(head) or fp.is_lz10(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if fp.is_lz10(data) and not fp.is_pack(data):
        data = fp.lz10_decompress(data)
    if fp.is_pack(data):
        return fp.pack_members(data)
    # a bare LZ10 payload (.cms portraits are single TPLs)
    if data[:4] == tpl.MAGIC:
        return [("image.tpl", data)]
    return [("data.bin", data)]


# --- models -------------------------------------------------------------------------------


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gs") and gs.looks_like_gs(head, size)


def _find_tpl(src, path: str) -> bytes | None:
    if src is None:
        return None
    p = path.replace("\\", "/")
    folder = p.rsplit("/", 1)[0] if "/" in p else ""
    stem = _base(p).rsplit(".", 1)[0]
    by_path = getattr(src, "by_path", None) or {}
    candidates = [f"{folder}/{stem}.tpl", f"{folder}/texpack.tpl"]
    parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
    unit = _base(parent) if parent else ""
    if unit:
        candidates.append(f"{parent}/{unit}.tpl")
    # any other TPL in the same pack, then in the pack's folder
    for scope in (folder + "/", parent + "/" if parent else None):
        if scope is None:
            continue
        for k in sorted(by_path):
            inner = k[len(scope) :]
            is_tpl = k.startswith(scope) and "/" not in inner and inner.lower().endswith(".tpl")
            if is_tpl and k not in candidates:
                candidates.append(k)
    for c in candidates:
        if by_path and c not in by_path:
            continue
        try:
            blob = src.get(c)
        except Exception:  # noqa: BLE001
            continue
        if blob[:4] == tpl.MAGIC:
            return blob
    return None


def _materials(model: gs.Model, images: list, double: set[int]) -> list[MaterialDef]:
    out = []
    for i, m in enumerate(model.materials):
        tex = None
        clamp_u = clamp_v = mirror_u = mirror_v = False
        alpha = False
        if m.sampler is not None and m.sampler.image < len(images):
            tex = f"image{m.sampler.image}"
            img = images[m.sampler.image]
            alpha = gx_texture.has_alpha(img.fmt, img.palette_fmt)
            clamp_u, clamp_v = m.sampler.wrap_s == 0, m.sampler.wrap_t == 0
            mirror_u, mirror_v = m.sampler.wrap_s == 2, m.sampler.wrap_t == 2
        r, g, b, a = m.diffuse
        out.append(
            MaterialDef(
                name=m.name or f"mat{i}",
                texture=tex,
                base_color=(r / 255, g / 255, b / 255, 1.0),
                alpha_blend=alpha and bool(m.flags & 0x10000),
                double_sided=i in double,
                clamp_u=clamp_u,
                clamp_v=clamp_v,
                mirror_u=mirror_u,
                mirror_v=mirror_v,
            )
        )
    return out


def build_scene(model: gs.Model, name: str, tex_blob: bytes | None) -> Scene:
    scene = Scene(name=name, warnings=list(model.warnings))
    images = []
    if tex_blob:
        try:
            images = tpl.parse(tex_blob)
        except Exception as ex:  # noqa: BLE001
            scene.warnings.append(f"texture TPL: {ex}")
    double = {r.material for r in model.records if r.flags & 0x04}
    scene.materials = _materials(model, images, double)
    used = {m.texture for m in scene.materials if m.texture}
    for i, img in enumerate(images):
        key = f"image{i}"
        if key in used:
            try:
                scene.textures[key] = img.decode()
            except Exception as ex:  # noqa: BLE001
                scene.warnings.append(f"texture {i}: {ex}")
    for rec in model.records:
        uvs = rec.uvs
        mat = model.materials[rec.material] if rec.material < len(model.materials) else None
        if uvs is not None and mat is not None and mat.sampler is not None:
            s = mat.sampler
            if s.scale_s != 1.0 or s.scale_t != 1.0:
                uvs = uvs * np.array([s.scale_s, s.scale_t], np.float32)
        scene.primitives.append(
            Primitive(
                material=rec.material,
                positions=rec.positions.astype(np.float32),
                indices=rec.triangles.reshape(-1).astype(np.uint32),
                normals=rec.normals,
                uvs=uvs,
                colors=rec.colors,
            )
        )
    scene.extras = {
        "format": "feporr_gs",
        "model": model.name,
        "shapes": [s.name for s in model.shapes],
        "skinned_records": model.skinned,
    }
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = gs.parse(data)
    stem = _base(path).rsplit(".", 1)[0]
    scene = build_scene(model, stem, _find_tpl(src, path))
    if not scene.primitives:
        return []
    return [scene]
