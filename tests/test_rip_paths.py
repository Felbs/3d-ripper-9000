"""Manifest path -> output path.  Member names are not filenames."""

from pathlib import Path

from gcrip.rip import _rel_out_path, _safe_component


def test_a_legal_path_is_untouched():
    """The fix must not churn the output paths of everything that already works."""
    assert _rel_out_path("files/models/normal/path.bmd") == Path("models/normal/path.bmd")


def test_an_embedded_absolute_path_does_not_escape_the_output_directory():
    """EA's cinema assets keep the artist's own absolute path inside the member path, so this
    used to build `D:/3d dump/.../d:/DJV2/...` and Windows rejected the lot - 350 models on Def
    Jam Fight For NY, all `OSError: [WinError 123]`."""
    got = _rel_out_path("files/assets/cinema/ta.big/d:/DJV2/assets/textures/final/gc/ta.gsh")
    assert ":" not in str(got)
    assert not Path(got).is_absolute()
    assert got.parts[0] == "assets"


def test_control_bytes_in_a_name_are_replaced():
    """NHL 2004 has member names with raw control bytes - 1,521 models."""
    got = _rel_out_path("files/FE/bg.viv/\u00f9\x93X\x16ANA_BG_00_tex.bin")
    assert not any(ord(c) < 32 for c in str(got))


def test_windows_device_names_are_escaped():
    assert _safe_component("CON.bin") != "CON.bin"
    assert _safe_component("com4") != "com4"
    assert _safe_component("console.bin") == "console.bin"


def test_a_trailing_dot_or_space_is_dropped():
    """Windows silently drops them, so two members could collide on one output file."""
    assert _safe_component("name.") == "name"
    assert _safe_component("name ") == "name"


def test_a_component_that_sanitises_to_nothing_still_has_a_name():
    assert _safe_component("...") == "_"
    assert _rel_out_path("files/") == Path("_")
