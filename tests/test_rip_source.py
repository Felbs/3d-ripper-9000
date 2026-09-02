"""Fetching a member of a plugin container.

The manifest walk and the later fetch have to agree on which plugin expanded a container.
They did not: `manifest._walk_plugin_container` skips fallback plugins under a root an ordinary
plugin opened, and `_Source._expanded` knew nothing about those roots, so the first plugin to
claim at fetch time was not always the one that named the members.  502 models across eight
discs died with a bare KeyError on their own path.
"""

import types

from gcrip.rip import _Source


class _Entry:
    def __init__(self, container):
        self.container = container
        self.disc_offset = None
        self.size = 0
        self.offset = 0


def _plugin(name, members, claims=True):
    mod = types.ModuleType(name)
    mod.NAME = name
    mod.is_container = lambda n, h, _c=claims: _c
    mod.expand = lambda data, _m=members: list(_m)
    return mod


def _source(monkeypatch, plugins, payload=b"PAYLOAD" * 8):
    src = _Source.__new__(_Source)
    src.by_path = {"c/one": _Entry("c"), "c/two": _Entry("c")}
    src._cache = {"c": payload}
    src._cache_order = ["c"]
    monkeypatch.setattr("gcrip.plugins.container_plugins", lambda: plugins)
    return src


def test_the_plugin_that_named_the_member_is_the_one_used(monkeypatch):
    """The first claimer yields `other`; only the second yields `one`.  The search has to carry
    on to the plugin that actually produced the member being asked for."""
    first = _plugin("first", [("other", b"nope")])
    second = _plugin("second", [("one", b"YES"), ("two", b"ALSO")])
    src = _source(monkeypatch, [first, second])
    assert src.raw("c/one") == b"YES"


def test_a_claimer_that_yields_nothing_does_not_shadow(monkeypatch):
    empty = _plugin("empty", [])
    real = _plugin("real", [("one", b"YES")])
    src = _source(monkeypatch, [empty, real])
    assert src.raw("c/one") == b"YES"


def test_the_first_expansion_is_kept_when_nothing_holds_the_member(monkeypatch):
    """If no plugin produces it, the behaviour is the old one - a KeyError naming the path -
    rather than a silent wrong answer from some other plugin's expansion."""
    first = _plugin("first", [("other", b"nope")])
    src = _source(monkeypatch, [first])
    try:
        src.raw("c/one")
    except KeyError as e:
        assert "c/one" in str(e)
    else:
        raise AssertionError("expected a KeyError naming the member")
