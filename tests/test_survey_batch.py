import json

from gcrip import batch, survey
from gcrip.formats import yaz0
from tests.builders import build_disc, build_rarc, yaz0_literal


def test_survey_disc_detects_j3d_inside_yaz0_rarc(tmp_path):
    inner = build_rarc(
        {"bdl/x.bdl": b"J3D2bdl4" + b"\0" * 64, "bck/a.bck": b"J3D1bck1" + b"\0" * 32}
    )
    files = {"res/Object/X.arc": yaz0_literal(inner), "sys/foo.bin": b"\0" * 32}
    iso = tmp_path / "g.iso"
    iso.write_bytes(build_disc(files, game_id=b"GTSTE0", title=b"Test Game"))
    assert yaz0.is_yaz0(files["res/Object/X.arc"])
    s = survey.survey_disc(iso)
    assert s.game_id == "GTSTE0" and s.engine == "J3D"
    assert s.j3d_models >= 1 and s.j3d_anims >= 1 and s.j3d_inside_archives == 1


def test_survey_writes_resumable_jsonl_and_md(tmp_path):
    folder = tmp_path / "roms"
    folder.mkdir()
    (folder / "a.iso").write_bytes(
        build_disc({"data.bin": b"\0" * 64}, game_id=b"GAAA69", title=b"A")
    )
    out = tmp_path / "out"
    done = survey.survey(folder, out, quiet=True)
    assert set(done) == {"a.iso"}
    assert (out / "survey.md").exists()
    assert len((out / "survey.jsonl").read_text().splitlines()) == 1
    (folder / "b.iso").write_bytes(build_disc({"x.tpl": b"\0" * 64}, game_id=b"GBBB01", title=b"B"))
    done = survey.survey(folder, out, quiet=True)
    assert set(done) == {"a.iso", "b.iso"}
    rows = [json.loads(x) for x in (out / "survey.jsonl").read_text().splitlines()]
    assert len(rows) == 2  # a.iso was not re-surveyed


def test_batch_matrix_handles_errors(tmp_path):
    rows = [
        {"file": "bad.iso", "error": "boom", "seconds": 1},
        {
            "file": "ok.iso",
            "game_id": "GOKE01",
            "title": "OK",
            "exported": 3,
            "duplicates": 1,
            "failed": 0,
            "triangles": 1234,
            "clips": 5,
            "animated_models": 1,
            "expressions": 0,
            "mixamo_rigs": 1,
            "textured_pct": 100.0,
            "textures": 2,
            "seconds": 9,
            "report": "out/GOKE01/report.html",
            "warnings": {"x": 2},
            "fail_examples": [],
        },
    ]
    p = batch.write_matrix(tmp_path, rows)
    txt = p.read_text(encoding="utf-8")
    assert "boom" in txt and "[OK](out/GOKE01/report.html)" in txt and "1,234" in txt
