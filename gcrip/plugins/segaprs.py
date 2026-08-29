"""Sega PRS-compressed files (``.prs``: Sonic Adventure 2: Battle, Sonic Adventure DX and
other Sonic Team GameCube discs) as a container with a single decompressed member, so the
model and texture plugins see the payload (gcrip.formats.prs)."""

from __future__ import annotations

from gcrip.formats import prs

NAME = "segaprs"
MAX_SIZE = 64 << 20


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".prs") and len(head) >= 4


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if len(data) > MAX_SIZE:
        return []
    try:
        payload = prs.decompress(data)
    except Exception:  # noqa: BLE001
        return []
    if len(payload) < 16:
        return []
    return [("payload.bin", payload)]


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
