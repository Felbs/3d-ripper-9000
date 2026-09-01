"""Warthog ``WART3.00`` ``.hog`` archives (gcrip.formats.wart_hog) - Animaniacs, Looney Tunes:
Back in Action, Harry Potter and the Sorcerer's Stone.

A container only: it reads the directory, decompresses each member and hands the named results
back to the pipeline, which then offers them to every other plugin.  The archive holds no
geometry of its own, so ``detect``/``extract`` decline - they exist because
``container_plugins()`` will not register a module without them.
"""

from __future__ import annotations

import struct

from gcrip.formats import wart_hog
from ripcore.scene import Scene

NAME = "wart_hog"
SUFFIX = ".hog"
# every member opens with a u32 holding the length of the packed stream that follows, so the
# record's packed size is that stream plus four.  Slicing from the record offset instead feeds
# the codec its own length word as a token and decodes nothing.
PREFIX = 4


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src) -> list[Scene]:
    return []


def is_container(name: str, head: bytes) -> bool:
    """``rip`` passes a basename, and ``head`` is only the 64 bytes ``classify`` sniffs.

    The three Tiger Woods discs also ship ``.hog`` files and they are EA ``SHOC``, not this -
    hence the magic test rather than the extension.
    """
    return name.lower().endswith(SUFFIX) and wart_hog.is_wart_hog(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for member in wart_hog.members(data):
        # Looney Tunes' level archives store every member raw and leave the packed size at
        # zero, so the record's span is its unpacked size.  The offsets chain through those
        # sizes exactly, which is what says the members are stored rather than truncated.
        packed = member.packed or member.unpacked
        blob = data[member.offset : member.offset + packed]
        if len(blob) != packed:
            continue
        if packed == member.unpacked:
            out.append((member.name, blob))
            continue
        if len(blob) < PREFIX:
            continue
        (stream,) = struct.unpack_from(">I", blob)
        if stream + PREFIX != packed:
            continue
        body = wart_hog.decompress(blob[PREFIX : PREFIX + stream], member.unpacked)
        if body is not None:
            out.append((member.name, body))
    return out
