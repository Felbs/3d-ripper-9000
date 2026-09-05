"""Treyarch NGL chunks out of the ``.ST2`` stashes (gcrip.formats.treyarch_st2): Kelly
Slater's Pro Surfer's version-0xA ``GCNM`` meshes and its ``GCNT`` textures, reached as the
members the ``st2`` container plugin expands.  A mesh becomes one Scene with a primitive per
part (surfboards rigid, surfers skinned over a flat 40-bone skeleton); a texture becomes a
textures-only Scene.  Materials stay untextured: the part header carries no texture name
and the stash directory names are clipped by runtime pointers.

The later NGL generation (Spider-Man 2 / Ultimate Spider-Man, ``GCNM`` 0x1D-0x1F in
``amalga_gc.pak``) is ``plugins/ngl_mesh.py``; this plugin only takes textures that sit
under a stash, so those packs' ``.gct`` keep binding through their own mesh reader.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import ngl_gc
from gcrip.formats import treyarch_st2 as st2

NAME = "ngl"


def detect(path: str, head: bytes, size: int) -> bool:
    if st2.is_mesh(head):
        return True
    return ngl_gc.is_gct(head) and ".st2/" in path.lower().replace("\\", "/")


def extract(data: bytes, path: str, src):
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "ngl"
    if data[:4] == st2.TAG_TEX:
        return [st2.texture_scene(st2.decode_texture(data), stem)]
    mesh = st2.parse_mesh(data)
    return [st2.mesh_scene(mesh, mesh.name or stem)]
