"""Structure-based container cracking (gcrip.formats.generic)."""

import struct
import zlib

import numpy as np

from gcrip.formats import generic


def _members(k: int = 6) -> list[bytes]:
    rng = np.random.default_rng(k)
    return [rng.integers(0, 256, 300 + 97 * i, dtype=np.uint8).tobytes() for i in range(k)]


def _archive(records, header: bytes, members: list[bytes], stride: int) -> bytes:
    table = b"".join(records)
    base = len(header) + len(table)
    base = (base + 31) & ~31
    out = bytearray(header + table)
    out += b"\0" * (base - len(out))
    for m in members:
        out += m
        out += b"\0" * (-len(out) % 32)
    return bytes(out)


def test_offset_size_table_with_hash_column():
    members = _members()
    header = b"ARCH" + struct.pack(">II", len(members), 0)
    offs, pos = [], (len(header) + 12 * len(members) + 31) & ~31
    for m in members:
        offs.append(pos)
        pos += (len(m) + 31) & ~31
    rows = enumerate(zip(offs, members, strict=True))
    recs = [struct.pack(">III", 0xDEAD0000 + i, o, len(m)) for i, (o, m) in rows]
    blob = _archive(recs, header, members, 12)
    toc = generic.find_toc(blob)
    assert toc is not None and len(toc) == len(members)
    assert [blob[m.offset : m.offset + m.size] for m in toc] == members


def test_offsets_only_table():
    members = _members(5)
    header = b"PACK" + struct.pack(">I", len(members))
    pos = (len(header) + 4 * len(members) + 31) & ~31
    offs = []
    for m in members:
        offs.append(pos)
        pos += (len(m) + 31) & ~31
    recs = [struct.pack(">I", o) for o in offs]
    blob = _archive(recs, header, members, 4)
    toc = generic.find_toc(blob)
    assert toc is not None and len(toc) == len(members)
    for got, want in zip(toc, members, strict=True):
        assert blob[got.offset : got.offset + len(want)] == want


def test_no_table_in_noise_or_text():
    rnd = np.random.default_rng(1).integers(0, 256, 1 << 16, dtype=np.uint8).tobytes()
    assert generic.find_toc(rnd) is None
    assert generic.find_toc(b"the quick brown fox " * 4000) is None
    assert generic.find_toc(bytes(1 << 16)) is None


def _literal_lz10(payload: bytes) -> bytes:
    out = bytearray(b"\x10" + len(payload).to_bytes(3, "little"))
    for i in range(0, len(payload), 8):
        out += b"\x00" + payload[i : i + 8]
    return bytes(out)


def _literal_lzss(payload: bytes) -> bytes:
    out = bytearray(struct.pack(">I", len(payload)))
    for i in range(0, len(payload), 8):
        out += b"\xff" + payload[i : i + 8]
    return bytes(out)


def test_decompress_zlib_lz10_lzss():
    payload = (b"GX display list " * 200) + bytes(range(256)) * 4
    assert generic.try_decompress(zlib.compress(payload))[1] == payload
    assert generic.try_decompress(b"HDR!" + zlib.compress(payload))[1] == payload
    scheme, out = generic.try_decompress(_literal_lz10(payload))
    assert scheme == "lz10" and out == payload
    scheme, out = generic.try_decompress(_literal_lzss(payload))
    assert scheme.startswith("lzss") and out == payload


def test_lz10_backrefs_roundtrip_known_stream():
    # "abcabcabc": literal a b c, then a back-reference of length 6 distance 3
    stream = b"\x10" + (9).to_bytes(3, "little") + b"\x10" + b"abc" + bytes([(6 - 3) << 4 | 0, 2])
    assert generic.lz10(stream, 9, 4) == b"abcabcabc"


def test_decompress_rejects_noise():
    rnd = np.random.default_rng(2).integers(0, 256, 4096, dtype=np.uint8).tobytes()
    assert generic.try_decompress(rnd) is None
    assert generic.try_decompress(bytes(4096)) is None


def test_number_array_is_not_a_table():
    """Sample-offset arrays (audio banks) used to become thousands of 4-byte members."""
    import numpy as np

    from gcrip.formats import generic

    offs = (np.arange(2048, dtype=">u4") * 4 + 8192).tobytes()
    blob = offs + bytes(range(256)) * 64
    assert generic.find_toc(blob) is None


def test_generic_plugin_nesting_cap():
    from gcrip.plugins import generic as plug

    head = bytes(64)
    assert plug._level_of("files/a.bin") == ""
    assert plug._level_of("files/a.bin/g0003") == "g"
    assert plug._level_of("files/a.bin/g0003/gg0001") is None
    assert not plug.is_container("x/gg0001", head)
