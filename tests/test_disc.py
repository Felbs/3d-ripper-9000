import json

import pytest

from gcrip.classify import classify
from gcrip.cli import main
from gcrip.disc.fst import APPLOADER_OFFSET, parse_fst, parse_header
from gcrip.disc.image import DiscImage, UnsupportedImageError
from gcrip.formats import rarc
from gcrip.manifest import build_manifest

from .builders import build_disc, build_rarc, yay0_literal, yaz0_literal

BMD = b"J3D2bmd3" + b"\x00" * 56
BDL = b"J3D2bdl4" + b"\x00" * 56
BCK = b"J3D1bck1" + b"\x00" * 56
TPL = b"\x00\x20\xaf\x30" + b"\x00" * 60
AST = b"STRM" + b"\x00" * 60


@pytest.fixture
def disc_bytes():
    inner = build_rarc(
        {
            "model.bmd": BMD,
            "anim/walk.bck": BCK,
            "tex/skin.tpl": TPL,
            "nested.szp": yay0_literal(BDL),
        },
        root="kuri",
    )
    files = {
        "opening.bnr": b"BNR1" + b"\x00" * 100,
        "audio/bgm.ast": AST,
        "audio/se.dsp": b"\x00" * 96,
        "map/stage1.szs": yaz0_literal(inner),
        "map/stage1.arc": inner,
        "obj/mario.bmd": BMD,
        "obj/sub/thing.bin": b"\x01\x02\x03",
        "readme.txt": b"hello",
        "テスト/jp.bmd": BMD,  # Shift-JIS directory name
    }
    return build_disc(files, dirs=["empty"])


@pytest.fixture
def disc_path(tmp_path, disc_bytes):
    p = tmp_path / "test.iso"
    p.write_bytes(disc_bytes)
    return p


def test_header(disc_bytes):
    hdr = parse_header(disc_bytes[: APPLOADER_OFFSET + 0x20])
    assert hdr.game_id == "GTST01"
    assert hdr.title == "Test Disc"
    assert hdr.maker_code == "01"
    assert hdr.region == "NTSC-U"
    assert hdr.revision == 1
    assert hdr.fst_offset == 0x4000
    assert hdr.dol_offset == 0x3000
    assert hdr.apploader_date == "2001/01/01"


def test_fst_paths(disc_bytes):
    hdr = parse_header(disc_bytes[:0x440])
    entries = parse_fst(disc_bytes[hdr.fst_offset : hdr.fst_offset + hdr.fst_size])
    paths = {e.path: e for e in entries}
    assert "audio/bgm.ast" in paths and not paths["audio/bgm.ast"].is_dir
    assert paths["audio"].is_dir
    assert paths["obj/sub/thing.bin"].size == 3
    assert "empty" in paths and paths["empty"].is_dir
    assert "テスト/jp.bmd" in paths
    off = paths["readme.txt"].offset
    assert disc_bytes[off : off + 5] == b"hello"


def test_image_rejects_non_gc(tmp_path):
    p = tmp_path / "bad.iso"
    p.write_bytes(b"RVZ\x01" + b"\x00" * 100)
    with pytest.raises(UnsupportedImageError, match="RVZ"):
        DiscImage(p)
    p.write_bytes(b"\x00" * 100)
    with pytest.raises(UnsupportedImageError):
        DiscImage(p)


def test_rarc_parse():
    arc = rarc.parse(
        build_rarc({"a.bin": b"AAAA", "sub/b.bin": b"BB", "sub/deep/c.bin": b"C"}, root="r")
    )
    assert arc.root_name == "r"
    by_path = {f.path: f for f in arc.files}
    assert set(by_path) == {"r/a.bin", "r/sub/b.bin", "r/sub/deep/c.bin"}
    assert by_path["r/sub/b.bin"].size == 2
    assert {d.path for d in arc.dirs} == {"r", "r/sub", "r/sub/deep"}


def test_manifest_walks_archives(disc_path):
    with DiscImage(disc_path) as img:
        m = build_manifest(img)
    by_path = {f.path: f for f in m.files}
    # system files
    assert by_path["sys/main.dol"].size == 0x140
    assert by_path["sys/fst.bin"].disc_offset == 0x4000
    # top level classification
    assert by_path["files/obj/mario.bmd"].fmt == "BMD"
    assert by_path["files/audio/bgm.ast"].fmt == "AST"
    assert by_path["files/audio/se.dsp"].fmt == "DSP"  # by extension
    assert by_path["files/opening.bnr"].kind == "banner"
    # compressed archive: entry describes payload, notes compression
    szs = by_path["files/map/stage1.szs"]
    assert szs.compression == "Yaz0" and szs.fmt == "RARC"
    assert szs.sha1_decompressed == by_path["files/map/stage1.arc"].sha1
    # nested files inside both archives
    assert by_path["files/map/stage1.szs/kuri/model.bmd"].fmt == "BMD"
    assert by_path["files/map/stage1.szs/kuri/anim/walk.bck"].kind == "animation"
    assert by_path["files/map/stage1.szs/kuri/tex/skin.tpl"].fmt == "TPL"
    nested = by_path["files/map/stage1.szs/kuri/nested.szp"]
    assert nested.compression == "Yay0" and nested.fmt == "BDL"
    # disc_offset survives through an uncompressed archive but not a compressed one
    arc_model = by_path["files/map/stage1.arc/kuri/model.bmd"]
    assert arc_model.disc_offset is not None
    with DiscImage(disc_path) as img:
        assert img.read(arc_model.disc_offset, arc_model.size) == BMD
    assert by_path["files/map/stage1.szs/kuri/model.bmd"].disc_offset is None
    assert by_path["files/map/stage1.szs/kuri/model.bmd"].container == "files/map/stage1.szs"
    # same content -> same hash across containers
    assert arc_model.sha1 == by_path["files/obj/mario.bmd"].sha1
    assert "files/empty" in m.dirs
    assert not m.errors


def test_cli_manifest_and_tree(disc_path, tmp_path, capsys):
    out = tmp_path / "m.json"
    assert main(["manifest", str(disc_path), "-o", str(out), "-q"]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["game"]["id"] == "GTST01"
    assert d["stats"]["by_fmt"]["BMD"] >= 3
    assert main(["tree", str(out), "--ascii"]) == 0
    text = capsys.readouterr().out
    assert "stage1.szs/  [RARC<Yaz0>]" in text
    assert "kuri/" in text
    assert "mario.bmd  [BMD]" in text


def test_cli_extract(disc_path, tmp_path):
    out = tmp_path / "x"
    assert main(["extract", str(disc_path), str(out), "-q"]) == 0
    assert (out / "files/map/stage1.szs/kuri/model.bmd").read_bytes() == BMD
    assert (out / "files/map/stage1.szs/kuri/nested.szp").read_bytes() == BDL  # decompressed
    assert (out / "sys/boot.bin").stat().st_size == 0x440


@pytest.mark.parametrize(
    "name,head,expected",
    [
        ("x.bmd", BMD, ("model", "BMD")),
        ("x.bin", BDL, ("model", "BDL")),
        ("x.bin", TPL, ("texture", "TPL")),
        (
            "x.bti",
            b"\x0e\x00\x00\x40\x00\x40" + b"\x00" * 22 + b"\x00\x00\x00\x20" + b"\x00" * 32,
            ("texture", "BTI"),
        ),
        ("x.szs", b"Yaz0" + b"\x00" * 12, ("compressed", "Yaz0")),
        ("x.arc", b"RARC" + b"\x00" * 12, ("archive", "RARC")),
        ("x.thp", b"THP\x00", ("video", "THP")),
        ("x.rel", b"\x00" * 16, ("executable", "REL")),
        ("x.whatever", b"\x00" * 16, ("unknown", "")),
        ("common.jpc", b"JPAC1-00" + b"\x00" * 8, ("particle", "JPC")),
        ("tale.stb", b"STB\x00\xfe\xff\x00\x03", ("cutscene", "STB")),
        ("room.dzr", b"\x00\x00\x00\x0bSCLS", ("stagedata", "DZR")),
        ("COPYDATE", b"03/02/19 11:43:5", ("text", "TXT")),
        # Wind Waker event_list.dat must NOT trip the header-less DSP heuristic
        (
            "event_list.dat",
            bytes.fromhex("00000040 00000049 00003270 000000fb 00000000 00000000 00000000"),
            ("unknown", ""),
        ),
    ],
)
def test_classify(name, head, expected):
    c = classify(name, head, max(len(head), 0x100))
    assert (c.kind, c.fmt) == expected
