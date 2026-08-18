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
