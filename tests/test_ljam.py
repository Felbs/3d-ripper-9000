"""LJAM archives - Hunter: The Reckoning."""

import struct

from gcrip.formats import ljam
from gcrip.plugins import ljam as plugin


def node(files, dirs):
    """files: (name, offset, size); dirs: (name, node offset)."""
    out = struct.pack("<I", len(files))
    for name, offset, size in files:
        out += name.encode().ljust(ljam.NAME, b"\0")[: ljam.NAME] + struct.pack("<2I", offset, size)
    out += struct.pack("<I", len(dirs))
    for name, at in dirs:
        out += name.encode().ljust(ljam.NAME, b"\0")[: ljam.NAME] + struct.pack("<I", at)
    return out


def build():
    """Root -> UI -> {two files, GRAPHICS -> two files}, laid out the way the game does it:
    every node is its files and then its subdirectories."""
    payloads = [b"script data", b"\x00\x20\xaf\x30tpl", b"tga bytes here", b"twelve chars"]
    root_at = ljam.ROOT
    ui_at = root_at + len(node([], [("UI", 0)]))
    gfx_at = ui_at + len(node([("A", 0, 0)] * 2, [("GRAPHICS", 0)]))
    data_at = gfx_at + len(node([("A", 0, 0)] * 2, []))

    offsets, p = [], data_at
    for blob in payloads:
        offsets.append(p)
        p += len(blob)

    body = b"LJAM"
    body += node([], [("UI", ui_at)])
    body += node(
        [("LOADER.AUD", offsets[0], len(payloads[0])), ("LOGOS.TPL", offsets[1], len(payloads[1]))],
        [("GRAPHICS", gfx_at)],
    )
    body += node(
        [
            ("HVOLTAGE.TGA", offsets[2], len(payloads[2])),  # exactly 12 characters, no NUL
            ("TWELVECHARS.", offsets[3], len(payloads[3])),
        ],
        [],
    )
    assert len(body) == data_at, (len(body), data_at)
    return body + b"".join(payloads)


def test_every_member_is_found_and_the_file_is_covered():
    data = build()
    ms = ljam.members(data)
    assert [m.path for m in ms] == [
        "/UI/LOADER.AUD",
        "/UI/LOGOS.TPL",
        "/UI/GRAPHICS/HVOLTAGE.TGA",
        "/UI/GRAPHICS/TWELVECHARS.",
    ]
    assert sum(m.size for m in ms) == len(data) - ms[0].offset


def test_a_node_is_files_then_directories():
    """Read as one table the walk parses the first branch and stops - which is how the
    GRAPHICS textures went missing."""
    data = build()
    assert len(ljam.members(data)) == 4  # not 2


def test_a_twelve_character_name_has_no_terminator():
    data = build()
    names = [m.path.rsplit("/", 1)[-1] for m in ljam.members(data)]
    assert "HVOLTAGE.TGA" in names and len(names[2]) == ljam.NAME


def test_members_come_out_with_their_contents():
    got = dict(plugin.expand(build()))
    assert got["UI__LOGOS.TPL"].startswith(b"\x00\x20\xaf\x30")
    assert got["UI__GRAPHICS__HVOLTAGE.TGA"] == b"tga bytes here"


def test_container_detects_on_the_magic_only():
    assert plugin.is_container("INTROUI.JAM", b"LJAM" + bytes(60))
    assert not plugin.is_container("FeSplash.JAM", b"JAM2" + bytes(60))


def test_a_bad_child_offset_does_not_lose_its_siblings():
    data = bytearray(build())
    at = data.index(b"GRAPHICS")
    struct.pack_into("<I", data, at + ljam.NAME, len(data) + 999)  # dangling subtree
    assert len(ljam.members(bytes(data))) == 2  # the two files above it survive
