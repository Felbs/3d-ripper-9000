"""Walking a ZIP by its **local headers** instead of its central directory.

NFL Blitz 20-03's ``stadium.zip`` and Blitz 20-02's ``sound.zip`` are real ZIPs - `PK 03 04`,
a proper central directory, 1,981 and 5,435 entries - and Python's :mod:`zipfile` lists every
one of them.  Reading any of them fails: the offsets the central directory gives do not point
at local headers, so every ``read`` raises ``Bad magic number for file header``.  The plugin
swallowed those per-member and returned an empty archive, silently, on a 179 MB file holding
**1,334 RenderWare ``.dff`` models**.

The entries are all there; only the directory is wrong.  Walking ``PK 03 04`` records from
offset 0 recovers all 1,981 with **every CRC matching**, and the walk ends exactly on the
central directory signature - which is what says the walk is right rather than lucky.

Used only as a fallback, so a normal archive still goes through :mod:`zipfile`.
"""

from __future__ import annotations

import struct
import zlib

LOCAL = b"PK\x03\x04"
CENTRAL = b"PK\x01\x02"
LOCAL_HEADER = 30
STORED = 0
DEFLATED = 8
MAX_MEMBER = 256 << 20
RAW_WINDOW = -15


def _entry(data: bytes, at: int) -> tuple[str, bytes, int, int] | None:
    """(name, payload, crc, next offset) for the local record at ``at``."""
    if at + LOCAL_HEADER > len(data) or data[at : at + 4] != LOCAL:
        return None
    _sig, _ver, _flags, method, _t, _d, crc, csize, usize, namelen, extralen = struct.unpack_from(
        "<IHHHHHIIIHH", data, at
    )
    body = at + LOCAL_HEADER + namelen + extralen
    if body + csize > len(data) or usize > MAX_MEMBER:
        return None
    name = data[at + LOCAL_HEADER : at + LOCAL_HEADER + namelen].decode("latin-1", "replace")
    raw = data[body : body + csize]
    if method == STORED:
        payload = raw
    elif method == DEFLATED:
        try:
            payload = zlib.decompressobj(RAW_WINDOW).decompress(raw)
        except zlib.error:
            return None
    else:
        return None
    return name, payload, crc, body + csize


def members(data: bytes) -> list[tuple[str, bytes]]:
    """Every entry whose bytes match the CRC in its own local header.

    The CRC is what makes this safe: a mis-parsed record almost never produces a payload that
    checksums, so a bad walk yields nothing rather than garbage.
    """
    out: list[tuple[str, bytes]] = []
    at = 0
    while at < len(data):
        got = _entry(data, at)
        if got is None:
            break
        name, payload, crc, nxt = got
        if payload and (zlib.crc32(payload) & 0xFFFFFFFF) == crc:
            out.append((name.replace("\\", "/"), payload))
        at = nxt
    return out
