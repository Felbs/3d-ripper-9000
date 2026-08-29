"""Fallback container plugin: archives and compression streams recognised by their
structure (gcrip.formats.generic) when no format plugin knows the file.  Members are
walked like any archive, so the real plugins - and the gx scanner - see what is inside."""

from __future__ import annotations

from gcrip.formats import generic

NAME = "generic"
FALLBACK = True

MIN_SIZE = 8 << 10
MAX_LZ = 4 << 20  # pure-Python LZ decoders: keep the attempt cheap


_PREFIX = {"": "g", "g": "gg"}  # member name prefix by the level we are expanding at
_level = ""  # set by is_container for the blob expand() is about to see


def _level_of(name: str) -> str | None:
    """'' for a file no generic expansion produced, 'g' / 'gg' for our members, None when
    the name is already two generic levels deep (do not go further)."""
    stem = name.rsplit("/", 1)[-1]
    if stem.startswith("gg") and stem[2:].isdigit():
        return None
    if stem.startswith("g") and stem[1:].isdigit():
        return "g"
    return ""


def is_container(name: str, head: bytes) -> bool:
    global _level
    lvl = _level_of(name)
    if lvl is None:
        return False
    _level = lvl
    return generic.worth_trying(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if len(data) < MIN_SIZE:
        return []
    prefix = _PREFIX[_level]
    # compression streams are dense: skip the (pure-Python, slow) LZ decoders unless the
    # head looks compressed; zlib is C-speed and stays cheap to try
    dense = generic._entropy(data[: 1 << 16]) >= 6.5
    if dense and len(data) <= MAX_LZ:
        dec = generic.try_decompress(data)
    else:
        dec = generic.try_zlib(data)
    if dec is not None:
        return [(f"{prefix}{dec[0]}.bin", dec[1])]
    toc = generic.find_toc(data, offset_only=(_level == ""))
    if toc:
        return [(prefix + m.name, data[m.offset : m.offset + m.size]) for m in toc if m.size]
    return []


def detect(path: str, head: bytes, size: int) -> bool:  # containers only
    return False


def extract(data: bytes, path: str, src):
    return []
