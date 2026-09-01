"""``.gcn`` resource archives - Madagascar (Toys for Bob), and the reason cluster 1 looked empty.

The backlog filed these discs under ``.rws`` RenderWare stream bundles.  Their ``.rws`` are
**audio** (see ``docs/formats/rws-is-audio.md``); the geometry is here, in ``.gcn``, and it is
ordinary RenderWare behind a thin resource wrapper.

A ``.gcn`` is a **flat chain of little-endian RenderWare-style chunks** - ``u32 type``,
``u32 size``, ``u32 library stamp``, then ``size`` bytes - that covers the file to the byte.  On
Madagascar's 5,028,968-byte ``title.gcn`` the chain lands on 5,028,968 exactly.  Three types
appear::

    0x071C  once, a class census
    0x0716  a named resource
    0x0704  unread here

**0x071C is a census, not data**: ``u32 count`` then that many NUL-terminated names padded to
four bytes with ``0xBF``, each followed by a ``u32`` instance count - ``CTFBModel`` 15,
``CProtoActor`` 48, ``SpriteObject`` 165.  Useful for knowing what a level holds before opening
anything.

**0x0716 carries the payload**, big-endian inside the little-endian chunk::

    u32  header bytes that follow this pair
    u32  name length
    char name[]            "bird_big_mouth.dff", "title_high_Foreign_Col"
    u8   guid[16]
    u32  tag length
    char tag[]             "rwID_CLUMP", "rwID_WORLD", "rwID_TEXDICTIONARY", ...
    u32  length, char[]    repeated: the asset's original build paths
    ...
    the RenderWare payload

**The payload sits at ``body + 8 + header``** - the first word is the header's own length, so
the strings never have to be walked.  It is then confirmed by ending flush with the chunk, give
or take the 1 to 3 bytes of four-byte alignment padding that made a strict test miss 24 of 49
resources.

That rule finds **46 of the 49** RenderWare resources on ``title.gcn`` - every ``rwID_CLUMP``
(18), ``rwID_WORLD`` (5), ``rwID_TEXDICTIONARY`` (3) and ``rwID_HANIMANIMATION`` (20).  Only the
three ``rwID_2DFONT`` are shaped differently.  The payloads need no new reader: handed to
``plugins/renderware.py`` they give **114,936 triangles** from that one file, on a disc that
reports zero today.

One trap worth recording: the payload's library stamp is the **old style** ``0x1c020016``,
without the ``0xffff`` build bits, so a scan that insists on those finds nothing at all.
``rwstream.looks_like_stream`` already knows about old-style stamps; a hand-rolled check does
not.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

CENSUS = 0x071C
RESOURCE = 0x0716
HEADER = 12
GUID = 16
ALIGN = 4
PAD = 0xBF
MAX_NAME = 4096


@dataclass
class Resource:
    name: str
    tag: str
    offset: int  # of the RenderWare payload, absolute
    size: int  # of the payload, including its own 12-byte header


def _chunks(data: bytes):
    at = 0
    while at + HEADER <= len(data):
        kind, size, lib = struct.unpack_from("<3I", data, at)
        if size == 0 or at + HEADER + size > len(data):
            return
        yield at, kind, size, lib
        at += HEADER + size


def is_gcn(data: bytes) -> bool:
    """A ``.gcn`` opens with the class census and its chain covers the file exactly."""
    if len(data) < HEADER:
        return False
    kind, size, _lib = struct.unpack_from("<3I", data, 0)
    if kind != CENSUS or size == 0 or HEADER + size > len(data):
        return False
    end = 0
    for at, _k, sz, _l in _chunks(data):
        end = at + HEADER + sz
    return end == len(data)


def _text(data: bytes, at: int, length: int) -> str:
    return data[at : at + length].split(b"\0", 1)[0].decode("latin-1")


def census(data: bytes) -> dict[str, int]:
    """What the level declares it holds: class name -> instance count."""
    first = next(iter(_chunks(data)), None)
    if first is None or first[1] != CENSUS:
        return {}
    at, _kind, size, _lib = first
    body, end = at + HEADER, at + HEADER + size
    (count,) = struct.unpack_from(">I", data, body)
    p = body + 4
    out: dict[str, int] = {}
    for _ in range(count):
        stop = data.find(b"\0", p, end)
        if stop < 0:
            break
        name = data[p:stop].decode("latin-1")
        p = stop + 1
        while p < end and data[p] == PAD:  # names are padded to four bytes with 0xBF
            p += 1
        if p + 4 > end:
            break
        (out[name],) = struct.unpack_from(">I", data, p)
        p += 4
    return out


def resources(data: bytes) -> list[Resource]:
    """Every named resource that carries a RenderWare payload."""
    out: list[Resource] = []
    for at, kind, size, _lib in _chunks(data):
        if kind != RESOURCE:
            continue
        body, end = at + HEADER, at + HEADER + size
        if body + 8 > len(data):
            continue
        header, namelen = struct.unpack_from(">2I", data, body)
        if not 0 < namelen <= MAX_NAME or body + 8 + header + HEADER > end:
            continue
        name = _text(data, body + 8, namelen)
        p = body + 8 + namelen + GUID
        if p + 4 > end:
            continue
        (taglen,) = struct.unpack_from(">I", data, p)
        if not 0 < taglen <= MAX_NAME or p + 4 + taglen > end:
            continue
        tag = _text(data, p + 4, taglen)
        # the payload starts past the header block, whose length is the first word
        start = body + 8 + header
        (_kind, payload, _stamp) = struct.unpack_from("<3I", data, start)
        # it must reach the end of the chunk, allowing the four-byte alignment padding that
        # made a strict flush test miss 24 of 49 resources
        slack = end - (start + HEADER + payload)
        if payload <= 16 or not 0 <= slack < ALIGN:
            continue
        out.append(Resource(name, tag, start, HEADER + payload))
    return out
