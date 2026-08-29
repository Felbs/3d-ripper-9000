"""Mario Party GameCube ``.bin`` archives as a container (gcrip.formats.mpbin): members are
named by their content - ``NN.hsf`` for Hudson HSF models, ``NN.dat`` otherwise."""

from __future__ import annotations

from gcrip.formats import mpbin

NAME = "mpbin"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith((".bin", ".dat")) and mpbin.is_mpbin(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in mpbin.members(data):
        try:
            blob = mpbin.read(data, m)
        except Exception:  # noqa: BLE001
            continue
        if not blob:
            continue
        ext = "hsf" if blob[:4] == b"HSFV" else "dat"
        out.append((f"{m.index:03d}.{ext}", blob))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
