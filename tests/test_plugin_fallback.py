"""Fallback plugins (generic containers, gx scanner) never pre-empt a real format."""

from types import SimpleNamespace

from gcrip import plugins


def _mod(name, *, fallback=False, detect=True, container=True):
    m = SimpleNamespace(
        NAME=name,
        detect=lambda p, h, s: detect,
        is_container=lambda n, h: container,
        expand=lambda d: [],
        extract=lambda d, p, s: [],
    )
    if fallback:
        m.FALLBACK = True
    return m


def test_fallback_only_when_nothing_else_claims(monkeypatch):
    real = _mod("re4")
    fb = _mod("gx", fallback=True)
    monkeypatch.setattr(plugins, "_loaded", [fb, real])
    assert plugins.plugins_for("x.bin", b"\0" * 64, 4096) == [real]
    monkeypatch.setattr(plugins, "_loaded", [fb, _mod("re4", detect=False)])
    assert plugins.plugins_for("x.bin", b"\0" * 64, 4096) == [fb]


def test_container_plugins_put_fallbacks_last(monkeypatch):
    gen = _mod("generic", fallback=True)
    real = _mod("waverace")
    monkeypatch.setattr(plugins, "_loaded", [gen, real])
    assert [m.NAME for m in plugins.container_plugins()] == ["waverace", "generic"]


def test_real_plugins_are_discovered_with_fallbacks():
    names = {m.NAME for m in plugins.all_plugins()}
    assert {"generic", "gx", "re4", "ea"} <= names
    fb = {m.NAME for m in plugins.all_plugins() if plugins.is_fallback(m)}
    assert fb == {"generic", "gx"}
