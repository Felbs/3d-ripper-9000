import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from gcrip import blend, serve


def test_catalog_file_lists_parents(tmp_path):
    blend.write_catalogs(tmp_path, {"GZLE01/res/Object/Link.arc", "GZLE01/res/Stage"})
    txt = (tmp_path / "blender_assets.cats.txt").read_text()
    lines = [ln for ln in txt.splitlines() if ln and not ln.startswith(("#", "VERSION"))]
    paths = [ln.split(":")[1] for ln in lines]
    assert paths == sorted(paths)
    assert "GZLE01" in paths and "GZLE01/res" in paths and "GZLE01/res/Object" in paths
    ids = [ln.split(":")[0] for ln in lines]
    assert len(set(ids)) == len(ids)
    assert blend.catalog_id("GZLE01/res") == blend.catalog_id("GZLE01/res")  # deterministic


def test_find_blender_explicit(tmp_path):
    fake = tmp_path / "blender.exe"
    fake.write_bytes(b"")
    assert blend.find_blender(str(fake)) == str(fake)


def test_serve_endpoints_guard_paths(tmp_path):
    (tmp_path / "report.html").write_text("<p>hi</p>")
    (tmp_path / "m.gltf").write_text("{}")
    handler = serve.make_handler(tmp_path, blender=None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        st = json.load(urllib.request.urlopen(base + "/status"))
        assert st["blender"] is None
        assert urllib.request.urlopen(base + "/report.html").read() == b"<p>hi</p>"
        for bad in ("../secret", "", "nothere.gltf"):
            try:
                urllib.request.urlopen(base + "/open?path=" + bad)
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        try:
            urllib.request.urlopen(base + "/open?path=m.gltf")
            raise AssertionError("expected 500 without blender")
        except urllib.error.HTTPError as e:
            assert e.code == 500
            assert "Blender not found" in json.load(e)["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_serve_no_store_and_game_in_status(tmp_path):
    (tmp_path / "report.html").write_text("<p>hi</p>")
    handler = serve.make_handler(tmp_path, blender=None, game="GTST01")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        r = urllib.request.urlopen(base + "/report.html")
        assert r.headers["Cache-Control"] == "no-store"
        st = json.load(urllib.request.urlopen(base + "/status"))
        assert st["game"] == "GTST01"
    finally:
        httpd.shutdown()


def test_report_lists_stages(tmp_path):
    from gcrip.rip import RipResult, write_report

    res = RipResult(game_id="GTST01", title="Test", out_dir=tmp_path)
    d = tmp_path / "stages" / "M_Test"
    d.mkdir(parents=True)
    (d / "M_Test.gltf").write_text("{}")
    (d / "M_Test_report.json").write_text(
        json.dumps(
            {
                "stage": "M_Test",
                "rooms": [0, 1],
                "room_models": 3,
                "placed": 42,
                "triangles": 1234,
                "unresolved": 1,
            }
        )
    )
    out = write_report(res)
    html_text = out.read_text(encoding="utf-8")
    assert "Levels" in html_text
    assert "stages/M_Test/M_Test.gltf" in html_text
    assert "42 actors" in html_text
    assert 'GCRIP_GAME="GTST01"' in html_text or "GCRIP_GAME=" in html_text


def test_serve_root_redirects_cache_busted(tmp_path):
    (tmp_path / "report.html").write_text("<p>hi</p>")
    handler = serve.make_handler(tmp_path, blender=None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        r = conn.getresponse()
        assert r.status == 302
        assert r.getheader("Location").startswith("/report.html?fresh=")
    finally:
        httpd.shutdown()
