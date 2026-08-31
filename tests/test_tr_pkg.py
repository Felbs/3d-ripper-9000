"""Terminal Reality .PKG packages (BloodRayne, Blowout, RoadKill)."""

import struct

from gcrip.formats import tr_pkg
from gcrip.plugins import tr_pkg as plugin


def chunk(tag: bytes, name: bytes, payload: bytes) -> bytes:
    head = tr_pkg.MAGIC + tag + struct.pack("<I", len(payload))
    return head + name.ljust(tr_pkg.NAME, b"\0") + payload


def build(extra: bytes = b"") -> bytes:
    return (
        chunk(b"xet1", b"WHITE.TIF", b"pixels")
        + chunk(b"fms_", b"SHELL_MG.SMF", b"mesh-bytes")
        + extra
        + chunk(tr_pkg.END, b"", b"")
    )


def test_walks_to_the_terminator():
    d = build()
    cs = tr_pkg.chunks(d)
    assert [(c.tag, c.kind, c.name, c.size) for c in cs] == [
        ("xet1", "1tex", "WHITE.TIF", 6),
        ("fms_", "_smf", "SHELL_MG.SMF", 10),
    ]
    assert plugin.is_container("GCB_11_CREDITS.PKG", d[: tr_pkg.HEADER])
    assert plugin.expand(d) == [("WHITE.TIF", b"pixels"), ("SHELL_MG.SMF", b"mesh-bytes")]


def test_repeated_names_are_kept_apart():
    d = build(chunk(b"xet1", b"WHITE.TIF", b"second"))
    assert [n for n, _ in plugin.expand(d)] == ["WHITE.TIF", "SHELL_MG.SMF", "WHITE_001.TIF"]


def test_a_broken_chain_yields_nothing():
    assert tr_pkg.chunks(b"nope" + bytes(tr_pkg.HEADER)) == []
    assert not tr_pkg.is_pkg(b"short")
    # a size that runs past the end must not be trusted
    bad = tr_pkg.MAGIC + b"xet1" + struct.pack("<I", 1 << 24) + b"X".ljust(tr_pkg.NAME, b"\0")
    assert tr_pkg.chunks(bad) == []
    # no terminator and no clean landing
    assert tr_pkg.chunks(chunk(b"xet1", b"A.TIF", b"12345")[:-2]) == []
    assert plugin.detect("x.pkg", b"", 0) is False
    assert plugin.extract(b"", "x.pkg", None) == []


def test_detected_from_the_64_byte_sniff():
    """The chunk header is 76 bytes but a container plugin only sees SNIFF_BYTES of it."""
    from gcrip.classify import SNIFF_BYTES

    assert plugin.is_container("GCB_11_CREDITS.PKG", build()[:SNIFF_BYTES])
    assert not plugin.is_container("x.bin", b"Yoda" + bytes(SNIFF_BYTES))
