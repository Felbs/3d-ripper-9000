"""The Blitz Games object stream inside a ``.gcp`` package (:mod:`gcrip.formats.blitz_gcp`).

After the package stamp (``01 69 07 dd/mm/yyyy at hh:mm:ss by <user>``) the rest of a pack is
one flat stream of tagged values.  Each value is a type byte followed by its payload::

    0x00  u8      (NOT a terminator - it carries a byte, which is what makes the walk work)
    0x01  u8
    0x03  u16
    0x04  u32
    0x05  u32
    0x06  f32, little-endian
    0x07  NUL-terminated string

Treating ``0x00`` as a nil marker stops the walk after 163 of 200,327 values, 0.1% into the
package, which is what made earlier surveys conclude the packs held no arrays.  Giving it its
one byte walks **99.7%** of Bratz: Rock Angelz's ``hub_s3_fetm.gcp`` and **99.2%** of Pac-Man
World 3's ``mountains_1_world.gcp``, the remainder being trailing padding.  There is no length
field anywhere - landing on the end of the package IS the check that the grammar is right.

This also explains why scanning for IEEE floats finds nothing: a f32 here is five bytes,
``06`` and then the value, so no two are adjacent in the file.

What the stream contains is a **scene graph, not geometry**: 3,037 distinct strings in one
level pack, entity class names (``CFWorldNodeParticleSystem``, ``<noentclass>``), portal and
sector names, and asset references by name (``0_lightbeams_pinz01``).  The only float arrays of
any size are navigation meshes - the longest run, 408 floats, follows the string
``Transworld Navigation Mesh Edge`` - so the renderable models are not in these packs at all.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIZES = {0x00: 1, 0x01: 1, 0x03: 2, 0x04: 4, 0x05: 4, 0x06: 4}
STRING = 0x07
FLOAT = 0x06
MIN_RUN = 24  # floats in a row before a run is worth reporting


@dataclass
class Value:
    kind: str  # "i", "f" or "s"
    value: int | float | str
    offset: int


def values(data: bytes, start: int = 0, end: int | None = None) -> list[Value]:
    """Walk the stream, stopping at the first byte that is not a known tag."""
    if end is None:
        end = len(data)
    out: list[Value] = []
    p = start
    while p < end:
        tag = data[p]
        if tag == STRING:
            stop = data.find(b"\0", p + 1, end)
            if stop < 0:
                break
            out.append(Value("s", data[p + 1 : stop].decode("latin-1", "replace"), p))
            p = stop + 1
        elif tag in SIZES:
            size = SIZES[tag]
            if p + 1 + size > end:
                break
            if tag == FLOAT:
                out.append(Value("f", struct.unpack_from("<f", data, p + 1)[0], p))
            else:
                out.append(Value("i", int.from_bytes(data[p + 1 : p + 1 + size], "little"), p))
            p += 1 + size
        else:
            break
    return out


def strings(data: bytes, start: int = 0, end: int | None = None) -> list[str]:
    return [v.value for v in values(data, start, end) if v.kind == "s"]


def float_runs(vals: list[Value], minimum: int = MIN_RUN) -> list[tuple[str, list[float]]]:
    """Runs of consecutive floats, each labelled with the string that precedes it.

    On a level pack these come back as navigation meshes rather than renderable geometry, but
    the labelling is what makes that visible instead of guessed at.
    """
    out: list[tuple[str, list[float]]] = []
    run: list[float] = []
    label = ""
    last_string = ""
    for v in vals:
        if v.kind == "f":
            if not run:
                label = last_string
            run.append(float(v.value))
            continue
        if v.kind == "s":
            last_string = v.value
        if len(run) >= minimum:
            out.append((label, run))
        run = []
    if len(run) >= minimum:
        out.append((label, run))
    return out
