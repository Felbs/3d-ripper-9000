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

TOP_MODELS = 24  # inline model thumbnails baked per game


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
    for m in models:
        thumb, tris = m.get("thumb"), int(m.get("triangles") or 0)
        if not thumb or tris <= 0 or m.get("duplicate_of") or m.get("error"):
            continue
        if m.get("skinned"):
            entry["skinned"] = True
        have.append((tris, m, thumb))
    have.sort(key=lambda x: -x[0])
    for tris, m, thumb in have:
        if entry["hero"] is None and (root / gid / thumb).exists():
            entry["hero"] = f"{gid}/{thumb}"
        if len(entry["top"]) < TOP_MODELS:
            out_rel = m.get("out_rel")
            entry["top"].append(
                {
                    "n": (m.get("path") or out_rel or "model").split("/")[-1],
                    "t": f"{gid}/{thumb}",
                    "tris": tris,
                    "tex": int(m.get("textures") or 0),
                    "g": f"{gid}/{out_rel}" if out_rel and out_rel.endswith(".gltf") else None,
                }
            )
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
    stats = {
        "games": len(games),
        "with_geo": sum(1 for g in games if g["tris"] > 0),
        "models": sum(g["models"] for g in games),
        "tris": sum(g["tris"] for g in games),
        "tex": sum(g["textures"] for g in games),
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
            if path == "/catalog.json":
                # on demand only (the page's Refresh button) - one rescan of the metadata
                # JSONs, so it is a click, never a poll, keeping disc load off the rip
                body = json.dumps(build_catalog(root)).encode()
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
  <input id="q" placeholder="Search games…  (title or disc filename)" autocomplete="off">
  <select id="sort">
    <option value="tris">Sort: most triangles</option><option value="models">Sort: most models</option>
    <option value="title">Sort: title A–Z</option><option value="tex">Sort: most textures</option>
  </select>
  <span class="chip" data-f="geo">Has models</span><span class="chip" data-f="tex">Textured</span>
  <span class="chip" data-f="skin">Skinned</span><span class="chip" data-f="anim">Animated</span>
  <span class="chip" id="refresh" title="Rescan the dump for newly ripped games">↻ Refresh</span>
</div></header>
<main><div class="grid" id="grid"></div><div class="empty" id="empty" hidden>No games match.</div></main>
<footer id="foot"></footer>
<div id="modal"><div class="bar"><b id="mvname"></b><a id="mvdl" href="#" download>Download .glb</a><span class="x" onclick="closeMV()">×</span></div><div id="mv"></div></div>
<script>
let GAMES=__DATA__, STATS=__STATS__;
const served=location.protocol==="http:"||location.protocol==="https:";
const fmt=n=>n>=1e6?(n/1e6).toFixed(1)+"M":n>=1e3?(n/1e3).toFixed(0)+"k":(""+n);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function drawStats(){document.getElementById("sub").textContent=`${STATS.with_geo} of ${STATS.games} discs with geometry`;
document.getElementById("statbar").innerHTML=[["Games",STATS.games],["With geometry",STATS.with_geo],["Models",fmt(STATS.models)],["Triangles",fmt(STATS.tris)],["Textures",fmt(STATS.tex)]].map(([k,v])=>`<span class="stat">${k} <b>${v}</b></span>`).join("");}
drawStats();
const refresh=document.getElementById("refresh");
if(served){refresh.onclick=async()=>{refresh.textContent="↻ …";try{const r=await fetch("/catalog.json",{cache:"no-store"});const c=await r.json();GAMES=c.games;STATS=c.stats;drawStats();render();}catch(e){alert("Refresh failed: "+e);}refresh.textContent="↻ Refresh";};}
else refresh.style.display="none";
document.getElementById("foot").innerHTML=served?"Served locally — click any model thumbnail to preview it in 3D, or open a game's full report. Nothing is uploaded.":"Opened from disk — click a game to preview its top models, or open its full report. For live 3D preview, run <code>gcrip library</code> to serve the folder.";
const grid=document.getElementById("grid"),empty=document.getElementById("empty"),q=document.getElementById("q"),sortSel=document.getElementById("sort");
const filters={geo:false,tex:false,skin:false,anim:false};let expanded=null,mvLoaded=false;
document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{filters[c.dataset.f]=!filters[c.dataset.f];c.classList.toggle("on");render();});
q.oninput=render;sortSel.onchange=render;
function card(g){
  const icons=(g.skinned?"⤳":"")+(g.clips>0?" ▶":"");
  const hero=g.hero?`<img class=hero loading=lazy src="${g.hero}" alt="">`:`<div class=noimg>no preview</div>`;
  const b=[`<span class="badge${g.tris>0?" g":""}">${fmt(g.models)} mdl</span>`,g.tris>0?`<span class="badge">△ ${fmt(g.tris)}</span>`:"",g.textures>0?`<span class="badge">▦ ${fmt(g.textures)}</span>`:"",`<span class="icons">${icons}</span>`].join("");
  return `<div class="card" data-id="${g.id}">${hero}<div class="body"><div class="title" title="${esc(g.title)}">${esc(g.title)}</div><div class="meta">${b}</div></div></div>`;
}
function expandBlock(g){
  const link=g.report?`<a href="${g.report}" target="_blank">Open full report ↗</a>`:"";
  const strip=g.top.length?g.top.map((m,i)=>`<div class="mcard${served&&m.g?" v":""}" data-id="${g.id}" data-i="${i}"><img loading=lazy src="${m.t}" alt=""><div class=mn title="${esc(m.n)}">${esc(m.n)}</div>△ ${fmt(m.tris)}${m.tex?` · ▦${m.tex}`:""}</div>`).join(""):`<div style="color:#55555f">No model previews.</div>`;
  return `<div class="expand"><h3>${esc(g.title)} — top ${g.top.length} of ${fmt(g.models)} models ${link}</h3><div class=mstrip>${strip}</div></div>`;
}
function render(){
  const term=q.value.trim().toLowerCase();
  let list=GAMES.filter(g=>{
    if(filters.geo&&g.tris<=0)return false;if(filters.tex&&g.textures<=0)return false;
    if(filters.skin&&!g.skinned)return false;if(filters.anim&&g.clips<=0)return false;
    if(term&&!(g.title.toLowerCase().includes(term)||g.disc.toLowerCase().includes(term)||g.id.toLowerCase().includes(term)))return false;
    return true;});
  const k=sortSel.value,key=k==="models"?"models":k==="tex"?"textures":"tris";
  list.sort((a,b)=>k==="title"?a.title.localeCompare(b.title):b[key]-a[key]);
  empty.hidden=list.length>0;
  let h="";for(const g of list){h+=card(g);if(expanded===g.id)h+=expandBlock(g);}
  grid.innerHTML=h;
  grid.querySelectorAll(".card").forEach(c=>c.onclick=()=>{expanded=expanded===c.dataset.id?null:c.dataset.id;render();});
  grid.querySelectorAll(".mcard.v").forEach(c=>c.onclick=e=>{e.stopPropagation();const g=GAMES.find(x=>x.id===c.dataset.id);openMV(g.top[+c.dataset.i]);});
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
  ensureMV(()=>{document.getElementById("mv").innerHTML=`<model-viewer src="${url}" camera-controls auto-rotate exposure="1.1" shadow-intensity="0.6" style="width:100%;height:100%"></model-viewer>`;});
  document.getElementById("modal").classList.add("on");
}
function closeMV(){document.getElementById("modal").classList.remove("on");document.getElementById("mv").innerHTML="";}
addEventListener("keydown",e=>{if(e.key==="Escape")closeMV();});
render();
</script></body></html>"""
