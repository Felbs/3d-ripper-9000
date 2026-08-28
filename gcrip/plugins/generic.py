"""Fallback container plugin: archives and compression streams recognised by their
structure (gcrip.formats.generic) when no format plugin knows the file.  Members are
walked like any archive, so the real plugins - and the gx scanner - see what is inside."""

from __future__ import annotations

from gcrip.formats import generic

NAME = "generic"
FALLBACK = True

MIN_SIZE = 8 << 10
MAX_LZ = 4 << 20  # pure-Python LZ decoders: keep the attempt cheap


def is_container(name: str, head: bytes) -> bool:
    return generic.worth_trying(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if len(data) < MIN_SIZE:
        return []
    # compression streams are dense: skip the (pure-Python, slow) LZ decoders unless the
    # head looks compressed; zlib is C-speed and stays cheap to try
    dense = generic._entropy(data[: 1 << 16]) >= 6.5
    if dense and len(data) <= MAX_LZ:
        dec = generic.try_decompress(data)
    else:
        dec = generic.try_zlib(data)
    if dec is not None:
        return [(f"{dec[0]}.bin", dec[1])]
    toc = generic.find_toc(data)
    if toc:
        return [(m.name, data[m.offset : m.offset + m.size]) for m in toc if m.size]
    return []


def detect(path: str, head: bytes, size: int) -> bool:  # containers only
    return False


def extract(data: bytes, path: str, src):
    return []
