"""Terminal Reality ``.PKG`` packages as a container (gcrip.formats.tr_pkg): the textures,
static meshes, skinned meshes and skeletons that BloodRayne, Blowout and RoadKill keep inside
their POD archives.  Members come out under the artists' own file names, so the `.TIF`
textures land on `gcrip/plugins/tr_tex.py` and the rest reaches the structure scanner
labelled."""

from __future__ import annotations

from gcrip.formats import tr_pkg

NAME = "tr_pkg"


def is_container(name: str, head: bytes) -> bool:
    return tr_pkg.is_pkg(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return tr_pkg.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
