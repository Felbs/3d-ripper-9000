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
