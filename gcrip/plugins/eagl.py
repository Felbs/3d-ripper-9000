"""EA Canada EAGL models (FIFA, NBA Live, NHL, MVP, Def Jam, Fight Night, SSX, ...): the
``.ord`` + ``.orp`` ELF pairs inside EA BIG/VIV archives (gcrip.formats.eagl).  One Scene
per ``__Model`` (LOD / variation); textures are the sibling ``.gsh`` shape files named by
the packet's SHAPENAME reference when they can be found."""

from __future__ import annotations

import contextlib
import posixpath

import numpy as np

from gcrip.formats import ea_shape, eagl
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "eagl"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".ord") and eagl.is_ord(head)


_BASENAME_ATTR = "_eagl_basename_index"


def _basename_index(src) -> dict[str, list[str]]:
    """lower-case file name -> every manifest path with that name (built once per source)."""
    index = getattr(src, _BASENAME_ATTR, None)
    if index is not None:
        return index
    index = {}
    for p in getattr(src, "by_path", {}) or {}:
        index.setdefault(p.lower().rsplit("/", 1)[-1], []).append(p)
    with contextlib.suppress(Exception):
        setattr(src, _BASENAME_ATTR, index)
    return index


def _sibling(src, path: str, name: str) -> bytes | None:
    """The paired half of an EAGL object, which is not always beside its partner.

    The obvious lookup is the same folder, and that is right most of the time.  It is wrong on
    NBA Live, where the pair is split across **two containers in the same directory**: the
    `.ord` sits in `anim/body/xanims.viv/` and its `.orl` in `anim/body/xsyms.viv/`.  A
    same-folder lookup can never find that, and it cost 32 models across 8 discs with the
    misleading error "section table outside the file (missing .orp?)" - the half was on the
    disc all along.
    """
    folder = posixpath.dirname(path)
    with contextlib.suppress(Exception):
        return src.get(posixpath.join(folder, name))
    return _sibling_across_containers(src, path, name)


def _sibling_across_containers(src, path: str, name: str) -> bytes | None:
    folder = posixpath.dirname(path)
    parent = posixpath.dirname(folder)  # the real directory both containers live in
    for candidate in _basename_index(src).get(name.lower(), ()):
        holder = posixpath.dirname(candidate)
        if holder == folder or posixpath.dirname(holder) == parent:
            with contextlib.suppress(Exception):
                return src.get(candidate)
    return None


_INDEX_ATTR = "_eagl_shape_index"


def _shape_index(src, path: str) -> dict[str, str]:
    """shape name -> .gsh manifest path, for every shape file in the same folder (header
    reads only; cached on the source per folder)."""
    cache = getattr(src, _INDEX_ATTR, None)
    if cache is None:
        cache = {}
        with contextlib.suppress(Exception):
            setattr(src, _INDEX_ATTR, cache)
    folder = posixpath.dirname(path)
    if folder in cache:
        return cache[folder]
    index: dict[str, str] = {}
    by_path = getattr(src, "by_path", {}) or {}
    for p in by_path:
        if posixpath.dirname(p) == folder and p.lower().endswith(".gsh"):
            try:
                for name in ea_shape.shape_names(src.get(p)[:0x4010]):
                    index.setdefault(name, p)
            except Exception:  # noqa: BLE001
                continue
    cache[folder] = index
    return index


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = posixpath.basename(path)[:-4]
    # .orp on the FIFA titles, .orl on MVP Baseball, NHL, FIFA Street, Def Jam and Fight Night;
    # a disc carries one or the other, never both
    orp = next(
        (blob for ext in (".orp", ".orl", ".ORP", ".ORL") if (blob := _sibling(src, path, stem + ext))),
        None,
    )
    obj = eagl.parse(eagl.join(data, orp))
    lookup = _shape_index(src, path)
    decoded: dict[str, np.ndarray | None] = {}
    scenes = []
    for model in obj.models:
        scene = Scene(name=model.name)
        scene.warnings += obj.warnings
        scene.joints = [
            Joint(b.name, b.parent, tuple(b.translation), tuple(b.rotation), tuple(b.scale))
            for b in obj.skeleton
        ]
        for pk in model.packets:
            tex_key = None
            for n in pk.textures:
                if n not in decoded:
                    decoded[n] = None
                    gsh = lookup.get(n)
                    if gsh:
                        try:
                            for s in ea_shape.parse(src.get(gsh)):
                                if s.name == n and s.rgba is not None:
                                    decoded[n] = s.rgba
                                    break
                        except Exception as e:  # noqa: BLE001
                            scene.warnings.append(f"{gsh}: {e}")
                if decoded.get(n) is not None:
                    tex_key = n
                    scene.textures.setdefault(n, decoded[n])
                    break
            mat = MaterialDef(
                name=f"{pk.shader}#{len(scene.materials)}",
                texture=tex_key,
                double_sided=True,
            )
            scene.materials.append(mat)
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=pk.positions,
                    indices=pk.indices,
                    normals=pk.normals,
                    uvs=pk.uvs,
                    joints=pk.joints if scene.joints else None,
                    weights=pk.weights if scene.joints else None,
                )
            )
        if scene.primitives:
            scene.extras = {
                "format": "eagl",
                "bones": len(obj.bones),
                "packets": len(model.packets),
                "variations": model.variations,
                "skinned": sum(1 for pk in model.packets if pk.joints is not None),
                "variations_are": "kit toggle sets (enable_* flags), not LODs",
            }
            scenes.append(scene)
    return scenes
