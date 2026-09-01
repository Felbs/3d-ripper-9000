"""Piglet's ``PIGGCN.pkd`` (gcrip.formats.piglet_pkd) as a container.

The payloads are ordinary RenderWare, so this only has to hand them out and
``plugins/renderware.py`` reads them.  ``detect``/``extract`` decline because
``container_plugins()`` will not register a module without them.
"""

from __future__ import annotations

from gcrip.formats import piglet_pkd
from ripcore.scene import Scene

NAME = "piglet_pkd"
SUFFIX = ".pkd"
KIND_EXT = {0x10: "dff", 0x0B: "bsp", 0x16: "txd", 0x1B: "anm", 0x1E: "rw1e", 0x0C: "rw0c"}


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    """``rip`` passes a basename and only the 64 bytes ``classify`` sniffs, which is far too few
    to prove the chain - that is ``expand``'s job.  Screen on the extension and the zlib magic."""
    return name.lower().endswith(SUFFIX) and piglet_pkd.is_pkd(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    got = piglet_pkd.inflate(data)
    if got is None:
        return []
    image, starts = got
    out = []
    for i, asset in enumerate(piglet_pkd.assets(image, starts)):
        ext = KIND_EXT.get(asset.kind, "bin")
        out.append((f"{i:05d}.{ext}", image[asset.offset : asset.offset + asset.size]))
    return out
