"""Edge of Reality ``Datasets`` members (gcrip.formats.edge_dataset) as a container: every
entry becomes ``<Category>/<hash>.eorm`` (a model), ``.eort`` (a texture), ``.eors`` (a shader)
or ``.bin``, for ``edge_model`` / ``edge_tex`` to claim."""

from __future__ import annotations

from gcrip.formats import edge_dataset

NAME = "edge_dataset"

EXT = {"Models": "eorm", "Textures": "eort", "Shaders": "eors"}


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".bin") and edge_dataset.style(head) is not None


def expand(data: bytes) -> list[tuple[str, bytes]]:
    try:
        _kind, _name, entries = edge_dataset.entries(data)
    except edge_dataset.DatasetError:
        return []
    out = []
    seen: dict[str, int] = {}
    for e in entries:
        if not e.payload:
            continue
        ext = EXT.get(e.category, "bin")
        stem = f"{e.category}/{e.hash:08x}"
        n = seen.get(stem, 0)
        seen[stem] = n + 1
        out.append((f"{stem}{'' if n == 0 else f'_{n}'}.{ext}", e.payload))
    return out
