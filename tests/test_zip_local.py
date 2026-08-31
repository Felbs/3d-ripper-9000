"""Walking a ZIP by its local headers - NFL Blitz's archives list every entry and read none."""

import io
import zipfile

from gcrip.formats import zip_local
from gcrip.plugins import zip as plugin

FILES = {"a.dff": b"model bytes" * 40, "b/c.gtd": b"terrain" * 90, "d.ini": b"[x]\nk=1\n"}


def build(compress=zipfile.ZIP_STORED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as z:
        for n, b in FILES.items():
            z.writestr(n, b)
    return buf.getvalue()


def break_central(data):
    """Point every central-directory record at a bogus offset, as NFL Blitz's do."""
    out = bytearray(data)
    at = out.find(zip_local.CENTRAL)
    while at >= 0:
        out[at + 42 : at + 46] = (0xFFFF).to_bytes(4, "little")
        at = out.find(zip_local.CENTRAL, at + 4)
    return bytes(out)


def test_local_walk_recovers_every_entry():
    got = dict(zip_local.members(build()))
    assert got == FILES


def test_deflated_entries_are_inflated():
    got = dict(zip_local.members(build(zipfile.ZIP_DEFLATED)))
    assert got == FILES


def test_the_crc_is_what_makes_the_walk_safe():
    """A mis-parsed record almost never checksums, so a bad walk yields nothing, not garbage."""
    data = bytearray(build())
    at = data.find(b"model bytes")
    data[at] = data[at] ^ 0xFF
    got = dict(zip_local.members(bytes(data)))
    assert "a.dff" not in got
    assert got["d.ini"] == FILES["d.ini"]


def test_the_plugin_falls_back_when_the_directory_reads_nothing():
    """NFL Blitz's stadium.zip lists 1,981 entries and reads none - the offsets in its central
    directory do not point at local headers.  The plugin returned an empty archive silently on
    a 179 MB file holding 1,334 RenderWare .dff models."""
    broken = break_central(build())
    assert dict(plugin.expand(broken)) == FILES


def test_a_normal_archive_still_goes_through_zipfile():
    assert dict(plugin.expand(build())) == FILES
