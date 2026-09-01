"""Edge of Reality index.ind + .arc - The Sims, Shark Tale, Over the Hedge."""

import struct

from gcrip.formats import edge_ind
from gcrip.plugins import edge_arc as plugin


def table(entries):
    """u32 count, then the sorted hash array, then the (offset, size) pairs."""
    out = struct.pack(">I", len(entries))
    out += b"".join(struct.pack(">I", h) for h, _, _ in entries)
    out += b"".join(struct.pack(">2I", o, s) for _, o, s in entries)
    return out


def index(sections=None):
    sections = sections or [
        ("Levels", [(0x10, 0, 64), (0x20, 64, 32)]),
        ("AudioStreams", [(0x30, 0, 128)]),
    ]
    segs = []
    for name, entries in sections:
        segs.append(name.encode().ljust((len(name) // 4 + 1) * 4, b"\x00"))
        segs.append(table(entries))
    head = struct.pack(">I", len(segs))
    start = 4 + (len(segs) + 1) * 4
    offsets, at = [], start
    for s in segs:
        offsets.append(at)
        at += len(s)
    offsets.append(at)
    return head + b"".join(struct.pack(">I", o) for o in offsets) + b"".join(segs)


def test_the_offset_table_has_to_close_on_itself():
    """The first offset is the end of the table and the last is the file length - that pair
    is what says this is an index rather than a file that starts with plausible numbers."""
    data = index()
    assert edge_ind.is_index(data)
    bad = bytearray(data)
    struct.pack_into(">I", bad, 4, 999)
    assert not edge_ind.is_index(bytes(bad))
    short = data[:-1]
    assert not edge_ind.is_index(short)


def test_categories_come_out_named():
    got = edge_ind.categories(index())
    assert set(got) == {"Levels", "AudioStreams"}
    assert [e.offset for e in got["Levels"]] == [0, 64]
    assert [e.size for e in got["Levels"]] == [64, 32]


def test_a_table_is_a_sorted_hash_array_not_a_record_array():
    """4 + count * 12 measures the same either way, and read interleaved it gives three
    columns of plausible 32-bit numbers.  The sorted hashes are the only thing that tells
    them apart, so unsorted ones are refused."""
    entries = [(0x30, 0, 64), (0x10, 64, 32)]  # hashes out of order
    data = index([("Levels", entries)])
    assert edge_ind.categories(data) == {}


def test_the_archive_name_is_the_category_truncated_to_eight():
    assert edge_ind.stem_of("AudioStreams") == "audiostr"
    assert edge_ind.stem_of("QuickDatas") == "quickdat"
    assert edge_ind.stem_of("RleTextures") == "rletextu"
    assert edge_ind.stem_of("Models") == "models"


def test_fits_allows_a_padded_tail_but_not_a_wrong_archive():
    entries = [edge_ind.Entry(1, 0, 1_000_000)]
    assert edge_ind.fits(entries, 1_000_000)  # exact, as eleven of sixteen pairs are
    assert edge_ind.fits(entries, 1_064_000)  # padded tail, as the other five are
    assert not edge_ind.fits(entries, 400_000_000)  # a different archive entirely
    assert not edge_ind.fits(entries, 900_000)  # entries running past the end


def test_only_the_archives_these_discs_ship_are_claimed():
    head = b"\x00" * 64
    assert plugin.is_container("models.arc", head)
    assert plugin.is_container("datasets.arc", head)
    assert not plugin.is_container("something.arc", head)
    assert not plugin.is_container("models.bin", head)


def test_audio_and_video_archives_are_skipped():
    """Movies alone is 574 MB on Over the Hedge and none of it is geometry."""
    head = b"\x00" * 64
    for name in ("movies.arc", "audiostr.arc", "samples.arc"):
        assert not plugin.is_container(name, head)


def test_expand_with_names_members_by_category_and_hash():
    data = index()
    archive = bytes(96)
    got = plugin.expand_with(archive, "levels.arc", lambda n: data)
    assert [n for n, _ in got] == ["Levels/00000010.bin", "Levels/00000020.bin"]
    assert len(got[0][1]) == 64 and len(got[1][1]) == 32


def test_an_archive_the_index_does_not_account_for_is_declined():
    data = index()
    assert plugin.expand_with(bytes(5_000_000), "levels.arc", lambda n: data) == []


def test_a_missing_index_is_declined_rather_than_raising():
    assert plugin.expand_with(bytes(96), "levels.arc", lambda n: None) == []

    def boom(_name):
        raise OSError("disc read failed")

    assert plugin.expand_with(bytes(96), "levels.arc", boom) == []
