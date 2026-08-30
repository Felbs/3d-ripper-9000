"""``res\\n`` resource files as a container (gcrip.formats.res): Digimon Rumble Arena 2,
Lemony Snicket's A Series of Unfortunate Events and Samurai Jack: The Shadow of Aku all ship
their levels, menus and audio in this middleware format.  Splitting a file into its tagged
sections gives the structure scanner small, labelled blobs (``surf``, ``node``, ``sdta`` hold
the geometry; ``wave`` / ``musc`` are audio)."""

from __future__ import annotations

import posixpath

from gcrip.formats import res, res_surf
from ripcore.scene import Scene

NAME = "res"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".res") and res.is_res(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return res.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    # a surf member handed back by expand(); the real check needs the whole section, which
    # extract() gets, so this only screens on the name expand() gave it
    return "_surf_" in posixpath.basename(path)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = res_surf.decode(data)
    if rgba is None:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "res_surf"}
    return [scene]
