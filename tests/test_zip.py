"""Plain ZIP archives shipped as game data."""

import io
import zipfile

from gcrip.plugins import zip as plugin


def build() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("models/hero.dff", b"\x10\x00\x00\x00" + bytes(64))
        zf.writestr("textures/hero.txd", b"\x16\x00\x00\x00" + bytes(32))
        zf.writestr("empty.bin", b"")
        zf.writestr("dir/", b"")
    return buf.getvalue()


def test_expands_named_members():
    data = build()
    assert plugin.is_container("Data.zip", data[:8])
    out = dict(plugin.expand(data))
    assert sorted(out) == ["models/hero.dff", "textures/hero.txd"]  # empty entries dropped
    assert out["models/hero.dff"].startswith(b"\x10\x00\x00\x00")


def test_bad_archive_and_plugin_shape():
    assert plugin.expand(b"PK\x03\x04 not really a zip") == []
    assert not plugin.is_container("x.zip", b"NOPE")
    data = build()
    assert plugin.detect("x.zip", data[:8], len(data)) is False
    assert plugin.extract(data, "x.zip", None) == []
