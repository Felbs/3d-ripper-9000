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


def build_stream(want, tokens):
    return b"".join(tokens), want


def test_a_literal_run_token_is_four_bytes_a_step():
    got = wart_hog.decompress(bytes([0xE1]) + b"model\r\n{", 8)
    assert got == b"model\r\n{"


def test_a_low_token_emits_its_literals_before_the_match():
    """The stream order is token, offset byte, literals - but the literals come out first and
    the match copies after them.  Reading it the other way turns `{cactus})` CRLF TAB into
    `{cactus}` CRLF TAB `)`."""
    head = bytes([0xE5]) + b"level\r\n{\r\n\tname({cactus}"
    # token 0x01: one literal ')', length 3, offset 0x10 + 1 = 17 -> CR LF TAB
    got = wart_hog.decompress(head + bytes([0x01, 0x10]) + b")", 28)
    assert got == b"level\r\n{\r\n\tname({cactus})\r\n\t"


def test_the_length_and_offset_biases_are_three_and_one():
    got = wart_hog.decompress(bytes([0xE0]) + b"abcd" + bytes([0x04, 0x03]), 8)
    assert got == b"abcdabcd"  # length (4>>2)+3 = 4, offset 3+1 = 4


def test_a_truncated_member_declines_rather_than_half_decoding():
    """A caller must never be handed a partial member."""
    assert wart_hog.decompress(bytes([0xE0]) + b"abcd" + bytes([0x87, 0x40]), 16) is None


def test_a_member_that_does_not_reach_its_declared_size_is_refused():
    assert wart_hog.decompress(bytes([0xE0]) + b"abcd", 99) is None


# Eight members of Animaniacs' frontend.hog, three of them embedded here.  frontend_cog1 and
# frontend_cog2 are 199 packed bytes differing at a single stream byte, which makes them the
# sharpest test available: a decoder that is merely plausible cannot produce two 386-byte texts
# one character apart.
COG1 = bytes.fromhex(
    "e56c6576656c0d0a7b0d0a096e616d65287b6361637475737d011029e161636f756e742834040b0d0b70050b30"
    "8740 0b7387400b7487400b6287400b6fe16174747269627574005de64f626a656374547970657d2c20436f6e73"
    "742c204e756d6265722c200b00302e308b0032e04d657368019a4e1c30011b53e36e672c207b66726f6e74656e"
    "645f636f0eb267311c37e1496e697469616c5002076f73023e6f6e022b416d03812c205687406f6f9a00099200"
    "55e04f726965bbc0586e7461e07d0d0a0dfd0a".replace(" ", "")
)
COG2 = COG1[:142] + bytes([0x32]) + COG1[143:]
SCROLL = bytes.fromhex(
    "e56c6576656c0d0a7b0d0a096e616d65287b6361637475737d011029e161636f756e742835040b0d0b70050b30"
    "87400b7387400b7487400b6287400b6fe16174747269627574005de64f626a656374547970657d2c20436f6e73"
    "742c204e756d6265722c200b00302e30e12c2053756247726f039175704e0d8a7b1c42e04d6573680418 1c4001"
    "1b53e46e672c207b66726f6e74656e645f7363726f6c6c0021990049e1496e697469616c5002076f73022e6f6e"
    "023d416d03a32c205689409 16f9a0009a00065e04f726965c30068566e7461e34c696768744578636c7564654d"
    "61736b1c66346196404831e07d0d0a0dfd0a".replace(" ", "")
)


def test_the_three_cog_streams_decode_and_differ_at_exactly_one_character():
    """frontend_cog1/2 differ at one packed byte and must differ at one decoded character -
    the MeshName.  Length alone proves nothing here; this does."""
    one, two = wart_hog.decompress(COG1, 386), wart_hog.decompress(COG2, 386)
    assert len(one) == len(two) == 386
    assert [i for i in range(386) if one[i] != two[i]] == [201]
    assert b"{frontend_cog1}" in one and b"{frontend_cog2}" in two


def test_a_member_decodes_to_its_declared_text():
    CRLF = chr(13) + chr(10)
    got = wart_hog.decompress(COG1, 386).decode("ascii")
    assert got.startswith("level" + CRLF + "{" + CRLF + chr(9) + "name({cactus})")
    assert "attribute({ObjectType}, Const, Number, 0.000000)" in got
    assert "attribute({MeshName}, Const, String, {frontend_cog1})" in got
    assert got.endswith(")" + CRLF + "}" + CRLF + CRLF)
    assert got.count("attribute(") == 4 == int(got.split("acount(")[1][0])


def test_the_low_form_offset_is_ten_bits_not_eight():
    """The token that broke four sessions of guessing.  frontend_scroll carries `34 61`, whose
    copy has to reach back 354 bytes for `Number, `; `b + 1` gives 98 and quietly produces
    `r, 0.0000` instead.  Every smaller vector has bits 5-6 of the token clear, so a rule
    fitted to them looks general and is not."""
    got = wart_hog.decompress(SCROLL, 525).decode("ascii")
    assert "attribute({LightExcludeMask}, Amend, Number, 1.000000, SubGroupName{})" in got
    assert "{frontend_scroll}" in got


def test_every_token_form_appears_in_the_vectors():
    """Guards against a form quietly going untested: the three cog/scroll streams between them
    exercise the literal run, both short forms and the three-operand long form."""
    seen = set()
    for stream in (COG1, SCROLL):
        for byte in stream:
            seen.add("run" if byte >= 0xE0 else
                     "long" if byte >= 0xC0 else "high" if byte >= 0x80 else "low")
    assert seen == {"run", "long", "high", "low"}
