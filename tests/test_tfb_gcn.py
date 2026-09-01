"""Madagascar `.gcn` resource archives - the geometry cluster 1 was looking for."""

import struct

from gcrip.formats import tfb_gcn
from gcrip.plugins import tfb_gcn as plugin

LIB = 0x1C020016  # the old-style stamp these payloads carry, with no 0xffff build bits


def chunk(kind: int, body: bytes) -> bytes:
    return struct.pack("<3I", kind, len(body), LIB) + body


def census_chunk(entries) -> bytes:
    body = struct.pack(">I", len(entries))
    for name, count in entries:
        raw = name.encode() + b"\0"
        raw += bytes([tfb_gcn.PAD]) * (-len(raw) % 4)
        body += raw + struct.pack(">I", count)
    return chunk(tfb_gcn.CENSUS, body)


def resource(name: str, tag: str, payload: bytes, paths=(b"c:/build/out",), pad: int = 0) -> bytes:
    """One 0x0716 resource.

    The body opens with two words - the header's own length and the name length - and the
    payload sits at ``body + 8 + header``, so the build-path strings never have to be walked.
    """
    raw_name = name.encode() + b"\0"
    raw_tag = tag.encode() + b"\0"
    header = raw_name + bytes(tfb_gcn.GUID) + struct.pack(">I", len(raw_tag)) + raw_tag
    for p in paths:
        header += struct.pack(">I", len(p)) + p
    body = struct.pack(">2I", len(header), len(raw_name)) + header + payload + bytes(pad)
    return chunk(tfb_gcn.RESOURCE, body)


def rw_payload(kind: int = 0x10, n: int = 64) -> bytes:
    return struct.pack("<3I", kind, n, LIB) + bytes(n)


def build(*parts: bytes) -> bytes:
    return b"".join(parts)


def test_a_gcn_is_a_chain_that_covers_the_file_exactly():
    data = build(census_chunk([("CTFBModel", 15)]), resource("a.dff", "rwID_CLUMP", rw_payload()))
    assert tfb_gcn.is_gcn(data)
    # a trailing byte breaks the covering identity, which is what makes the check meaningful
    assert not tfb_gcn.is_gcn(data + b"\0")


def test_the_census_reads_class_counts():
    data = build(
        census_chunk([("CTFBModel", 15), ("CProtoActor", 48), ("SpriteObject", 165)]),
        resource("a.dff", "rwID_CLUMP", rw_payload()),
    )
    assert tfb_gcn.census(data) == {"CTFBModel": 15, "CProtoActor": 48, "SpriteObject": 165}


def test_the_payload_is_found_from_the_header_length():
    data = build(census_chunk([("x", 1)]), resource("bird.dff", "rwID_CLUMP", rw_payload(n=128)))
    (res,) = tfb_gcn.resources(data)
    assert res.name == "bird.dff" and res.tag == "rwID_CLUMP"
    assert data[res.offset : res.offset + 4] == struct.pack("<I", 0x10)
    assert res.size == 12 + 128


def test_alignment_padding_is_tolerated():
    """1 to 3 bytes of four-byte padding follow the payload, and a strict flush test missed 24
    of the 49 real resources because of it."""
    for pad in (0, 1, 2, 3):
        data = build(census_chunk([("x", 1)]), resource("a.dff", "rwID_CLUMP", rw_payload(), pad=pad))
        assert len(tfb_gcn.resources(data)) == 1, f"pad {pad} rejected"


def test_a_resource_with_no_renderware_payload_is_skipped():
    """SCRIPT, TEXT and TextStringDict resources share the wrapper and carry no RW chunk."""
    data = build(census_chunk([("x", 1)]), resource("s.ai", "SCRIPT", b"not a chunk at all"))
    assert tfb_gcn.resources(data) == []


def test_the_container_hands_payloads_out_under_their_own_names():
    data = build(
        census_chunk([("x", 1)]),
        resource("bird.dff", "rwID_CLUMP", rw_payload()),
        resource("world", "rwID_WORLD", rw_payload(kind=0x0B)),
    )
    members = dict(plugin.expand(data))
    assert set(members) == {"bird.dff", "world.dff"}
    assert members["bird.dff"][:4] == struct.pack("<I", 0x10)


def test_repeated_names_do_not_collide():
    data = build(
        census_chunk([("x", 1)]),
        resource("title.dff", "rwID_CLUMP", rw_payload()),
        resource("title.dff", "rwID_CLUMP", rw_payload()),
    )
    names = [n for n, _ in plugin.expand(data)]
    assert len(set(names)) == 2
