"""Terminal Reality POD archives (BloodRayne, Blowout, RoadKill = POD3; 4x4 Evo 2 = POD2)."""

import struct

from gcrip.formats import pod
from gcrip.plugins import pod as plugin

# the second name deliberately points into the tail of nothing shared, the third shares a suffix
TABLE = b"WORLD/EN/01_AIRLOCK.TXT\0MODELS/01_AIRLOCK.BST\0"
FILES = [("WORLD/EN/01_AIRLOCK.TXT", b"airlock text"), ("MODELS/01_AIRLOCK.BST", b"mesh")]


def _index(placed: bytes) -> bytes:
    return placed


def build3() -> bytes:
    body = bytearray()
    placed = []
    for name, blob in FILES:
        placed.append((name, pod.POD3_HEADER + len(body), len(blob)))
        body += blob
    index = pod.POD3_HEADER + len(body)
    out = bytearray(pod.POD3_HEADER)
    out[:4] = b"POD3"
    struct.pack_into("<2I", out, 0x58, len(FILES), 0)
    struct.pack_into("<I", out, 0x108, index)
    struct.pack_into("<I", out, 0x110, len(TABLE))
    out += body
    for name, offset, size in placed:
        out += struct.pack("<5I", TABLE.index(name.encode()), size, offset, 0x3F8B1041, 0)
    return bytes(out) + TABLE


def build2() -> bytes:
    names = pod.POD2_INDEX + len(FILES) * pod.ENTRY
    data_start = names + len(TABLE)
    index = bytearray()
    body = bytearray()
    for name, blob in FILES:
        index += struct.pack(
            "<5I", TABLE.index(name.encode()), len(blob), data_start + len(body), 0x3B6F8AF6, 0
        )
        body += blob
    out = bytearray(pod.POD2_INDEX)
    out[:4] = b"POD2"
    struct.pack_into("<I", out, 0x58, len(FILES))
    return bytes(out) + bytes(index) + TABLE + bytes(body)


def test_pod3_entries_tile():
    d = build3()
    assert pod.version(d[: pod.POD3_HEADER]) == 3
    es = pod.entries(d)
    assert [(e.name, e.size) for e in es] == [("WORLD/EN/01_AIRLOCK.TXT", 12), ("MODELS/01_AIRLOCK.BST", 4)]
    assert es[0].offset == pod.POD3_HEADER
    assert es[0].offset + es[0].size == es[1].offset  # contiguous
    assert es[0].timestamp == 0x3F8B1041


def test_pod2_index_is_inline():
    d = build2()
    assert pod.version(d[: pod.POD3_HEADER]) == 2
    assert plugin.expand(d) == [
        ("WORLD/EN/01_AIRLOCK.TXT", b"airlock text"),
        ("MODELS/01_AIRLOCK.BST", b"mesh"),
    ]


def test_plugin_expands_pod3():
    d = build3()
    assert plugin.is_container("LANGUAGE.POD", d[: pod.POD3_HEADER])
    assert plugin.expand(d) == [
        ("WORLD/EN/01_AIRLOCK.TXT", b"airlock text"),
        ("MODELS/01_AIRLOCK.BST", b"mesh"),
    ]
    assert plugin.detect("x.pod", d[: pod.POD3_HEADER], len(d)) is False
    assert plugin.extract(d, "x.pod", None) == []


def test_rejects_junk_and_bad_offsets():
    assert not pod.is_pod(b"POD1" + bytes(pod.POD3_HEADER))
    assert not pod.is_pod(b"nope")
    assert pod.version(b"POD3" + bytes(pod.POD3_HEADER)) == 0  # zero file count
    d = bytearray(build3())
    struct.pack_into("<I", d, 0x108, len(d) * 4)  # index past the end
    assert pod.entries(bytes(d)) == []


def test_detected_from_the_64_byte_sniff():
    """A container plugin only ever sees gcrip.classify.SNIFF_BYTES of a file."""
    from gcrip.classify import SNIFF_BYTES

    d = build3()
    assert plugin.is_container("LANGUAGE.POD", d[:SNIFF_BYTES])
    assert plugin.is_container("TRUCK.pod", build2()[:SNIFF_BYTES])
    assert not plugin.is_container("x.bin", b"POD1" + bytes(SNIFF_BYTES))
