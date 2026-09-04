"""The library browser generator (gcrip.library)."""

import json
import re

from gcrip import library


def _write(root, gid, models, batch_extra=None):
    (root / gid).mkdir(parents=True)
    (root / gid / "report.html").write_text("<html></html>", encoding="utf-8")
    for m in models:
        if m.get("thumb"):
            t = root / gid / m["thumb"]
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(b"\x89PNG\r\n")
    (root / gid / "rip_results.json").write_text(
        json.dumps({"game_id": gid, "title": "T", "models": models}), encoding="utf-8"
    )
    row = {"game_id": gid, "title": f"Game {gid}", "file": f"{gid}.iso"}
    row.update(batch_extra or {})
    return row


def _catalog(root):
    html = (root / "library.html").read_text(encoding="utf-8")
    games = json.loads(re.search(r"GAMES=(\[.*?\]), STATS=", html, re.S).group(1))
    stats = json.loads(re.search(r"STATS=(\{.*?\});", html, re.S).group(1))
    return html, games, stats


def test_build_index_bakes_the_catalog(tmp_path):
    rows = [
        _write(
            tmp_path,
            "AAAA",
            [
                {
                    "path": "a/big.gma",
                    "out_rel": "a/big.gltf",
                    "triangles": 500,
                    "textures": 2,
                    "thumb": "a/big_thumb.png",
                    "skinned": True,
                },
                {
                    "path": "a/small.gma",
                    "out_rel": "a/small.gltf",
                    "triangles": 10,
                    "textures": 0,
                    "thumb": "a/small_thumb.png",
                },
                {
                    "path": "a/dup.gma",
                    "triangles": 99,
                    "thumb": "a/dup_thumb.png",
                    "duplicate_of": "x",
                },
            ],
            {"exported": 2, "triangles": 510, "textures": 2, "clips": 3},
        ),
        _write(tmp_path, "BBBB", [], {"exported": 0, "triangles": 0}),
    ]
    with (tmp_path / "batch_results.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    dest = library.build_index(tmp_path)
    assert dest.name == "library.html"
    html, games, stats = _catalog(tmp_path)

    assert stats == {"games": 2, "with_geo": 1, "models": 2, "tris": 510, "tex": 2}
    a = next(g for g in games if g["id"] == "AAAA")
    # sorted most-triangles first, the geometry game leads
    assert games[0]["id"] == "AAAA"
    assert a["hero"] == "AAAA/a/big_thumb.png" and a["skinned"] and a["clips"] == 3
    assert a["report"] == "AAAA/report.html"
    # the duplicate is dropped; the two real models are the top strip, biggest first
    assert [m["n"] for m in a["top"]] == ["big.gma", "small.gma"]
    assert a["top"][0]["g"] == "AAAA/a/big.gltf"  # .gltf path for the /glb 3D viewer
    b = next(g for g in games if g["id"] == "BBBB")
    assert b["hero"] is None and b["top"] == [] and b["tris"] == 0
    # the page is self-contained and carries the viewer + refresh wiring
    assert "model-viewer" in html and "/glb?path=" in html
    assert 'id="refresh"' in html and "/catalog.json" in html

    # build_catalog returns the same data the page bakes, for the served /catalog.json refresh
    cat = library.build_catalog(tmp_path)
    assert cat["stats"] == stats and [g["id"] for g in cat["games"]] == [g["id"] for g in games]


def test_missing_hero_thumb_is_skipped(tmp_path):
    # a model whose thumb file is absent must not become the hero (no broken images)
    row = _write(
        tmp_path,
        "CCCC",
        [{"path": "m.gma", "out_rel": "m.gltf", "triangles": 5, "thumb": "gone_thumb.png"}],
    )
    (tmp_path / "CCCC" / "gone_thumb.png").unlink()
    with (tmp_path / "batch_results.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({**row, "exported": 1, "triangles": 5}) + "\n")
    library.build_index(tmp_path)
    _, games, _ = _catalog(tmp_path)
    assert games[0]["hero"] is None  # thumb was missing
    assert games[0]["top"][0]["n"] == "m.gma"  # still listed in the strip
