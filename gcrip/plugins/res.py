"""``res\\n`` resource files as a container (gcrip.formats.res): Digimon Rumble Arena 2,
Lemony Snicket's A Series of Unfortunate Events and Samurai Jack: The Shadow of Aku all ship
their levels, menus and audio in this middleware format.  Splitting a file into its tagged
sections gives the structure scanner small, labelled blobs (``surf``, ``node``, ``sdta`` hold
the geometry; ``wave`` / ``musc`` are audio)."""

from __future__ import annotations

import posixpath

from gcrip.formats import res, res_rdms, res_surf
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "res"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".res") and res.is_res(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return res.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    # a member handed back by expand(); the real check needs the whole section, which
    # extract() gets, so this only screens on the name expand() gave it
    base = posixpath.basename(path)
    return "_surf_" in base or "_rdms_" in base


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    if "_rdms_" in name:
        mesh = res_rdms.mesh(data)
        if mesh is None:
            return []
        scene = Scene(name=name)
        # A real material, not the -1 "no material" sentinel with an empty list: the thumbnail
        # pass indexes material_colors by it, and `[][-1]` is an IndexError that failed 62,640
        # meshes across the three discs - every mesh that had triangles to draw.
        scene.materials.append(MaterialDef(name=name, texture=None))
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
