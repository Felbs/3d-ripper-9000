"""Crystal Dynamics bigfile.dat - Tomb Raider: Legend."""

import struct
import zlib

from gcrip.formats import cd_bigfile
from gcrip.plugins import cd_bigfile as plugin

PAYLOADS = tuple(b"member %02d bytes" % i * (i + 1) for i in range(8))
HASHES = tuple(0x1000 * (i + 1) + i for i in range(8))
COMPRESS = tuple(i % 2 == 0 for i in range(8))


def build(payloads=PAYLOADS, compress=COMPRESS, sentinel=cd_bigfile.SENTINEL, hashes=HASHES):
    count = len(payloads)
    table = 4 + count * 4
    body_at = table + count * cd_bigfile.ENTRY
    start = (body_at + cd_bigfile.SECTOR - 1) // cd_bigfile.SECTOR
    blobs, recs, sector = [], [], start
    for p, z in zip(payloads, compress, strict=True):
        raw = zlib.compress(p) if z else p
        recs.append(struct.pack(">4I", len(p), sector, sentinel, 0))
        blobs.append((sector, raw))
        sector += (len(raw) + cd_bigfile.SECTOR - 1) // cd_bigfile.SECTOR
    out = bytearray(struct.pack(">I", count) + struct.pack(f">{count}I", *hashes) + b"".join(recs))
    out += bytes(sector * cd_bigfile.SECTOR - len(out))
    for at, raw in blobs:
        out[at * cd_bigfile.SECTOR : at * cd_bigfile.SECTOR + len(raw)] = raw
    return bytes(out)


def test_members_are_named_by_their_hash():
    """There is no name table in the archive at all - only the sorted hashes."""
    got = cd_bigfile.members(build())
    assert [m.name for m in got] == [f"{h:08x}" for h in HASHES]


def test_a_zlib_member_and_a_stored_member_both_come_back():
    data = build()
    got = {m.name: cd_bigfile.read(data, m) for m in cd_bigfile.members(data)}
    assert list(got.values()) == list(PAYLOADS)


def test_the_unpacked_size_has_to_match():
    """A member that inflates to the wrong size is refused rather than passed on short."""
    data = bytearray(build())
    table = 4 + len(PAYLOADS) * 4
    struct.pack_into(">I", data, table, 999)
    first = cd_bigfile.members(bytes(data))[0]
    assert cd_bigfile.read(bytes(data), first) is None


def test_the_sentinel_word_fixes_the_stride():
    """Every record's third word is 0xffffffff on all 4,314 of Tomb Raider's entries, and it
    is what pins the 16-byte stride."""
    assert cd_bigfile.members(build(sentinel=0)) == []


def test_unsorted_hashes_are_refused():
    """The hash array is what identifies the format; out of order it is something else."""
    assert cd_bigfile.members(build(hashes=HASHES[::-1])) == []


def test_detection_fits_in_the_sniffed_head():
    head = build()[:64]
    assert cd_bigfile.is_bigfile(head)
    assert plugin.is_container("bigfile.dat", head)
    assert not cd_bigfile.is_bigfile(b"AFS\0" + bytes(60))


def test_the_plugin_yields_every_readable_member():
    assert [n for n, _ in plugin.expand(build())] == [f"{h:08x}" for h in HASHES]
