"""``res\\n`` resource files as a container (gcrip.formats.res): Digimon Rumble Arena 2,
Lemony Snicket's A Series of Unfortunate Events and Samurai Jack: The Shadow of Aku all ship
their levels, menus and audio in this middleware format.  Splitting a file into its tagged
sections gives the structure scanner small, labelled blobs (``surf``, ``node``, ``sdta`` hold
the geometry; ``wave`` / ``musc`` are audio)."""

from __future__ import annotations

import posixpath
import re

import numpy as np

from gcrip.formats import res, res_bmsh, res_rdms, res_surf
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "res"

# characters are modelled Z-up (the Scotsman's bind root sits at z = 1.13); glTF is Y-up
UPRIGHT = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], np.float32)


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".res") and res.is_res(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return res.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    # a member handed back by expand(); the real check needs the whole section, which
    # extract() gets, so this only screens on the name expand() gave it
    base = posixpath.basename(path)
    return "_surf_" in base or "_rdms_" in base or "_bmsh_" in base


_TEXTURE_TAG = re.compile(r"_t(\d{3})$")
_CHARACTER_TAG = re.compile(r"_t((?:\d{3}|x)(?:-(?:\d{3}|x))*)$")


def _surf(src, path: str, index: int) -> bytes | None:
    """The sibling member ``NNN_surf_*.bin`` of the same container."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    prefix = f"{folder}/{index:03d}_surf_"
    for p in src.by_path:
        if p.startswith(prefix):
            try:
                return src.get(p)
            except Exception:  # noqa: BLE001 - the mesh is still worth having untextured
                return None
    return None


def _bind(scene: Scene, src, path: str, index: int | None) -> int:
    """Append a material sampling surf ``index`` (decoded once a scene) - its index."""
    texture = None
    if index is not None:
        texture = f"surf_{index:03d}"
        if texture not in scene.textures:
            blob = _surf(src, path, index)
            rgba = res_surf.decode(blob) if blob else None
            if rgba is None:
                texture = None
            else:
                scene.textures[texture] = rgba
    name = texture or f"material_{len(scene.materials)}"
    scene.materials.append(MaterialDef(name=name, texture=texture))
    return len(scene.materials) - 1


def _character(data: bytes, name: str, path: str, src) -> list[Scene]:
    mdl = res_bmsh.model(data)
    if mdl is None or not mdl.batches:
        return []
    tags: list[str] = []
    m = _CHARACTER_TAG.search(name)
    if m:
        tags = m.group(1).split("-")
    scene = Scene(name=name)
    scene.warnings.extend(mdl.warnings)
    for k, batch in enumerate(mdl.batches):
        surf = int(tags[k]) if k < len(tags) and tags[k] != "x" else None
        material = _bind(scene, src, path, surf)
        scene.primitives.append(
            Primitive(
                material=material,
                positions=np.ascontiguousarray(batch.positions @ UPRIGHT),
                indices=batch.indices,
                normals=np.ascontiguousarray(batch.normals @ UPRIGHT),
                uvs=batch.uvs,
            )
        )
    scene.extras = {"format": "res_bmsh", "batches": len(mdl.batches), "upright": "z-up to y-up"}
    return [scene]


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    if "_bmsh_" in name:
        return _character(data, name, path, src)
    if "_rdms_" in name:
        mesh = res_rdms.mesh(data)
        if mesh is None:
            return []
        scene = Scene(name=name)
        texture = None
        m = _TEXTURE_TAG.search(name)
        if m:
            # expand() named the surf the mesh's shader samples (formats.res.shader_textures)
            blob = _surf(src, path, int(m.group(1)))
            rgba = res_surf.decode(blob) if blob else None
            if rgba is not None:
                texture = f"surf_{int(m.group(1)):03d}"
                scene.textures[texture] = rgba
        # A real material, not the -1 "no material" sentinel with an empty list: the thumbnail
        # pass indexes material_colors by it, and `[][-1]` is an IndexError that failed 62,640
        # meshes across the three discs - every mesh that had triangles to draw.
        scene.materials.append(MaterialDef(name=name, texture=texture))
        scene.primitives.append(
            Primitive(
                material=0,
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
            )
        )
        scene.extras = {"format": "res_rdms"}
        return [scene]
    rgba = res_surf.decode(data)
    if rgba is None:
        return []
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "res_surf"}
    return [scene]
