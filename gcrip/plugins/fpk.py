"""Eighting FPK archives as a container (gcrip.formats.fpk): Naruto: Clash of Ninja /
Gekitou Ninja Taisen, Bloody Roar: Primal Fury, Zatch Bell!, Battle Stadium D.O.N.  Members
are PRS-compressed HAL sysdope ``.dat`` models (read by the hsd plugin), ``.txg`` textures
and ``.mot`` motions."""

from __future__ import annotations

from gcrip.formats import fpk

NAME = "fpk"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".fpk") and fpk.is_fpk(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in fpk.members(data):
        try:
            out.append((m.name, fpk.read(data, m)))
        except ValueError:
            continue
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
