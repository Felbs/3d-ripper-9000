"""Treyarch NGL stashes (``.ST2``, gcrip.formats.treyarch_st2) as a container: Kelly
Slater's Pro Surfer keeps every asset in 209 of them.  Members are the stash's ``GCNM``
mesh and ``GCNT`` texture chunks, which the ``ngl`` plugin then decodes.

Two claims, on purpose.  ``is_container``/``expand`` walks the chunks out of the stash so
the generic fallback container no longer carves it into ``glzss@4.bin`` / ``g0000``
pseudo-members (the LZSS sniff was a false positive on plain texture data).  ``detect``
also claims the stash itself as an ordinary format that yields no scenes: without that the
``gx`` fallback scanned every 5 MB stash and exported its bounding-box tables as meshes -
36 of Kelly Slater's 42 library models were that noise (quality audit, GKSE52).
"""

from __future__ import annotations

from gcrip.formats import treyarch_st2 as st2

NAME = "st2"


def is_container(name: str, head: bytes) -> bool:
    return st2.is_stash(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return st2.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return st2.is_stash(head, size)


def extract(data: bytes, path: str, src):
    return []  # the models are the members; see the module docstring
