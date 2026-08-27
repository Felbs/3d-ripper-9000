"""Ubisoft Jade engine (Beyond Good & Evil GGEE41, Prince of Persia: The Sands of
Time GPTE41): the .bf big file is the container, every level is a binarized
ROOT/Bin/ff0xxxxx.bin pack (LZO) with its geometry (and, for PoP, its textures);
BG&E keeps textures in a sibling ff8xxxxx.bin pack.

What comes out:
  * one Scene per GEO geometric object in a map pack - positions, UVs, vertex
    colours / normals where present, one material slot per element (untextured:
    linking a GEO to its material and texture goes through the game object graph,
    which needs the full loader);
  * one textures-only Scene per pack holding every texture that decodes.

See gcrip.formats.jade for the structures and their sources.
"""

from __future__ import annotations

import hashlib
import re
import struct

import numpy as np

from gcrip.formats import j3d, jade, jade_bf, jade_lzo
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "jade"

_BIN_RE = re.compile(r"(?:^|/)ROOT/Bin/[^/]*?([0-9a-fA-F]{8})\.bin$")


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


def _pack_bytes(data: bytes, path: str, src) -> bytes:
    """The manifest walker records members of plugin containers without their
    offset, so the bytes handed to us may be the head of the .bf itself: in
    that case locate the pack through the big file's table."""
    if jade_lzo.is_jade_blocks(data) and not jade_bf.is_bf(data):
        return data
    by_path = getattr(src, "by_path", {}) or {}
    entry = by_path.get(path)
    container = getattr(entry, "container", None)
    if container is None:
        cut = path.lower().rfind(".bf/")
        if cut < 0:
            raise jade.JadeError("pack is not inside a .bf big file")
        container = path[: cut + 3]
    bf = _container_bytes(src, container)
    inner = path[len(container) + 1 :] if path.startswith(container) else path
    for e in jade_bf.parse(bf):
        if e.path == inner or e.path.endswith("/" + inner) or inner.endswith(e.path):
            return bf[e.offset : e.offset + e.size]
    raise jade.JadeError(f"{inner} not found in {container}")


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


def geo_to_scene(g: jade.Geo, name: str) -> Scene:
    scene = Scene(name=name)
    scene.warnings += g.warnings
    verts = _to_yup(g.vertices.astype(np.float32))
    nrm = _to_yup(g.normals.astype(np.float32)) if g.normals is not None else None
    colors = None
    if g.colors is not None and len(g.colors) == len(verts):
        colors = g.colors.astype(np.float32) / 255.0
        colors[:, 3] = np.minimum(colors[:, 3] * 2.0, 1.0)  # Jade alpha is 0..128
    uvs = g.uvs.astype(np.float32)
    mat_index: dict[int, int] = {}
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
        mi = mat_index.get(el.material)
        if mi is None:
            mi = len(scene.materials)
            mat_index[el.material] = mi
            scene.materials.append(MaterialDef(name=f"mat{el.material}", texture=None))
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=pos.astype(np.float32),
                indices=inv.reshape(-1).astype(np.uint32),
                normals=normals,
                uvs=uv,
                colors=col,
            )
        )
    return scene


def _textures_scene(name: str, textures: dict[str, np.ndarray]) -> Scene:
    """No geometry; one material per texture so the glTF writer emits the PNGs."""
    scene = Scene(name=name)
    scene.textures = textures
    scene.materials = [MaterialDef(name=k, texture=k) for k in textures]
    scene.extras = {"textures_only": True}
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    key = _bin_key(path) or 0
    stem = f"{key:08x}"
    payload = _pack_bytes(data, path, src)
    dec = jade_lzo.decompress_blocks(payload)
    scenes: list[Scene] = []
    textures: dict[str, np.ndarray] = {}
    if jade.is_montreal(dec):
        entries = jade.walk_montreal(dec)
        textures = jade.textures_montreal(entries)
        for e in entries:
            if len(e.data) < 24 or struct.unpack_from("<I", e.data, 0)[0] != jade.GRO_GEO:
                continue
            try:
                g = jade.parse_geo(e.data, montreal=True)
            except (jade.JadeError, ValueError):
                continue
            if g.triangle_count == 0:
                continue
            scenes.append(geo_to_scene(g, f"{e.key:08x}"))
    else:
        entries = jade.walk_montpellier(dec)
        textures = jade.textures_montpellier(entries)
        if jade_bf.key_type(key) == "map":
            for off, g in jade.find_geos_montpellier(dec):
                if g.triangle_count == 0:
                    continue
                scenes.append(geo_to_scene(g, f"geo_{off:06x}"))
    if textures:
        # identical images under different keys are common (shared banks)
        seen: dict[str, str] = {}
        uniq: dict[str, np.ndarray] = {}
        for k, img in textures.items():
            h = hashlib.sha1(img.tobytes()).hexdigest()
            if h in seen:
                continue
            seen[h] = k
            uniq[k] = img
        scenes.append(_textures_scene(f"{stem}_textures", uniq))
    return scenes
