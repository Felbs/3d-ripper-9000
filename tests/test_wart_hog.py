"""WART3.00 .hog archives - Warthog's engine (Animaniacs, Looney Tunes, Harry Potter)."""

import struct

from gcrip.formats import wart_hog

DIRS = ("fonts/", "localisation/")
FILES = ("font3.btga", "font3.tnf", "general_eng.loc")


def build(dirs=DIRS, files=FILES, swap_dir_bytes=False, payload=b"packed"):
    dir_blob = b"\0" + b"".join(d.encode() + b"\0" for d in dirs)
    file_blob = b"".join(f.encode() + b"\0" for f in files)
    dir_at, at = {}, 1
    for d in dirs:
        dir_at[d] = at
        at += len(d) + 1
    file_at, at = {}, 0
    for f in files:
        file_at[f] = at
        at += len(f) + 1
    table = b""
    body = b""
    start = wart_hog.HEADER + len(files) * wart_hog.ENTRY
    for i, f in enumerate(files):
        folder = dirs[i % len(dirs)]
        table += struct.pack(
            ">6I",
            start + len(body),
            len(payload),
            len(payload) * 4,
            0,
            file_at[f],
            dir_at[folder],
        )
        body += payload
    names_at = start + len(body)
    word = len(dir_blob)
    if swap_dir_bytes:
        word = struct.unpack(">I", struct.pack("<I", word))[0]
    head = wart_hog.MAGIC + struct.pack(">4I", len(files), names_at, len(file_blob), word)
    return head + table + body + dir_blob + file_blob


def test_a_member_path_is_its_directory_plus_its_name():
    got = wart_hog.members(build())
    assert [m.name for m in got] == [
        "fonts/font3.btga",
        "localisation/font3.tnf",
        "fonts/general_eng.loc",
    ]


def test_records_start_at_twenty_four_not_sixteen():
    """Read eight bytes early every offset still chains, because the two name words just
    shift the window - so contiguity cannot be what proves the field order."""
    data = build()
    first = wart_hog.members(data)[0]
    early = struct.unpack_from(">6I", data, 16)
    assert early[2] == first.offset and early[3] == first.packed
    assert first.offset == wart_hog.HEADER + 3 * wart_hog.ENTRY


def test_the_directory_bytes_word_is_accepted_in_either_byte_order():
    """Animaniacs stores it big-endian, Looney Tunes byte-swapped."""
    assert [m.name for m in wart_hog.members(build(swap_dir_bytes=True))] == [
        m.name for m in wart_hog.members(build())
    ]


def test_a_directory_word_landing_mid_string_is_refused():
    data = bytearray(build())
    struct.pack_into(">I", data, 20, 3)
    assert wart_hog.members(bytes(data)) == []


def test_the_magic_fits_in_the_sniffed_head():
    assert wart_hog.is_wart_hog(build()[:64])
    assert not wart_hog.is_wart_hog(b"CTRL" + bytes(60))


def test_a_table_overrunning_the_name_section_is_refused():
    data = bytearray(build())
    struct.pack_into(">I", data, 8, 4000)
    assert wart_hog.members(bytes(data)) == []


def test_sizes_are_reported_packed_and_unpacked():
    """Every member is compressed; the codec is still open, so a reader that pretended
    otherwise would hand the pipeline garbage."""
    got = wart_hog.members(build())
    assert all(m.unpacked == m.packed * 4 for m in got)
