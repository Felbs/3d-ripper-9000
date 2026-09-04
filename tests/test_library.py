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

    assert stats["games"] == 2 and stats["with_geo"] == 1 and stats["models"] == 2
    assert stats["tris"] == 510 and stats["tex"] == 2
    assert stats["rigged"] == 1  # big.gma is skinned
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

    # nmodels counts every thumbnailed model (for the "Show all" button); game_models lists them
    assert a["nmodels"] == 2 and 'id="refresh"' in html and "/models.json" in html
    gm = library.game_models(tmp_path, "AAAA")
    assert gm["total"] == 2 and [m["n"] for m in gm["models"]] == ["big.gma", "small.gma"]
    assert gm["models"][0]["g"] == "AAAA/a/big.gltf"
    assert library.game_models(tmp_path, "NONE")["models"] == []


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


def _mini_dump(tmp_path):
    rows = [
        _write(
            tmp_path,
            "WIND",
            [
                {
                    "path": "a/link.bdl",
                    "out_rel": "a/link.gltf",
                    "triangles": 900,
                    "textures": 3,
                    "thumb": "a/link_thumb.png",
                    "skinned": True,
                },
                {
                    "path": "a/boat.bdl",
                    "out_rel": "a/boat.gltf",
                    "triangles": 300,
                    "textures": 1,
                    "thumb": "a/boat_thumb.png",
                },
            ],
            {"exported": 2, "triangles": 1200, "textures": 4, "clips": 5},
        ),
        _write(
            tmp_path,
            "PONG",
            [
                {
                    "path": "b/ball.bdl",
                    "out_rel": "b/ball.gltf",
                    "triangles": 40,
                    "textures": 0,
                    "thumb": "b/ball_thumb.png",
                }
            ],
            {"exported": 1, "triangles": 40},
        ),
        _write(tmp_path, "NADA", [], {"exported": 0, "triangles": 0}),
    ]
    with (tmp_path / "batch_results.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return tmp_path


def test_query_search_and_list(tmp_path):
    from gcrip import library_query as lq

    root = _mini_dump(tmp_path)
    st = lq.stats(root)
    assert (st["games"], st["with_geo"], st["models"], st["tris"], st["tex"]) == (3, 2, 3, 1240, 4)
    # search by id/title and filters
    assert [g["id"] for g in lq.search_games(root, "wind")] == ["WIND"]
    assert [g["id"] for g in lq.search_games(root, "", skinned=True)] == ["WIND"]
    assert [g["id"] for g in lq.search_games(root, "", has_models=True, sort="models")] == [
        "WIND",
        "PONG",
    ]
    assert [g["id"] for g in lq.search_games(root, "", sort="title")] == ["NADA", "PONG", "WIND"]
    # list_models resolves by id or title, paginates, and carries the glTF path
    lm = lq.list_models(root, "The WIND game".lower().replace("the ", "") and "WIND")
    assert lm["total"] == 2 and lm["models"][0]["g"] == "WIND/a/link.gltf"
    page = lq.list_models(root, "WIND", limit=1, offset=1)
    assert page["returned"] == 1 and page["models"][0]["n"] == "boat.bdl"
    assert "error" in lq.list_models(root, "ZZZ")


def test_query_pack_glb_guards(tmp_path):
    from gcrip import library_query as lq

    root = _mini_dump(tmp_path)
    # a path outside the root or a non-.gltf is refused; a missing file too
    assert "error" in lq.pack_glb(root, "../secret.gltf")
    assert "error" in lq.pack_glb(root, "WIND/a/link.png")
    assert "error" in lq.pack_glb(root, "WIND/a/nope.gltf")


def test_model_tags_classifier():
    from gcrip.model_tags import KINDS, classify, tags

    assert classify("gun_pistol") == "weapon"
    assert classify("steelsword.gs") == "weapon"  # compound names hit via substrings
    assert classify("level3_terrain.bsp") == "level"
    assert classify("hud_icon_health") == "ui"
    assert classify("racecar_01") == "vehicle"
    assert classify("particle_flame_fx") == "effect"
    assert classify("coin_gold") == "prop"
    # precision: short ambiguous fragments must not fire inside other words
    assert classify("command_center") != "weapon"
    # the rig is a character signal when the name says nothing
    assert classify("block0123.bin", skinned=True) == "character"
    assert classify("block0123.bin") == "unknown"
    # a skinned mesh with a weak level/prop name hit is still a character
    assert classify("stage_actor_body", skinned=True) == "character"
    t = tags("boss_dragon", skinned=True, animated=True)
    assert t == {"kind": "character", "rigged": True, "animated": True}
    assert t["kind"] in KINDS


def test_query_search_models(tmp_path):
    from gcrip import library_query as lq

    root = _mini_dump(tmp_path)
    # model cards carry the classification facets
    lm = lq.list_models(root, "WIND")
    assert {m["n"]: m["k"] for m in lm["models"]} == {
        "link.bdl": "character",
        "boat.bdl": "vehicle",
    }
    assert lm["models"][0]["r"] is True  # link is rigged
    # search across every game, tagged with the owning game
    r = lq.search_models(root, "boat")
    assert r["total"] == 1 and r["models"][0]["gid"] == "WIND" and r["models"][0]["k"] == "vehicle"
    # kind and rig filters
    assert lq.search_models(root, "", kind="vehicle")["total"] == 1
    assert lq.search_models(root, "", rigged=True)["models"][0]["n"] == "link.bdl"
    assert lq.search_models(root, "", kind="nonsense").get("error")
    # a game-title query returns that game's models
    assert lq.search_models(root, "game wind")["total"] == 2
    # per-game kind counts reach the catalog for the page's category chips
    g = lq.find_game(root, "WIND")
    assert g["kinds"] == {"character": 1, "vehicle": 1} and g["rigged"] == 1
