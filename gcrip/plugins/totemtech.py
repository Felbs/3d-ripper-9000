"""Kalisto TotemTech ``.dgc`` data files (Spirits & Spells, Jimmy Neutron: Boy Genius,
SpongeBob: Revenge of the Flying Dutchman).

Every ``.dgc`` is a chain of records whose directory is the sibling ``.ngc`` - a plain-text
index of ``<hash> "<typed path>"`` lines - so this plugin reads the pair.  One Scene per
``TMESH``, named by the path the index gives it.
"""

from __future__ import annotations

import contextlib

import numpy as np

from gcrip.formats import totemtech
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "totemtech"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".dgc") and totemtech.is_dgc(head)


def _index(src, path: str) -> bytes | None:
    """The sibling index.  Same stem, ``.ngc`` instead of ``.dgc`` - 225 of 225 pair up."""
    for name in (path[:-4] + ".ngc", path[:-4] + ".NGC"):
        with contextlib.suppress(Exception):
            data = src.get(name)
            if data:
                return data
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    raw = _index(src, path)
    if not raw:
        # without the directory a record header cannot be told from its payload, so say so
        # rather than returning nothing: a silent drop reads as "this disc has no geometry"
        raise totemtech.TotemError(f"no sibling .ngc index beside {path}")
    entries = totemtech.index(raw)
    if not entries:
        raise totemtech.TotemError(f"the sibling index of {path} parsed to nothing")
    byhash = {e.hash: e for e in entries if e.hash}
    scenes: list[Scene] = []
    dropped: list[str] = []
    for rec in totemtech.records(data, entries):
        entry = byhash.get(rec.ident)
        if entry is None or entry.kind != "TMESH":
            continue
        try:
            mesh = totemtech.mesh(data, rec)
        except totemtech.TotemError as exc:
            dropped.append(f"{entry.name}: {exc}")
            continue
        tris = mesh.triangles()
        if not tris or not len(mesh.positions):
            dropped.append(f"{entry.name}: no triangles")
            continue
        scene = Scene(name=entry.name.rsplit(".", 1)[0] or entry.name)
        scene.materials.append(MaterialDef(name=f"{scene.name}_mat", texture=None))
        scene.primitives.append(
            Primitive(
                material=0,
                positions=np.ascontiguousarray(mesh.positions, dtype=np.float32),
                indices=np.asarray(tris, dtype=np.uint32).reshape(-1),
            )
        )
        # the normals are a stream of their own length and nothing yet says which index
        # reaches them, so they are carried as a note rather than guessed onto the vertices
        scene.extras["totemtech"] = {
            "path": entry.path,
            "strips": len(mesh.strips),
            "normals": int(len(mesh.normals)),
            "uvs": int(len(mesh.uvs)),
        }
        scenes.append(scene)
    if not scenes:
        raise totemtech.TotemError(
            f"no TMESH records read in {path}"
            + (f" ({len(dropped)} dropped: {dropped[0]})" if dropped else "")
        )
    if dropped:
        scenes[0].warnings.append(f"{len(dropped)} TMESH records did not read: {dropped[0]}")
    return scenes
