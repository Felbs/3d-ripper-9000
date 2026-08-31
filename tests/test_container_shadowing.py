"""A container plugin that claims an archive and then yields nothing must not shadow the next
plugin that would open it.

`feporr` (Fire Emblem: Path of Radiance) claims every ``.pak`` whose header passes its own
`pack` check, which includes THQ's - and returns no members for them.  Because it sorts sixth
among the container plugins and `thq_pack` thirtieth, Avatar: The Last Airbender lost all nine
of its archives (699 MB) to a plugin that produced nothing from them.
"""

import struct

from gcrip.formats import thq_pack
from gcrip.plugins import container_plugins, feporr
from gcrip.plugins import thq_pack as thq_plugin

NAMES = ("data/boot.rad", "data/level.rad")
BODIES = (b"rad0 boot object", b"rad0 level object")


def build():
    table = thq_pack.TABLE + len(NAMES) * thq_pack.ENTRY
    names = b"".join(n.encode() + b"\0" for n in NAMES)
    data_at = table + len(names)
    head = bytearray(thq_pack.TABLE)
    head[:4] = thq_pack.MAGIC
    body = b""
    entries = b""
    cursor = 0
    for i, blob in enumerate(BODIES):
        entries += struct.pack(">4I", data_at + len(body), len(blob), 0, cursor)
        cursor += len(NAMES[i]) + 1
        body += blob
    struct.pack_into(">5I", head, 4, 1, thq_pack.TABLE, data_at + len(body), table, len(NAMES))
    return bytes(head) + entries + names + body


def test_thq_pack_opens_the_archive():
    data = build()
    got = dict(thq_plugin.expand(data))
    assert set(got) == set(NAMES)
    assert got["data/boot.rad"] == BODIES[0]


def test_feporr_claims_the_same_header_and_yields_nothing():
    """The collision this rule exists for - if feporr ever stops claiming these, the test
    still passes, but the rule below is what keeps the archive readable either way."""
    data = build()
    if feporr.is_container("c8_DATA.PAK", data[:64]):
        assert feporr.expand(data) == []


def test_the_first_plugin_that_actually_yields_members_wins():
    data = build()
    winner = None
    for mod in container_plugins():
        if not mod.is_container("c8_DATA.PAK", data[:64]):
            continue
        try:
            entries = mod.expand(data)
        except Exception:  # noqa: BLE001
            continue
        if entries:  # the rule: an empty result does not end the search
            winner = mod.NAME
            break
    assert winner == "thq_pack"
