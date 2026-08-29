"""Phantasy Star Online BML archives as a container (gcrip.formats.bml): every entry yields
its Ninja model (``name``) and, when present, its texture archive (``name.gvm``)."""

from __future__ import annotations

from gcrip.formats import bml

NAME = "bml"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".bml") and bml.is_bml(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in bml.members(data):
        try:
            out.append((m.name, bml.read(data, m.offset, m.packed, m.size)))
        except Exception:  # noqa: BLE001
            continue
        if m.tex_packed:
            try:
                tex = bml.read(data, m.tex_offset, m.tex_packed, m.tex_size)
            except Exception:  # noqa: BLE001
                continue
            out.append((m.name + ".gvm", tex))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
