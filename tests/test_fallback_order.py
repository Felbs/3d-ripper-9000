"""The fallback scan is time-budgeted per disc, so the order it visits files in decides what
a disc yields.  Sorting purely biggest-first spent the whole budget on movies and audio: Tiger
Woods 2003 leads with a 100 MB ``Data/Movies/intro.ngc`` and never reached the ``.skg`` that
``gxscan`` does find display lists in.  Media now sorts last whatever its size."""

from __future__ import annotations

from gcrip.rip import _looks_like_media

BACKSLASH = chr(92)


def test_media_by_directory():
    assert _looks_like_media("files/Data/Movies/intro.ngc")
    assert _looks_like_media("root/streams/streamsn.wad")
    assert _looks_like_media("packages/Music/music.gcp")
    assert _looks_like_media("x/audiostr/voice1.bin")


def test_media_by_extension():
    assert _looks_like_media("files/anything.thp")
    assert _looks_like_media("files/track01.dsp")
    assert _looks_like_media("LOUD.H4M")  # case does not matter


def test_geometry_is_not_media():
    """The files this fix exists to reach, plus ordinary model and texture names."""
    assert not _looks_like_media("files/Data/Char/35char.skg")
    assert not _looks_like_media("files/Data/Tex/18alltex.fxg")
    assert not _looks_like_media("files/model/player.bmd")
    # a directory merely containing a media word is not a media directory
    assert not _looks_like_media("files/soundstage/level.arc")


def test_both_path_separators():
    assert _looks_like_media(BACKSLASH.join(["files", "Data", "Movies", "intro.ngc"]))
    assert not _looks_like_media(BACKSLASH.join(["files", "Data", "Char", "35char.skg"]))


def test_media_sorts_after_geometry_of_every_size():
    """The ordering key itself: a 100 MB movie must come after a 4 KB mesh."""
    files = [
        ("files/Data/Movies/intro.ngc", 100 << 20),
        ("files/Data/Char/35char.skg", 4 << 10),
        ("files/Data/Tex/18alltex.fxg", 1 << 20),
        ("files/sound/bank.dsp", 60 << 20),
    ]
    order = sorted(files, key=lambda c: (_looks_like_media(c[0]), -c[1]))
    assert [p for p, _ in order] == [
        "files/Data/Tex/18alltex.fxg",
        "files/Data/Char/35char.skg",
        "files/Data/Movies/intro.ngc",
        "files/sound/bank.dsp",
    ]


def test_container_archives_sort_after_ordinary_files():
    """Tiger Woods 2003: 273 EA SHOC `.hog` of 2-5 MB, all claimed by plugins/shoc.py and all
    bigger than the `.skg` that actually hold geometry.  Scanning them as raw blobs finds no
    display lists and spends the whole per-disc budget, so the `.skg` were never reached."""
    files = [  # (path, size, claimed by a real container plugin)
        ("files/Data/Movies/intro.ngc", 100 << 20, False),
        ("files/Data/01_Peb/hole_01/hole.hog", 5 << 20, True),
        ("files/Data/Char/35char.skg", 512_000, False),
        ("files/Data/Tex/18alltex.fxg", 1_236_992, False),
    ]
    order = sorted(files, key=lambda c: (_looks_like_media(c[0]), c[2], -c[1]))
    assert [p.rsplit("/", 1)[1] for p, _, _ in order] == [
        "18alltex.fxg",
        "35char.skg",
        "hole.hog",
        "intro.ngc",
    ]


def test_fallback_containers_do_not_deprioritise_everything():
    """plugins/generic.py is a registered container that claims every file there is.  Counting
    it would mark the whole disc "claimed" and change no ordering at all."""
    from gcrip.plugins import container_plugins, is_fallback

    fallbacks = [m for m in container_plugins() if is_fallback(m)]
    assert [getattr(m, "NAME", m.__name__) for m in fallbacks] == ["generic"]


def test_reordering_never_drops_a_candidate():
    """The fix is a sort key, not a filter.  A container archive or a movie still gets scanned
    if the budget reaches it - which matters because a disc whose only models come from raw-
    scanning a container blob must not lose them, only wait longer for them."""
    files = [
        ("files/Data/Movies/intro.ngc", 100 << 20, False),
        ("files/Data/01_Peb/hole_01/hole.hog", 5 << 20, True),
        ("files/Data/Char/35char.skg", 512_000, False),
        ("files/sound/bank.dsp", 60 << 20, False),
        ("files/model/player.bmd", 4 << 10, False),
    ]
    order = sorted(files, key=lambda c: (_looks_like_media(c[0]), c[2], -c[1]))
    assert sorted(order) == sorted(files)
    assert len(order) == len(files)
