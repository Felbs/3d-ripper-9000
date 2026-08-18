"""Turn a finished rip into a Blender asset library: one .blend per model, marked as an
asset with the rip thumbnail, sorted into catalogs by disc path.

    gcrip blend out/rip/GZLE01 [--blender PATH] [--filter TEXT] [--limit N] [--force]

Afterwards, in Blender: Edit > Preferences > File Paths > Asset Libraries > add
`out/rip` (or use the GCRip panel's "Add rip folder as asset library" button). Every
model then appears in the Asset Browser with its thumbnail and can be dragged into any
scene; double-clicking a .blend opens that model on its own for editing.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_NS = uuid.UUID("2c1a4b7e-9d3f-4a1c-8f6e-1b2d3c4e5f60")


def find_blender(explicit: str | None = None) -> str | None:
    """Blender executable: --blender, $BLENDER, PATH, then the usual install folders
    (newest version first)."""
    cands: list[str] = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("BLENDER"):
        cands.append(os.environ["BLENDER"])
    on_path = shutil.which("blender")
    if on_path:
        cands.append(on_path)
    if sys.platform == "win32":
        for base in (
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        ):
            found = glob.glob(os.path.join(base, "Blender Foundation", "Blender *", "blender.exe"))
            cands += sorted(found, key=_version_key, reverse=True)
        cands += sorted(
            glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender*\blender.exe")),
            reverse=True,
        )
    elif sys.platform == "darwin":
        cands += ["/Applications/Blender.app/Contents/MacOS/Blender"]
    else:
        cands += ["/usr/bin/blender", "/snap/bin/blender", "/usr/local/bin/blender"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _version_key(path: str) -> tuple:
    import re

    m = re.search(r"Blender (\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def addon_path() -> Path | None:
    """blender/gcrip_blender.py from a source checkout (None when pip-installed)."""
    p = Path(__file__).resolve().parent.parent / "blender" / "gcrip_blender.py"
    return p if p.exists() else None


@dataclass
class BlendResult:
    done: int = 0
    failed: list[str] = field(default_factory=list)
    skipped: int = 0
    seconds: float = 0.0
    library_root: Path | None = None


def catalog_id(path: str) -> str:
    return str(uuid.uuid5(CATALOG_NS, path))


def write_catalogs(library_root: Path, catalog_paths: set[str]) -> None:
    """blender_assets.cats.txt: one line per catalog and every parent so the tree is
    browsable (Blender wants the parents listed too)."""
    all_paths: set[str] = set()
    for p in catalog_paths:
        parts = p.split("/")
        for i in range(1, len(parts) + 1):
            all_paths.add("/".join(parts[:i]))
    lines = ["# gcrip asset catalogs", "VERSION 1", ""]
    for p in sorted(all_paths):
        lines.append(f"{catalog_id(p)}:{p}:{p.replace('/', '-')}")
    (library_root / "blender_assets.cats.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def blend(
    game_dir: Path,
    *,
    blender: str | None = None,
    path_filter: str | None = None,
    limit: int | None = None,
    force: bool = False,
    quiet: bool = False,
    batch: int = 40,
) -> BlendResult:
    t0 = time.monotonic()
    game_dir = Path(game_dir).resolve()
    res = BlendResult(library_root=game_dir.parent)
    exe = find_blender(blender)
    if not exe:
        raise SystemExit("Blender not found: pass --blender PATH or set BLENDER")
    results = json.loads((game_dir / "rip_results.json").read_text(encoding="utf-8"))
    game_id = results["game_id"]
    models = [m for m in results["models"] if m.get("out_rel")]
    if path_filter:
        models = [m for m in models if path_filter in m["path"]]
    if limit:
        models = models[:limit]
    jobs = []
    catalogs: set[str] = set()
    for m in models:
        gltf = game_dir / m["out_rel"]
        blend_path = gltf.with_suffix(".blend")
        m["blend_rel"] = str(Path(m["out_rel"]).with_suffix(".blend").as_posix())
        if blend_path.exists() and not force:
            res.skipped += 1
            continue
        arc_dir = Path(m["out_rel"]).parent.as_posix()
        # catalog: GameID / disc directory (archives kept as their own level)
        cat = f"{game_id}/{arc_dir}".replace("/archive", "")
        catalogs.add(cat)
        jobs.append(
            {
                "gltf": str(gltf),
                "blend": str(blend_path),
                "thumb": str(game_dir / m["thumb"]) if m.get("thumb") else None,
                "name": gltf.stem,
                "catalog": cat,
                "catalog_id": catalog_id(cat),
                "description": f"{m['path']} - {m['triangles']:,} tris, {m['joints']} joints, "
                f"{len(m.get('animations') or [])} clips",
                "tags": [game_id, *(["animated"] if m.get("animations") else [])],
                "index": m["path"],
            }
        )
    if not quiet:
        print(f"{len(jobs)} models -> .blend ({res.skipped} already done), Blender: {exe}")
    write_catalogs(game_dir.parent, catalogs | _existing_catalogs(game_dir.parent))
    script = Path(__file__).resolve().parent / "blender_batch.py"
    addon = addon_path()
    for start in range(0, len(jobs), batch):
        chunk = jobs[start : start + batch]
        cfg = game_dir / "_blend_jobs.json"
        cfg.write_text(
            json.dumps({"addon": str(addon) if addon else None, "game": game_id, "jobs": chunk}),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [exe, "-b", "--python", str(script), "--", str(cfg)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        lines = proc.stdout.splitlines()
        ok = {int(line.split()[1]) for line in lines if line.startswith("BLEND_OK")}
        for i, job in enumerate(chunk):
            if i in ok:
                res.done += 1
            else:
                err = next(
                    (line.split(" ", 2)[2] for line in lines if line.startswith(f"BLEND_ERR {i} ")),
                    "blender exited without result",
                )
                res.failed.append(f"{job['index']}: {err}")
        if not quiet:
            n = min(start + batch, len(jobs))
            print(f"  {n}/{len(jobs)} ({len(res.failed)} failed)", flush=True)
        cfg.unlink(missing_ok=True)
    # record .blend paths so report.html / serve can link them, and refresh the report
    (game_dir / "rip_results.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    from gcrip.rip import load_results, write_report

    write_report(load_results(game_dir))
    res.seconds = time.monotonic() - t0
    return res


def _existing_catalogs(root: Path) -> set[str]:
    f = root / "blender_assets.cats.txt"
    out: set[str] = set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith(("#", "VERSION")):
                out.add(line.split(":")[1])
    return out
