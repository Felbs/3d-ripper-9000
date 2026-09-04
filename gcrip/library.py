"""Library browser: one page over every ripped game.

``gcrip library "D:/3d dump/GameCube"`` writes ``library.html`` into the dump root and serves
the root so the page can preview any model in 3D (through the ``/glb`` endpoint that packs a
glTF into a self-contained ``.glb``) and open models in Blender - the same endpoints
:mod:`gcrip.serve` gives one game, applied across the whole library.

The generator reads only the small metadata JSONs (``batch_results.jsonl`` and each game's
``rip_results.json``), never a disc image, so it is safe to run while a rip is using the
drive.  With no server the page still works from ``file://`` - hero thumbnails and per-game
reports load by relative path; the 3D viewer and Blender buttons light up only when it is
served.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import time
import webbrowser
from pathlib import Path

from gcrip.model_tags import KINDS, classify

TOP_MODELS = 24  # inline model thumbnails baked per game
ALL_MODELS_CAP = 600  # most models the served /models.json returns for one game


def _model_card(root: Path, gid: str, m: dict, thumb: str, tris: int) -> dict:
    out_rel = m.get("out_rel")
    skinned = bool(m.get("skinned"))
    animated = bool(m.get("animations"))
    return {
        "n": (m.get("path") or out_rel or "model").split("/")[-1],
        "t": f"{gid}/{thumb}",
        "tris": tris,
        "tex": int(m.get("textures") or 0),
        "g": f"{gid}/{out_rel}" if out_rel and out_rel.endswith(".gltf") else None,
        "k": classify(m.get("path") or out_rel or "", skinned=skinned, animated=animated),
        "r": skinned,  # rigged
        "a": animated,
    }


def game_models(root: Path, gid: str) -> dict:
    """The full model list for one game (thumbnailed, non-duplicate), biggest first - the
    served ``/models.json?game=`` body behind the page's *Show all N models*."""
    try:
        rr = json.loads((root / gid / "rip_results.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"id": gid, "models": [], "total": 0}
    models = rr.get("models", []) if isinstance(rr, dict) else rr
    have = [
        (int(m.get("triangles") or 0), m, m.get("thumb"))
        for m in models
        if m.get("thumb") and int(m.get("triangles") or 0) > 0 and not m.get("duplicate_of") and not m.get("error")
    ]
    have.sort(key=lambda x: -x[0])
    cards = [_model_card(root, gid, m, thumb, tris) for tris, m, thumb in have[:ALL_MODELS_CAP]]
    return {"id": gid, "models": cards, "total": len(have)}


def _game_entry(root: Path, row: dict) -> dict | None:
    gid = row.get("game_id")
    if not gid:
        return None
    title = (row.get("title") or row.get("file") or gid).strip() or gid
    entry = {
        "id": gid,
        "title": title,
        "disc": row.get("file", ""),
        "models": int(row.get("exported") or 0),
        "tris": int(row.get("triangles") or 0),
        "textures": int(row.get("textures") or 0),
        "clips": int(row.get("clips") or 0),
        "skinned": False,
        "hero": None,
        "top": [],
        "report": f"{gid}/report.html" if (root / gid / "report.html").exists() else None,
    }
    try:
        rr = json.loads((root / gid / "rip_results.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a game with no results is still listed by its batch row
        return entry
    models = rr.get("models", []) if isinstance(rr, dict) else rr
    have = []
    kinds = dict.fromkeys(KINDS, 0)
    rigged = animated = 0
    for m in models:
        thumb, tris = m.get("thumb"), int(m.get("triangles") or 0)
        if not thumb or tris <= 0 or m.get("duplicate_of") or m.get("error"):
            continue
        if m.get("skinned"):
            entry["skinned"] = True
            rigged += 1
        if m.get("animations"):
            animated += 1
        kinds[classify(m.get("path") or m.get("out_rel") or "", skinned=bool(m.get("skinned")),
                       animated=bool(m.get("animations")))] += 1
        have.append((tris, m, thumb))
    have.sort(key=lambda x: -x[0])
    for tris, m, thumb in have:
        if entry["hero"] is None and (root / gid / thumb).exists():
            entry["hero"] = f"{gid}/{thumb}"
        if len(entry["top"]) < TOP_MODELS:
            entry["top"].append(_model_card(root, gid, m, thumb, tris))
    entry["nmodels"] = len(have)  # thumbnailed models available for "Show all"
    # per-game kind counts (only kinds that occur) drive the catalog's category filters
    entry["kinds"] = {k: n for k, n in kinds.items() if n}
    entry["rigged"] = rigged
    entry["animated"] = animated
    return entry


def build_catalog(root: Path) -> dict:
    """The `{games, stats}` catalog from the metadata JSONs - the served ``/catalog.json``
    body and the data baked into ``library.html``."""
    rows = []
    with (root / "batch_results.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    games = [g for g in (_game_entry(root, r) for r in rows) if g]
    games.sort(key=lambda g: -g["tris"])
    kind_totals = dict.fromkeys(KINDS, 0)
    for g in games:
        for k, n in g.get("kinds", {}).items():
            kind_totals[k] += n
    stats = {
        "games": len(games),
        "with_geo": sum(1 for g in games if g["tris"] > 0),
        "models": sum(g["models"] for g in games),
        "tris": sum(g["tris"] for g in games),
        "tex": sum(g["textures"] for g in games),
        "kinds": {k: n for k, n in kind_totals.items() if n},
        "rigged": sum(g.get("rigged", 0) for g in games),
    }
    return {"games": games, "stats": stats}


def build_index(root: Path) -> Path:
    """Write ``library.html`` into ``root`` from the metadata JSONs; return its path."""
    cat = build_catalog(root)
    out = _TEMPLATE.replace("__DATA__", json.dumps(cat["games"], separators=(",", ":"))).replace(
        "__STATS__", json.dumps(cat["stats"])
    )
    dest = root / "library.html"
    dest.write_text(out, encoding="utf-8")
    return dest


def serve_library(root: Path, *, port: int = 8765, blender: str | None = None, open_browser=True):
    from gcrip.blend import find_blender
    from gcrip.serve import make_handler

    root = Path(root).resolve()
    if not (root / "batch_results.jsonl").exists():
        raise SystemExit(f"{root} has no batch_results.jsonl - pass the dump root of a batch rip")
    build_index(root)
    exe = find_blender(blender)
    base = make_handler(root, exe, None)

    class LibraryHandler(base):  # type: ignore[valid-type,misc]
        def do_GET(self):  # noqa: N802 - redirect the root to the library, keep every endpoint
            path = self.path.split("?", 1)[0]
            if self.path == "/" or self.path.startswith("/?"):
                self.send_response(302)
                self.send_header("Location", f"/library.html?fresh={int(time.time() * 1000)}")
                self.end_headers()
                return None
            if path == "/models.json":
                import urllib.parse as _up

                gid = _up.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("game", [""])[0]
                if not gid or not (root / gid).is_dir():
                    body = b'{"models":[],"total":0}'
                else:
                    from gcrip import library_query as _lq

                    body = json.dumps(_lq.game_models_cached(root, gid)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return None
            if path in ("/flag", "/flags.json"):
                import urllib.parse as _up

                from gcrip import library_query as _lq

                if path == "/flag":
                    qs = _up.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                    one = lambda k, d="": qs.get(k, [d])[0]  # noqa: E731
                    flags = _lq.set_flag(
                        root,
                        one("key"),
                        one("on") == "1",
                        name=one("n"),
                        gid=one("gid"),
                        note=one("note"),
                    )
                else:
                    flags = _lq.read_flags(root)
                body = json.dumps(flags).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return None
            if path == "/search_models.json":
                import urllib.parse as _up

                from gcrip import library_query as _lq

                qs = _up.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                one = lambda k, d=None: qs.get(k, [d])[0]  # noqa: E731
                body = json.dumps(
                    _lq.search_models(
                        root,
                        one("q", "") or "",
                        kind=one("kind"),
                        rigged=True if one("rigged") == "1" else None,
                        animated=True if one("animated") == "1" else None,
                        game=one("game"),
                        min_triangles=int(one("min_tris", "0") or 0),
                        limit=min(2000, int(one("limit", "600") or 600)),
                    )
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return None
            if path == "/catalog.json":
                # served from the mtime cache: instant unless batch_results.jsonl changed,
                # and a changed library rebuilds once behind a lock - repeated Refresh
                # clicks can no longer stack full re-scans against a mid-rip drive
                from gcrip import library_query as _lq

                body = json.dumps(_lq.catalog(root)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return None
            return super().do_GET()

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), LibraryHandler)
    url = f"http://127.0.0.1:{port}/library.html"
    print(f"serving {root}\n  {url}\n  Blender: {exe or 'NOT FOUND (pass --blender)'}\nCtrl+C to stop")
    if open_browser:
        webbrowser.open(f"{url}?fresh={int(time.time() * 1000)}")
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
    httpd.server_close()
    return 0


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GameCube 3D Model Library</title>
<style>
:root{--bg:#0e0e11;--panel:#17171c;--panel2:#1e1e25;--edge:#2a2a33;--txt:#e9e9ef;--dim:#9a9aa8;--accent:#7fb4ff;--good:#6bd08a}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
header{position:sticky;top:0;z-index:5;background:#0e0e11f2;backdrop-filter:blur(6px);border-bottom:1px solid var(--edge);padding:.9rem 1.1rem}
h1{margin:0;font-size:1.15rem}h1 small{color:var(--dim);font-weight:400;font-size:.8rem;margin-left:.5rem}
.stats{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0 .1rem}
.stat{background:var(--panel2);border:1px solid var(--edge);border-radius:7px;padding:.28rem .6rem;font-size:.78rem;color:var(--dim)}
.stat b{color:var(--txt)}
.controls{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-top:.6rem}
#q{flex:1;min-width:220px;padding:.5rem .7rem;border-radius:8px;border:1px solid var(--edge);background:var(--panel);color:var(--txt);font-size:.9rem}
select{padding:.5rem;border-radius:8px;border:1px solid var(--edge);background:var(--panel);color:var(--txt);font-size:.82rem}
.chip{cursor:pointer;user-select:none;padding:.38rem .6rem;border-radius:20px;border:1px solid var(--edge);background:var(--panel);color:var(--dim);font-size:.76rem}
.chip.on{background:#26324a;border-color:#3c5686;color:#cfe0ff}
.seg{display:inline-flex;border:1px solid var(--edge);border-radius:20px;overflow:hidden}
.seg .chip{border:0;border-radius:0;margin:0}
.cats{margin-top:.5rem;gap:.4rem}
.cats .chip{font-size:.75rem}
.cats .chip .c{color:var(--dim);font-weight:400;margin-left:.28rem}
.kb{display:inline-block;border-radius:4px;padding:.05rem .3rem;font-size:.6rem;margin-top:.2rem;background:#23232b;color:#b9b9c8}
.kb.character{background:#2b3a55;color:#cfe0ff}.kb.weapon{background:#4a2b2b;color:#ffd0d0}
.kb.vehicle{background:#3a3320;color:#ffe6a8}.kb.level{background:#243a2c;color:#bfe8cd}
.kb.prop{background:#3a2b45;color:#e6cff5}.kb.ui{background:#2a2a33;color:#b9b9c8}
.kb.effect{background:#183a3f;color:#b8ecf2}.rg{color:var(--good)}
.fl{float:right;cursor:pointer;opacity:.35;font-size:.8rem;line-height:1}
.fl:hover{opacity:.9}.fl.on{opacity:1}
.mcard.flagged{border-color:#a05050;background:#221a1a}
.acts{display:flex;gap:.45rem;margin-top:.28rem;font-size:.64rem;align-items:center}
.acts .fl{float:none;opacity:.75;font-size:.64rem}
.acts .fl.on{color:#ff9d9d;opacity:1}
.acts .act{cursor:pointer;color:var(--dim)}
.acts .act:hover,.acts .fl:hover{color:var(--accent);opacity:1}
.dash{grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:.8rem}
.panel{background:var(--panel);border:1px solid var(--edge);border-radius:11px;padding:.8rem .9rem}
.panel h3{margin:.1rem 0 .6rem;font-size:.88rem;color:var(--txt)}
.hbar{display:flex;align-items:center;gap:.5rem;margin:.22rem 0;font-size:.72rem;color:var(--dim)}
.hbar .lbl{width:11em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right;cursor:pointer}
.hbar .lbl:hover{color:var(--accent)}
.hbar .bar{height:.72rem;border-radius:4px;background:linear-gradient(90deg,#3c5686,#7fb4ff);min-width:2px}
.hbar .val{color:var(--txt)}
.bignum{font-size:1.6rem;font-weight:700;color:var(--txt)}
.bignum small{font-size:.7rem;font-weight:400;color:var(--dim);display:block}
.numgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.7rem}
#mpie svg{max-width:100%;height:auto}
main{padding:1rem 1.1rem 4rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.8rem}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:11px;overflow:hidden;cursor:pointer;transition:border-color .12s,transform .12s}
.card:hover{border-color:#3c4a6a;transform:translateY(-2px)}
.hero,.noimg{width:100%;aspect-ratio:16/10;display:block}
.hero{object-fit:contain;background:repeating-conic-gradient(#202027 0 25%,#17171c 0 50%) 0 0/18px 18px}
.noimg{display:flex;align-items:center;justify-content:center;color:#4d4d59;font-size:.8rem;background:#141418}
.body{padding:.55rem .65rem}
.title{font-weight:600;font-size:.9rem;line-height:1.2;margin-bottom:.25rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta{display:flex;flex-wrap:wrap;gap:.3rem;font-size:.72rem;color:var(--dim)}
.badge{background:var(--panel2);border-radius:5px;padding:.12rem .38rem}.badge.g{color:var(--good)}.icons{margin-left:auto}
.expand{grid-column:1/-1;background:var(--panel2);border:1px solid var(--edge);border-radius:11px;padding:.7rem .8rem;margin:-.2rem 0 .3rem}
.expand h3{margin:.1rem 0 .5rem;font-size:.86rem}.expand h3 a{color:var(--accent);text-decoration:none;font-size:.78rem;font-weight:400;margin-left:.6rem}
.mstrip{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:.5rem}
.mcard{background:var(--panel);border:1px solid var(--edge);border-radius:8px;padding:.3rem;font-size:.66rem;color:var(--dim);cursor:pointer}
.mcard.v:hover{border-color:var(--accent)}
.mcard img{width:100%;aspect-ratio:1;object-fit:contain;background:repeating-conic-gradient(#202027 0 25%,#17171c 0 50%) 0 0/12px 12px;border-radius:5px}
.mcard .mn{margin-top:.25rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt)}
.empty{color:var(--dim);padding:2rem;text-align:center}
footer{color:#55555f;font-size:.72rem;padding:1.5rem 1.1rem;border-top:1px solid var(--edge)}
#modal{position:fixed;inset:0;background:#000000d8;z-index:20;display:none;flex-direction:column}
#modal.on{display:flex}
#modal .bar{padding:.6rem 1rem;color:var(--txt);display:flex;gap:1rem;align-items:center;border-bottom:1px solid var(--edge)}
#modal .bar b{font-size:.95rem}#modal .bar a{color:var(--accent);text-decoration:none;font-size:.82rem}
#modal .x{margin-left:auto;cursor:pointer;font-size:1.3rem;color:var(--dim)}
#mv{flex:1;width:100%;background:#0b0b0e}
</style></head><body>
<header>
<h1>GameCube 3D Model Library <small id="sub"></small></h1>
<div class="stats" id="statbar"></div>
<div class="controls">
  <span class="seg"><span class="chip on" id="modeGames" data-mode="games">Games</span><span class="chip" id="modeModels" data-mode="models">Models</span><span class="chip" id="modeStats" data-mode="stats">📊 Stats</span></span>
  <input id="q" placeholder="Search games…  (title or disc filename)" autocomplete="off">
  <select id="sort">
    <option value="tris">Sort: most triangles</option><option value="models">Sort: most models</option>
    <option value="title">Sort: title A–Z</option><option value="tex">Sort: most textures</option>
  </select>
  <span class="chip" data-f="geo">Has models</span><span class="chip" data-f="tex">Textured</span>
  <span class="chip" data-f="skin">Skinned</span><span class="chip" data-f="anim">Animated</span>
  <span class="chip" id="refresh" title="Rescan the dump for newly ripped games">↻ Refresh</span>
</div>
<div class="controls cats" id="cats"></div></header>
<main><div class="grid" id="grid"></div><div class="empty" id="empty" hidden>No games match.</div></main>
<footer id="foot"></footer>
<div id="modal"><div class="bar"><b id="mvname"></b><a id="mvdl" href="#" download>Download .glb</a><span id="mvblend" class="chip" style="cursor:pointer">🟦 Open in Blender</span><span id="mvflag" class="chip" style="cursor:pointer">🚩 Flag as glitchy</span><span class="x" onclick="closeMV()">×</span></div><div id="mv"></div></div>
<script>
let GAMES=__DATA__, STATS=__STATS__;
const served=location.protocol==="http:"||location.protocol==="https:";
const fmt=n=>n>=1e6?(n/1e6).toFixed(1)+"M":n>=1e3?(n/1e3).toFixed(0)+"k":(""+n);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function drawStats(){document.getElementById("sub").textContent=`${STATS.with_geo} of ${STATS.games} discs with geometry`;
document.getElementById("statbar").innerHTML=[["Games",STATS.games],["With geometry",STATS.with_geo],["Models",fmt(STATS.models)],["Triangles",fmt(STATS.tris)],["Textures",fmt(STATS.tex)]].map(([k,v])=>`<span class="stat">${k} <b>${v}</b></span>`).join("");}
let FLAGS={};  // model key (gltf or thumb path) -> flag entry, mirrored from /flags.json
const mkey=m=>m.g||m.t;
drawStats();
const refresh=document.getElementById("refresh");
if(served){refresh.onclick=async()=>{refresh.textContent="↻ …";try{const r=await fetch("/catalog.json",{cache:"no-store"});const c=await r.json();GAMES=c.games;STATS=c.stats;modelCacheKey="\x00";drawStats();drawCats();render();}catch(e){alert("Refresh failed: "+e);}refresh.textContent="↻ Refresh";};}
else refresh.style.display="none";
document.getElementById("foot").innerHTML=served?"Served locally — click any model thumbnail to preview it in 3D, or open a game's full report. Nothing is uploaded.":"Opened from disk — click a game to preview its top models, or open its full report. For live 3D preview, run <code>gcrip library</code> to serve the folder.";
const grid=document.getElementById("grid"),empty=document.getElementById("empty"),q=document.getElementById("q"),sortSel=document.getElementById("sort");
const filters={geo:false,tex:false,skin:false,anim:false};let mvLoaded=false,mode="games";
const cats=new Set();  // active category kinds (and the pseudo-kind "rigged")
const CATS=[["character","Characters"],["weapon","Weapons"],["vehicle","Vehicles"],["level","Levels"],["prop","Props"],["ui","UI"],["effect","FX"]];
function drawCats(){
  const K=STATS.kinds||{};
  let h=CATS.filter(([k])=>K[k]).map(([k,label])=>`<span class="chip cat" data-k="${k}">${label}<span class=c>${fmt(K[k])}</span></span>`).join("");
  if(STATS.rigged)h+=`<span class="chip cat" data-k="rigged" title="characters with a skeleton/rig">⤳ Rigged<span class=c>${fmt(STATS.rigged)}</span></span>`;
  const nf=Object.keys(FLAGS).length;
  if(nf)h+=`<span class="chip cat" data-k="flagged" title="models you flagged as glitchy">🚩 Flagged<span class=c>${nf}</span></span>`;
  document.getElementById("cats").innerHTML=h;
  document.querySelectorAll("#cats .cat").forEach(c=>{if(cats.has(c.dataset.k))c.classList.add("on");c.onclick=()=>{const k=c.dataset.k;cats.has(k)?cats.delete(k):cats.add(k);c.classList.toggle("on");render();};});
}
drawCats();
document.querySelectorAll(".chip[data-f]").forEach(c=>c.onclick=()=>{filters[c.dataset.f]=!filters[c.dataset.f];c.classList.toggle("on");render();});
const modeG=document.getElementById("modeGames"),modeM=document.getElementById("modeModels"),modeS=document.getElementById("modeStats");
function setMode(m){mode=m;if(gameFromHash())history.replaceState(null,"",location.pathname+location.search);modeG.classList.toggle("on",m==="games");modeM.classList.toggle("on",m==="models");modeS.classList.toggle("on",m==="stats");
  q.placeholder=m==="models"?"Search models…  (character / weapon / part names across every game)":"Search games…  (title or disc filename)";
  render();}
modeG.onclick=()=>setMode("games");modeM.onclick=()=>setMode("models");modeS.onclick=()=>setMode("stats");
q.oninput=render;sortSel.onchange=render;
function card(g){
  const icons=(g.skinned?"⤳":"")+(g.clips>0?" ▶":"");
  const hero=g.hero?`<img class=hero loading=lazy src="${g.hero}" alt="">`:`<div class=noimg>no preview</div>`;
  const b=[`<span class="badge${g.tris>0?" g":""}">${fmt(g.models)} mdl</span>`,g.tris>0?`<span class="badge">△ ${fmt(g.tris)}</span>`:"",g.textures>0?`<span class="badge">▦ ${fmt(g.textures)}</span>`:"",`<span class="icons">${icons}</span>`].join("");
  return `<div class="card" data-id="${g.id}">${hero}<div class="body"><div class="title" title="${esc(g.title)}">${esc(g.title)}</div><div class="meta">${b}</div></div></div>`;
}
function kbadge(m){const k=m.k&&m.k!=="unknown"?`<span class="kb ${m.k}">${m.k}</span>`:"";return k+(m.r?`<span class="kb rg" title=rigged>⤳</span>`:"")+(m.a?`<span class="kb" title=animated>▶</span>`:"");}
function flbtn(m){if(!served)return "";const on=mkey(m) in FLAGS;return `<span class="fl${on?" on":""}" title="${on?"flagged for review — click to clear":"flag as glitchy for review"}">${on?"🚩 flagged":"🚩 flag"}</span>`;}
function actrow(m){if(!served)return "";const b=m.g?`<span class=act data-act=open title="open in Blender">🟦 Blender</span><span class=act data-act=reveal title="show file in Explorer">📂</span>`:"";return `<div class=acts>${flbtn(m)}${b}</div>`;}
async function doAct(act,m){try{await fetch("/"+act+"?path="+encodeURIComponent(m.g),{cache:"no-store"});}catch(e){alert(act+" failed: "+e);}}
function mcard(gid,m,i){const on=mkey(m) in FLAGS;return `<div class="mcard${served&&m.g?" v":""}${on?" flagged":""}" data-id="${gid}" data-i="${i}"><img loading=lazy src="${m.t}" alt=""><div class=mn title="${esc(m.n)}">${esc(m.n)}</div>△ ${fmt(m.tris)}${m.tex?` · ▦${m.tex}`:""}<div>${kbadge(m)}</div>${actrow(m)}</div>`;}
function mcardG(m,i){/* model card in library-wide models mode, tagged with its game */return `<div class="mcard${served&&m.g?" v":""}" data-id="${m.gid}" data-i="${i}" data-flat="1"><img loading=lazy src="${m.t}" alt=""><div class=mn title="${esc(m.n)}">${esc(m.n)}</div><div class="mn gjump" data-g="${m.gid}" title="open ${esc(m.title||"")}" style="color:var(--accent);cursor:pointer">${esc(m.title||"")}</div>△ ${fmt(m.tris)}${m.tex?` · ▦${m.tex}`:""}<div>${kbadge(m)}</div>${actrow(m)}</div>`;}
const fullModels={};  // gid -> loaded full model list, shared by the game pages
if(served)fetch("/flags.json",{cache:"no-store"}).then(r=>r.json()).then(f=>{FLAGS=f;drawCats();render();}).catch(()=>{});
async function toggleFlag(m,el){
  const key=mkey(m),on=!(key in FLAGS);
  let note="";
  if(on){note=prompt("What looks wrong? (optional note for the rip fixer)","glitchy")||"";if(note===null)return;}
  const p=new URLSearchParams({key,on:on?"1":"0",n:m.n||"",gid:m.gid||key.split("/")[0]});
  if(note&&note!=="glitchy")p.set("note",note);else if(note)p.set("note",note);
  try{const r=await fetch("/flag?"+p.toString(),{cache:"no-store"});FLAGS=await r.json();}catch(e){alert("flag failed: "+e);return;}
  drawCats();render();
}
const kindCats=()=>[...cats].filter(k=>k!=="rigged"&&k!=="flagged");
function modelKindOK(m){const kc=kindCats();if(cats.has("rigged")&&!m.r)return false;if(cats.has("flagged")&&!(mkey(m) in FLAGS))return false;if(kc.length&&!kc.includes(m.k))return false;return true;}
function gameHasFlag(g){for(const k of Object.keys(FLAGS))if(k.startsWith(g.id+"/"))return true;return false;}
function catGameOK(g){for(const k of cats){if(k==="rigged"){if(!(g.rigged>0))return false;}else if(k==="flagged"){if(!gameHasFlag(g))return false;}else if(!(g.kinds&&g.kinds[k]>0))return false;}return true;}
function gameFromHash(){const m=location.hash.match(/^#g=(.+)$/);return m?decodeURIComponent(m[1]):null;}
function render(){const gid=gameFromHash();if(gid)return renderGame(gid);if(mode==="models")return renderModels();if(mode==="stats")return renderStats();renderGames();}
addEventListener("hashchange",()=>{q.value="";render();});
async function renderGame(gid){
  const g=GAMES.find(x=>x.id===gid);
  if(!g){grid.innerHTML=`<div class=empty>No game ${esc(gid)} — <a href="#" onclick="location.hash=''">back to the library</a></div>`;empty.hidden=true;return;}
  q.placeholder=`Search the ${fmt(g.nmodels||g.models)} models in ${g.title}…`;
  let full=fullModels[g.id];
  if(!full&&served&&(g.nmodels||0)>g.top.length){
    grid.innerHTML=`<div class=empty>loading ${fmt(g.nmodels)} models…</div>`;
    try{const r=await fetch("/models.json?game="+encodeURIComponent(g.id),{cache:"no-store"});full=fullModels[g.id]=(await r.json()).models;}catch(e){full=null;}
    if(gameFromHash()!==gid)return;  // user navigated away while loading
  }
  const pool=full||g.top||[];
  const term=q.value.trim().toLowerCase();
  let list=pool.filter(m=>modelKindOK(m)&&(!term||m.n.toLowerCase().includes(term)));
  const k=sortSel.value;list.sort((a,b)=>k==="tex"?b.tex-a.tex:k==="title"?a.n.localeCompare(b.n):b.tris-a.tris);
  const badges=[`${fmt(g.models)} models`,g.tris>0?`△ ${fmt(g.tris)}`:"",g.textures>0?`▦ ${fmt(g.textures)}`:"",g.skinned?"⤳ rigged":"",g.clips>0?`▶ ${fmt(g.clips)} clips`:""].filter(Boolean).map(x=>`<span class=badge>${x}</span>`).join(" ");
  const report=g.report?`<a href="${g.report}" target="_blank" style="color:var(--accent)">Full report ↗</a>`:"";
  const note=(!served&&(g.nmodels||0)>pool.length)?` — top ${pool.length} only (serve with <code>gcrip library</code> for all)`:` — ${fmt(list.length)}${list.length!==pool.length?` of ${fmt(pool.length)}`:""} shown`;
  empty.hidden=true;
  grid.innerHTML=`<div class=expand style="grid-column:1/-1">
    <h3><a href="#" onclick="location.hash='';return false" style="color:var(--accent);text-decoration:none">← Library</a>
    &nbsp; ${esc(g.title)} <span style="color:var(--dim);font-weight:400;font-size:.78rem">${esc(g.disc)}${note}</span>
    &nbsp; ${report}</h3>
    <div style="margin:.2rem 0 .6rem">${badges}</div>
    <div class=mstrip>${list.length?list.map((m,i)=>mcard(g.id,m,i)).join(""):`<div style="color:#55555f">No models match.</div>`}</div></div>`;
  grid.querySelectorAll(".mcard").forEach(c=>{c.onclick=()=>{if(served&&c.classList.contains("v"))openMV(list[+c.dataset.i]);};});
  grid.querySelectorAll(".fl").forEach(el=>{el.onclick=e=>{e.stopPropagation();const card=el.closest(".mcard");toggleFlag(list[+card.dataset.i],el);};});
  grid.querySelectorAll(".act").forEach(el=>{el.onclick=e=>{e.stopPropagation();const card=el.closest(".mcard");doAct(el.dataset.act,list[+card.dataset.i]);};});
}
function renderGames(){
  const term=q.value.trim().toLowerCase();
  let list=GAMES.filter(g=>{
    if(filters.geo&&g.tris<=0)return false;if(filters.tex&&g.textures<=0)return false;
    if(filters.skin&&!g.skinned)return false;if(filters.anim&&g.clips<=0)return false;
    if(!catGameOK(g))return false;
    if(term&&!(g.title.toLowerCase().includes(term)||g.disc.toLowerCase().includes(term)||g.id.toLowerCase().includes(term)))return false;
    return true;});
  const k=sortSel.value,key=k==="models"?"models":k==="tex"?"textures":"tris";
  list.sort((a,b)=>k==="title"?a.title.localeCompare(b.title):b[key]-a[key]);
  empty.hidden=list.length>0;
  let h="";for(const g of list)h+=card(g);
  grid.innerHTML=h;
  // a card opens the game's own page - every model in that game, searchable
  grid.querySelectorAll(".card").forEach(c=>c.onclick=()=>{location.hash="g="+encodeURIComponent(c.dataset.id);});
}
let modelCache=[],modelCacheKey="\x00";
async function renderModels(){
  const term=q.value.trim().toLowerCase(),kc=kindCats();
  let pool;
  if(served){
    const key=term+"|"+kc.join(",")+"|"+(cats.has("rigged")?1:0);
    if(key!==modelCacheKey){grid.innerHTML=`<div class=empty>searching…</div>`;
      const p=new URLSearchParams();if(term)p.set("q",term);if(kc.length===1)p.set("kind",kc[0]);if(cats.has("rigged"))p.set("rigged","1");p.set("limit","600");
      try{const r=await fetch("/search_models.json?"+p.toString(),{cache:"no-store"});modelCache=(await r.json()).models||[];}catch(e){modelCache=[];}
      modelCacheKey=key;}
    pool=modelCache;
  }else{pool=[];for(const g of GAMES)for(const m of (g.top||[]))pool.push(Object.assign({gid:g.id,title:g.title},m));}
  let list=pool.filter(m=>{if(!modelKindOK(m))return false;if(term&&!((m.n||"").toLowerCase().includes(term)||(m.title||"").toLowerCase().includes(term)))return false;return true;});
  const k=sortSel.value;list.sort((a,b)=>k==="tex"?b.tex-a.tex:k==="title"?(a.n||"").localeCompare(b.n||""):b.tris-a.tris);
  list=list.slice(0,600);
  empty.hidden=list.length>0;
  grid.innerHTML=list.length?`<div class=mstrip style="grid-column:1/-1">${list.map((m,i)=>mcardG(m,i)).join("")}</div>`:"";
  grid.querySelectorAll(".mcard").forEach(c=>{c.onclick=()=>{if(served&&c.classList.contains("v"))openMV(list[+c.dataset.i]);};});
  grid.querySelectorAll(".gjump").forEach(t=>t.onclick=e=>{e.stopPropagation();location.hash="g="+encodeURIComponent(t.dataset.g);});
  grid.querySelectorAll(".fl").forEach(el=>{el.onclick=e=>{e.stopPropagation();const card=el.closest(".mcard");toggleFlag(list[+card.dataset.i],el);};});
  grid.querySelectorAll(".act").forEach(el=>{el.onclick=e=>{e.stopPropagation();const card=el.closest(".mcard");doAct(el.dataset.act,list[+card.dataset.i]);};});
}
let mermaidLoaded=false;
function ensureMermaid(cb){
  if(mermaidLoaded)return cb();
  const sc=document.createElement("script");
  sc.src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js";
  sc.onload=()=>{mermaidLoaded=true;window.mermaid.initialize({startOnLoad:false,theme:"dark",themeVariables:{pie1:"#7fb4ff",pie2:"#e08a8a",pie3:"#ffd98a",pie4:"#8ad0a0",pie5:"#c9a0e8",pie6:"#8ab6bd",pie7:"#b0b0be",pie8:"#6a7ba0",darkMode:true,fontFamily:"system-ui"}});cb();};
  sc.onerror=()=>{};/* the CSS bars beside it carry the same numbers */
  document.head.appendChild(sc);
}
function hbar(label,val,max,onclick){const w=max?Math.max(1,Math.round(val/max*100)):1;
  return `<div class=hbar><span class=lbl title="${esc(label)}" ${onclick?`data-go="${esc(onclick)}"`:""}>${esc(label)}</span><span class=bar style="width:${w}%"></span><span class=val>${fmt(val)}</span></div>`;}
function renderStats(){
  empty.hidden=true;
  const K=STATS.kinds||{},nf=Object.keys(FLAGS).length;
  const geo=GAMES.filter(g=>g.tris>0);
  const kindOrder=Object.entries(K).sort((a,b)=>b[1]-a[1]);
  const kmax=kindOrder.length?kindOrder[0][1]:1;
  const topG=[...GAMES].sort((a,b)=>b.tris-a.tris).slice(0,15);
  const topM=[...GAMES].sort((a,b)=>b.models-a.models).slice(0,15);
  const rigG=[...GAMES].filter(g=>g.rigged>0).sort((a,b)=>b.rigged-a.rigged).slice(0,15);
  const pieRows=kindOrder.map(([k,v])=>`    "${k}" : ${v}`).join(String.fromCharCode(10));
  grid.innerHTML=`<div class=dash>
  <div class=panel><h3>The lake</h3><div class=numgrid>
    <div class=bignum>${fmt(STATS.games)}<small>discs indexed</small></div>
    <div class=bignum>${fmt(STATS.with_geo)}<small>with geometry</small></div>
    <div class=bignum>${fmt(STATS.models)}<small>models</small></div>
    <div class=bignum>${fmt(STATS.tris)}<small>triangles</small></div>
    <div class=bignum>${fmt(STATS.tex)}<small>textures</small></div>
    <div class=bignum>${fmt(STATS.rigged||0)}<small>rigged models</small></div>
    <div class=bignum>${nf}<small>🚩 flagged for review</small></div>
  </div>
  <div style="margin-top:.8rem"><div class=hbar><span class=lbl>coverage</span><span class=bar style="width:${Math.round(STATS.with_geo/STATS.games*100)}%"></span><span class=val>${Math.round(STATS.with_geo/STATS.games*100)}%</span></div></div></div>
  <div class=panel><h3>Models by kind — mermaid</h3><div id=mpie style="min-height:200px;color:var(--dim);font-size:.75rem">rendering…</div></div>
  <div class=panel><h3>Models by kind — counts</h3>${kindOrder.map(([k,v])=>hbar(k,v,kmax)).join("")}</div>
  <div class=panel><h3>Top games by triangles</h3>${topG.map(g=>hbar(g.title,g.tris,topG[0].tris,g.id)).join("")}</div>
  <div class=panel><h3>Top games by model count</h3>${topM.map(g=>hbar(g.title,g.models,topM[0].models,g.id)).join("")}</div>
  <div class=panel><h3>Most rigged characters</h3>${rigG.map(g=>hbar(g.title,g.rigged,rigG[0]?.rigged||1,g.id)).join("")}</div>
  </div>`;
  grid.querySelectorAll(".lbl[data-go]").forEach(el=>el.onclick=()=>{location.hash="g="+encodeURIComponent(el.dataset.go);});
  ensureMermaid(async()=>{
    try{
      const src="pie showData"+String.fromCharCode(10)+pieRows;
      const {svg}=await window.mermaid.render("piechart",src);
      const el=document.getElementById("mpie");if(el)el.innerHTML=svg;
    }catch(e){const el=document.getElementById("mpie");if(el)el.textContent="mermaid failed: "+e;}
  });
}
function ensureMV(cb){
  if(mvLoaded)return cb();
  const s=document.createElement("script");s.type="module";
  s.src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js";
  s.onload=()=>{mvLoaded=true;cb();};s.onerror=()=>alert("3D viewer needs internet for the model-viewer library.");
  document.head.appendChild(s);
}
function openMV(m){
  if(!m.g)return;
  const url="/glb?path="+encodeURIComponent(m.g);
  document.getElementById("mvname").textContent=m.n;
  document.getElementById("mvdl").href=url;
  const fb=document.getElementById("mvflag");
  const setfb=()=>{const on=mkey(m) in FLAGS;fb.textContent=on?"🚩 Flagged — click to clear":"🚩 Flag as glitchy";fb.classList.toggle("on",on);};
  setfb();fb.onclick=async()=>{await toggleFlag(m,fb);setfb();};
  document.getElementById("mvblend").onclick=()=>doAct("open",m);
  ensureMV(()=>{document.getElementById("mv").innerHTML=`<model-viewer src="${url}" camera-controls auto-rotate exposure="1.1" shadow-intensity="0.6" style="width:100%;height:100%"></model-viewer>`;});
  document.getElementById("modal").classList.add("on");
}
function closeMV(){document.getElementById("modal").classList.remove("on");document.getElementById("mv").innerHTML="";}
addEventListener("keydown",e=>{if(e.key==="Escape")closeMV();});
render();
</script></body></html>"""
