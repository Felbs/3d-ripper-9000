"""Kalisto TotemTech `.ngc` index (gcrip.formats.totemtech).

docs/OPEN.md recorded the blocker as "the file has no directory at all - nothing anywhere
references the verified vertex data".  There is one: the sibling `.ngc`, a plain-text
hash-to-typed-path index, and its hashes appear in the `.dgc` big-endian.
"""

from __future__ import annotations

import struct

import pytest

from gcrip.formats import totemtech

SAMPLE = (
    b'-853289997 "WORLD"\r\n'
    b'854756687 "DB:>LEVELS>LEVEL07A>MAP>LEVEL07A.TWORLD"\r\n'
    b'596819425 "LEVEL07A"\r\n'
    b'-1989570394 "DB:>LEVELS>LEVEL07A>MAP>3DNODEFAMILY>ROOT_LEVEL07A.T3DNODE"\r\n'
    b'1085295399 "DB:>LEVELS>LEVEL07A>MESHES>O_ECHAFAUDAGE_MESH.TMESH"\r\n'
)


def test_index_parses_hash_and_path():
    ents = totemtech.index(SAMPLE)
    assert len(ents) == 5
    assert ents[0].path == "WORLD"
    assert ents[1].name == "LEVEL07A.TWORLD"
    assert ents[3].kind == "T3DNODE"


def test_negative_hashes_become_unsigned():
    """They are written signed and appear in the .dgc as unsigned big-endian."""
    ents = totemtech.index(SAMPLE)
    assert ents[0].hash == (-853289997 & 0xFFFFFFFF)
    assert 0 <= ents[0].hash <= 0xFFFFFFFF


def test_of_kind_selects_the_meshes():
    meshes = totemtech.of_kind(totemtech.index(SAMPLE), "TMESH")
    assert [e.name for e in meshes] == ["O_ECHAFAUDAGE_MESH.TMESH"]


def test_locate_finds_the_hash_big_endian():
    ents = totemtech.index(SAMPLE)
    e = ents[4]
    blob = b"\x00" * 16 + struct.pack(">I", e.hash) + b"\x00" * 8 + struct.pack(">I", e.hash)
    assert totemtech.locate(blob, e) == [16, 28]
    # and the little-endian encoding is genuinely absent - 400/400 vs 0/400 on the real file
    assert struct.pack("<I", e.hash) not in blob or e.hash in (0,)


def test_a_bare_label_has_no_kind():
    ents = totemtech.index(SAMPLE)
    assert ents[0].kind == ""
    assert ents[2].kind == ""


def test_unparsable_lines_are_skipped_not_guessed():
    assert totemtech.index(b'not an index line\r\n42 "OK.TMESH"\r\n') == [
        totemtech.Entry(42, "OK.TMESH")
    ]


def test_dgc_banner():
    assert totemtech.is_dgc(b"TotemTech Data v1.75 (c) Kalisto")
    assert not totemtech.is_dgc(b"something else entirely")


# -- the record chain and the meshes --------------------------------------------------------


def _hash(name: str) -> int:
    """Any stable 32-bit value; the reader only ever compares hashes to the index."""
    return (abs(hash(name)) % 0xFFFFFF00) + 1


def make_dgc(objects, *, gap: int = 0) -> tuple[bytes, bytes]:
    """A .dgc / .ngc pair holding `objects` = [(path, payload)] as a record chain."""
    lines = ['0 "WORLD"']
    body = bytearray()
    seen = {}
    for path, payload in objects:
        name = path.rsplit(">", 1)[-1]
        short = name.rsplit(".", 1)[0]
        kind = name.rsplit(".", 1)[1][1:] if "." in name else ""
        for label in (kind, short, path):
            if label and label not in seen:
                seen[label] = _hash(label)
                lines.append(f'{seen[label]} "{label}"')
        rec = struct.pack(">4I", 16 + len(payload) + gap, seen[kind], seen[path], seen[short])
        body += rec + payload + b"\xcd" * gap
    head = totemtech.BANNER + b" test\x00" + b"\x00" * 32
    return bytes(head + body), ("\n".join(lines) + "\n").encode()


def make_mesh_payload(positions, strips, *, uvs=(), normals=()) -> bytes:
    """The bytes that follow a TMESH record header: three streams, then the strips."""
    out = bytearray(b"\x00" * (totemtech.MESH_VERTEX_COUNT - totemtech.REC_HEADER))
    out += struct.pack(">I", len(positions))
    for p in positions:
        out += struct.pack(">3f", *p)
    out += struct.pack(">I", len(uvs))
    for u in uvs:
        out += struct.pack(">2f", *u)
    out += struct.pack(">I", len(normals))
    for n in normals:
        out += struct.pack(">3f", *n)
    out += struct.pack(">I", len(strips))
    for idx, mode in strips:
        out += struct.pack(">I", len(idx)) + struct.pack(f">{len(idx)}H", *idx)
        out += struct.pack(">I", 6) + bytes([mode])
    out += b"\x00\x00\x00\x00" * len(strips)
    return bytes(out)


CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1)]


def test_the_chain_walks_every_record():
    dgc, ngc = make_dgc(
        [
            ("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3), 2)])),
            ("DB:>A>TWO.TSURFACE", b"\x11" * 40),
            ("DB:>A>THREE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3, 4), 1)])),
        ]
    )
    recs = totemtech.records(dgc, totemtech.index(ngc))
    assert len(recs) == 3, [r.offset for r in recs]
    assert [r.offset + r.size for r in recs[:-1]] == [r.offset for r in recs[1:]]


def test_the_walk_steps_over_a_gap_rather_than_stopping():
    """Nine of 2,036 hops on the real level land a few bytes short of the next header."""
    dgc, ngc = make_dgc(
        [
            ("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2), 2)])),
            ("DB:>A>TWO.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3), 2)])),
        ],
        gap=0,
    )
    # shorten the first record's declared size so its end falls 8 bytes early
    size = struct.unpack_from(">I", dgc, len(totemtech.BANNER) + 38)[0]
    at = dgc.index(struct.pack(">I", size))
    hurt = dgc[:at] + struct.pack(">I", size - 8) + dgc[at + 4 :]
    assert len(totemtech.records(hurt, totemtech.index(ngc))) == 2


def test_a_mesh_reads_back_its_own_geometry():
    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3, 4, 5), 2)]))])
    rec = totemtech.records(dgc, totemtech.index(ngc))[0]
    mesh = totemtech.mesh(dgc, rec)
    assert len(mesh.positions) == 6
    assert mesh.positions[1].tolist() == [1.0, 0.0, 0.0]
    assert len(mesh.strips) == 1 and mesh.strips[0].mode == 2
    assert len(mesh.triangles()) == 4  # a six-index strip is four triangles


def test_a_strip_flattens_with_alternating_winding():
    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3), 1)]))])
    mesh = totemtech.mesh(dgc, totemtech.records(dgc, totemtech.index(ngc))[0])
    assert mesh.triangles() == [(0, 1, 2), (2, 1, 3)]


def test_degenerate_joins_are_dropped():
    """Strips are stitched with repeated indices; those carry winding, not area."""
    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 1, 2, 3), 2)]))])
    mesh = totemtech.mesh(dgc, totemtech.records(dgc, totemtech.index(ngc))[0])
    assert all(len(set(t)) == 3 for t in mesh.triangles())


def test_an_index_past_the_vertex_array_is_refused():
    """The containment check is the identity that says the streams were read correctly:
    on the real level every index of every strip lands inside the positions, 52 of 52."""
    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 99), 2)]))])
    rec = totemtech.records(dgc, totemtech.index(ngc))[0]
    with pytest.raises(totemtech.TotemError, match="outside"):
        totemtech.mesh(dgc, rec)


def test_a_stream_that_runs_past_the_record_is_refused():
    payload = make_mesh_payload(CUBE, [((0, 1, 2), 2)])
    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", payload)])
    at = dgc.index(payload) + totemtech.MESH_VERTEX_COUNT - totemtech.REC_HEADER
    hurt = dgc[:at] + struct.pack(">I", 1 << 19) + dgc[at + 4 :]
    rec = totemtech.records(hurt, totemtech.index(ngc))[0]
    with pytest.raises(totemtech.TotemError, match="past the record"):
        totemtech.mesh(hurt, rec)


class _Src:
    def __init__(self, files):
        self.by_path = files

    def get(self, path):
        return self.by_path[path]


def test_the_plugin_pairs_the_dgc_with_its_ngc():
    from gcrip.plugins import totemtech as plugin

    dgc, ngc = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2, 3), 2)]))])
    src = _Src({"lvl/A.dgc": dgc, "lvl/A.ngc": ngc})
    assert plugin.detect("lvl/A.dgc", dgc[:64], len(dgc))
    scenes = plugin.extract(dgc, "lvl/A.dgc", src)
    assert len(scenes) == 1 and scenes[0].name == "ONE"
    assert scenes[0].triangles == 2
    assert scenes[0].primitives[0].material == 0
    assert scenes[0].materials  # the material index has to point at something


def test_the_plugin_says_so_when_the_index_is_missing():
    """A missing sibling must not look like a disc with no geometry."""
    from gcrip.plugins import totemtech as plugin

    dgc, _ = make_dgc([("DB:>A>ONE.TMESH", make_mesh_payload(CUBE, [((0, 1, 2), 2)]))])
    with pytest.raises(totemtech.TotemError, match="no sibling"):
        plugin.extract(dgc, "lvl/A.dgc", _Src({"lvl/A.dgc": dgc}))
