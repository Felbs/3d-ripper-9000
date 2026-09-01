"""The `indx` section of a `res` file - a name directory for the other sections."""

import struct

from gcrip.formats import res


def build(name=b"menus/train_game/bobblehead_texture.tif", tag=b"surf", bad_tag=False):
    """A res file holding one `surf`, one `strg` and one `indx` that names the surf.

    Both offsets in an index entry are **self-relative** - measured from the field's own
    position, the same convention `rdms` uses for its array offsets.
    """
    data_off = 0x1000
    strings = name + b"\0"
    surf = b"TEXTUREBYTES!"
    index = bytearray(res.INDEX_HEADER + res.INDEX_ENTRY)
    # indx before strg, as the real files have it, so the name offset runs forward
    payloads = [(b"surf", 4, surf), (b"indx", 44, bytes(index)), (b"strg", 28, bytes(strings))]
    body = bytearray()
    entries = []
    for t, ident, blob in payloads:
        entries.append((ident, t, len(body), len(blob)))
        body += blob
    dir_off = data_off + 0x1000
    out = bytearray(dir_off)
    out[:4] = res.MAGIC
    struct.pack_into("<H", out, 4, 7)
    struct.pack_into(">2I", out, 8, data_off, len(body))
    struct.pack_into(">2I", out, 0x1C, dir_off, 4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", out, 0x24, len(entries))
    out[data_off : data_off + len(body)] = body
    dirbuf = bytearray(4 + len(entries) * res.ENTRY)
    struct.pack_into(">I", dirbuf, 0, len(entries))
    for i, (ident, t, off, size) in enumerate(entries):
        struct.pack_into(">I4sIII", dirbuf, 4 + i * res.ENTRY, ident, t, off, size, 0)
    blob = bytearray(bytes(out) + bytes(dirbuf))

    surf_at = data_off + entries[0][2]
    indx_at = data_off + entries[1][2]
    strg_at = data_off + entries[2][2]
    field = indx_at + res.INDEX_HEADER
    struct.pack_into(">I", blob, indx_at, 1)
    struct.pack_into(">I", blob, indx_at + 4, 4)
    struct.pack_into(">I", blob, field, strg_at - field)  # name offset, self-relative
    struct.pack_into(">4s", blob, field + 4, b"node" if bad_tag else tag)
    struct.pack_into(">i", blob, field + 8, surf_at - (field + 8))  # section delta
    return bytes(blob)


def test_the_index_names_a_section():
    (entry,) = res.index_entries(build())
    assert entry.tag == "surf"
    assert entry.name == "menus/train_game/bobblehead_texture.tif"
    secs = {s.offset: s.tag for s in res.sections(build())}
    assert secs[entry.offset] == "surf"


def test_both_offsets_are_self_relative():
    """Measured from the `indx` section's start instead, none of Lemony Snicket's six names
    lands on a string - which is what identified the convention."""
    data = build()
    (entry,) = res.index_entries(data)
    index = next(s for s in res.sections(data) if s.tag == "indx")
    field = index.offset + res.INDEX_HEADER
    (stored,) = struct.unpack_from(">I", data, field)
    assert field + stored != index.offset + stored  # the two bases genuinely differ
    assert entry.name.endswith(".tif")


def test_an_entry_whose_tag_disagrees_with_its_target_is_dropped():
    """The two self-relative offsets are the check: a misread entry drops out rather than
    naming the wrong section."""
    assert res.index_entries(build(bad_tag=True)) == []


def test_a_file_without_an_index_is_not_an_error():
    from tests.test_res import build as plain

    assert res.index_entries(plain()) == []


def test_expand_uses_the_name_where_there_is_one():
    members = dict(res.expand(build()))
    assert any(n.startswith("000_surf_bobblehead_texture") for n in members)
    # the tag infix survives, because the plugin screens members on it
    assert all("_surf_" in n or "_strg_" in n or "_indx_" in n for n in members)
