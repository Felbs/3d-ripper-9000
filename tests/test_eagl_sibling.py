"""EAGL `.ord` files are half an object; the other half is not always beside them.

32 models across 8 discs failed with "section table outside the file (missing .orp?)".  The
half was on the disc the whole time: NBA Live splits the pair across two containers in the same
directory - the `.ord` in `anim/body/xanims.viv/` and its `.orl` in `anim/body/xsyms.viv/` - and
the lookup only ever searched the `.ord`'s own folder.
"""

from __future__ import annotations

from gcrip.plugins import eagl


class FakeSource:
    def __init__(self, files: dict[str, bytes]):
        self.by_path = dict(files)

    def get(self, path: str) -> bytes:
        return self.by_path[path]  # KeyError for anything absent, like the real source


NBA_LIVE = {
    "files/anim/body/xanims.viv/xmcpbnch.ord": b"ORD-DATA",
    "files/anim/body/xsyms.viv/xmcpbnch.orl": b"ORL-DATA",
    "files/anim/body/x3panims.viv/xmcp3ptcut.ord": b"ORD-2",
    "files/anim/body/x3psyms.viv/xmcp3ptcut.orl": b"ORL-2",
}


def test_sibling_in_the_same_folder_still_wins():
    src = FakeSource({
        "files/models/hero.ord": b"ORD",
        "files/models/hero.orp": b"ORP",
        "files/other/hero.orp": b"WRONG",
    })
    assert eagl._sibling(src, "files/models/hero.ord", "hero.orp") == b"ORP"


def test_sibling_is_found_in_a_neighbouring_container():
    src = FakeSource(NBA_LIVE)
    got = eagl._sibling(src, "files/anim/body/xanims.viv/xmcpbnch.ord", "xmcpbnch.orl")
    assert got == b"ORL-DATA"
    got2 = eagl._sibling(src, "files/anim/body/x3panims.viv/xmcp3ptcut.ord", "xmcp3ptcut.orl")
    assert got2 == b"ORL-2"


def test_a_match_in_an_unrelated_directory_is_not_used():
    """The search widens by one directory level, not across the disc - a same-named file
    somewhere else is a different object."""
    src = FakeSource({
        "files/anim/body/xanims.viv/hero.ord": b"ORD",
        "files/zzz/elsewhere.viv/hero.orl": b"NOT-THIS",
    })
    assert eagl._sibling(src, "files/anim/body/xanims.viv/hero.ord", "hero.orl") is None


def test_missing_sibling_returns_none_rather_than_raising():
    src = FakeSource({"files/a/b.viv/x.ord": b"ORD"})
    assert eagl._sibling(src, "files/a/b.viv/x.ord", "x.orp") is None


def test_the_basename_index_is_built_once():
    src = FakeSource(NBA_LIVE)
    first = eagl._basename_index(src)
    second = eagl._basename_index(src)
    assert first is second
    assert set(first["xmcpbnch.orl"]) == {"files/anim/body/xsyms.viv/xmcpbnch.orl"}
