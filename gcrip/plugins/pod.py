"""Terminal Reality ``POD3`` archives as a container (gcrip.formats.pod): BloodRayne,
4x4 Evo 2, Blowout and RoadKill ship their whole game in a handful of PODs (Blowout's seven
run to 180 MB).  Expanding one hands the rest of the pipeline named members - the models,
textures and levels inside are per-game formats picked up by the other plugins and by the
structure scanner."""

from __future__ import annotations

from gcrip.formats import pod

NAME = "pod"


def is_container(name: str, head: bytes) -> bool:
    return pod.is_pod(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return pod.expand(data)


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
