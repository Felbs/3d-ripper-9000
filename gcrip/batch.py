"""Rip many discs in one go and keep a per-game scoreboard.

    gcrip dump  D:/roms/gamecube --out "D:/3d dump/GameCube"          # every disc, everything
    gcrip batch D:/roms/gamecube --survey out/survey/survey.jsonl --out out/rip [--engine J3D]

Reads the survey (or takes every disc in the folder when no survey is given), rips each
selected disc with the normal pipeline, appends one line per game to
<out>/batch_results.jsonl (resumable: finished games are skipped) and rewrites
<out>/batch_matrix.md - the compatibility matrix across games: models exported/failed,
clips, expression switches, warnings, seconds. Failures inside one game never stop the run.
"""

from __future__ import annotations

import json
import time
import traceback
from collections import Counter
from pathlib import Path


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def batch(
    folder: Path,
    out_root: Path,
    *,
    survey_path: Path | None = None,
    engine: str | None = "J3D",
    limit: int | None = None,
    only: list[str] | None = None,
    thumbnails: bool = True,
    animations: bool = True,
    extras: bool = True,
    blend: bool = False,
    blender: str | None = None,
    shard: tuple[int, int] | None = None,
    quiet: bool = False,
    rip_fn=None,
    suffixes: tuple[str, ...] = (".iso", ".gcm"),
    verify: bool = False,
) -> list[dict]:
    """``extras`` runs every post-rip step the disc has data for (levels, text, audio,
    music, cutscenes; see gcrip.extras); ``blend`` adds one .blend per model.
    ``shard=(i, n)`` takes every n-th disc starting at i, so n processes can share one
    out folder (they append to the same results file; the matrix is rebuilt from disk)."""
    import shutil

    from gcrip.extras import run_extras
    from gcrip.rip import rip as gc_rip

    rip = rip_fn or gc_rip
    folder, out_root = Path(folder), Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    single = folder.is_file()
    if single:
        folder, only, survey_path = folder.parent, [folder.name], None
    results_path = out_root / "batch_results.jsonl"
    done = {d["file"]: d for d in _load_jsonl(results_path)}
    if survey_path:
        discs = [d for d in _load_jsonl(Path(survey_path)) if not d.get("error")]
        if engine:
            discs = [d for d in discs if d["engine"] == engine]
        files = [folder / d["file"] for d in discs]
    else:
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in suffixes)
    if only:
        files = [
            f
            for f in files
            if any(
                o.lower() == f.name.lower() if single else o.lower() in f.name.lower() for o in only
            )
        ]
    if limit:
        files = files[:limit]
    if shard:
        i, n = shard
        files = files[i::n]
    todo = [f for f in files if f.name not in done]
    if not quiet:
        print(f"{len(files)} discs selected, {len(done)} already ripped, {len(todo)} to go")
    with results_path.open("a", encoding="utf-8") as fh:
        for i, f in enumerate(todo):
            t0 = time.monotonic()
            row = {"file": f.name}
            if not quiet:
                print(f"\n=== [{i + 1}/{len(todo)}] {f.name}", flush=True)
            try:
                res = None
                for attempt in range(3 if verify else 1):
                    res = rip(
                        f,
                        out_root,
                        quiet=quiet,
                        thumbnails=thumbnails,
                        animations=animations,
                    )
                    if not verify or rip_fn is not None:
                        break
                    from gcrip.verify import verify as verify_rip

                    v = verify_rip(res.out_dir, f, quiet=True)
                    row["verified"] = v.ok
                    row["verify_attempts"] = attempt + 1
                    if v.ok:
                        break
                    if not quiet:
                        print(
                            f"  ! re-read mismatch on {len(v.mismatched)} file(s) "
                            f"({', '.join(v.mismatched[:2])}) - ripping again",
                            flush=True,
                        )
                    shutil.rmtree(res.out_dir, ignore_errors=True)
                assert res is not None
                ok = [m for m in res.models if m.out_rel]
                errs = [m for m in res.models if m.error and not m.error.startswith("skipped")]
                warn = Counter()
                for m in ok:
                    for w in m.warnings:
                        warn[w.split(":")[0][:60]] += 1
                row.update(
                    game_id=res.game_id,
                    dir=res.out_dir.name,
                    title=res.title,
                    models_total=len(res.models),
                    exported=len(ok),
                    duplicates=sum(1 for m in res.models if m.duplicate_of),
                    failed=len(errs),
                    # plugins that recognised a file and produced nothing: not failures, but
                    # the class that hid 89 objects on FIFA 2003 behind a healthy-looking zero
                    claimed_empty=sum(1 for m in res.models if m.empty),
                    empty_examples=sorted(
                        {
                            f"{m.warnings[0].removeprefix('format: ')}: "
                            f"{m.path.rsplit('/', 1)[-1]}"
                            for m in res.models
                            if m.empty and m.warnings
                        }
                    )[:5],
                    fail_examples=[f"{m.path.split('/')[-1]}: {m.error}" for m in errs[:5]],
                    triangles=sum(m.triangles for m in ok),
                    clips=sum(len(m.animations) for m in ok),
                    animated_models=sum(1 for m in ok if m.animations),
                    expressions=sum(1 for m in ok if m.expressions),
                    mixamo_rigs=sum(1 for m in ok if len(m.std_bones) >= 15),
                    textured_pct=round(100 * sum(1 for m in ok if m.textures) / max(1, len(ok)), 1),
                    warnings=dict(warn.most_common(6)),
                    textures=sum(1 for t in res.textures if t.out_rel),
                    seconds=round(res.seconds),
                    report=str((res.out_dir / "report.html").as_posix()),
                )
                if (extras and rip_fn is None) or blend:
                    ex = run_extras(
                        f,
                        res.out_dir,
                        res.game_id,
                        quiet=quiet,
                        blend=blend,
                        blender=blender,
                        steps=extras and rip_fn is None,
                        log=None if quiet else (lambda m: print("  " + m, flush=True)),
                    )
                    row["extras"] = {
                        k: {a: b for a, b in v.items() if a != "trace"} for k, v in ex.items()
                    }
                    row["seconds"] = round(time.monotonic() - t0)
            except Exception as e:  # noqa: BLE001
                row.update(error=f"{type(e).__name__}: {e}", seconds=round(time.monotonic() - t0))
                if not quiet:
                    traceback.print_exc()
            done[f.name] = row
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            write_matrix(out_root, _all_rows(results_path, done))
    write_matrix(out_root, _all_rows(results_path, done))
    return list(done.values())


def _all_rows(results_path: Path, done: dict[str, dict]) -> list[dict]:
    """Rows from every process writing this results file (other shards included)."""
    merged = {d["file"]: d for d in _load_jsonl(results_path)}
    merged.update(done)
    return list(merged.values())


def write_matrix(out_root: Path, rows: list[dict]) -> Path:
    rows = sorted(rows, key=lambda r: (bool(r.get("error")), r.get("title") or r["file"]))
    tot_models = sum(r.get("exported", 0) for r in rows)
    tot_clips = sum(r.get("clips", 0) for r in rows)
    lines = [
        "# Batch rip matrix",
        "",
        f"{len(rows)} games · {tot_models:,} models exported · {tot_clips:,} animation clips · "
        f"{sum(r.get('failed', 0) for r in rows)} model failures · "
        f"{sum(r.get('claimed_empty', 0) for r in rows)} claimed-but-empty · "
        f"{sum(1 for r in rows if r.get('error'))} games errored",
        "",
        "| game | ID | exported | dups | failed | empty | tris | clips | animated | expr "
        "| Mixamo rigs | textured % | textures | extras | s | top warnings |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| {r['file']} | | ⚠ {r['error']} | | | | | | | | | | | | {r.get('seconds', 0)} | |"
            )
            continue
        warns = "; ".join(f"{k} ×{v}" for k, v in r.get("warnings", {}).items())[:160]
        fails = "; ".join(r.get("fail_examples", []))[:160]
        note = warns + ((" ‖ " + fails) if fails else "")
        lines.append(
            f"| [{r['title']}]({r['report']}) | {r['game_id']} | {r['exported']} | "
            f"{r['duplicates']} | "
            f"{r['failed']} | {r.get('claimed_empty', 0)} | "
            f"{r['triangles']:,} | {r['clips']} | {r['animated_models']} | "
            f"{r['expressions']} | {r['mixamo_rigs']} | {r['textured_pct']} | {r['textures']} | "
            f"{_extras_cell(r)} | {r['seconds']} | {note} |"
        )
    p = out_root / "batch_matrix.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_dump_readme(out_root, rows)
    return p


def _extras_cell(r: dict) -> str:
    ex = r.get("extras") or {}
    parts = []
    for k, v in ex.items():
        if not v.get("ok"):
            parts.append(f"{k} ⚠")
            continue
        n = next((v[a] for a in ("built", "streams", "songs", "scenes", "written") if a in v), None)
        parts.append(k if n is None else f"{k} {n}")
    return ", ".join(parts)


def write_dump_readme(out_root: Path, rows: list[dict]) -> Path:
    """<out_root>/README.md: what is in this dump folder and how to open it, plus the
    Blender add-on so the folder is self-contained."""
    import contextlib
    import shutil

    import gcrip

    addon = Path(gcrip.__file__).resolve().parent.parent / "blender" / "gcrip_blender.py"
    if addon.exists():
        with contextlib.suppress(OSError):
            shutil.copyfile(addon, out_root / "gcrip_blender.py")
    ok = [r for r in rows if not r.get("error")]
    with_models = [r for r in ok if r.get("exported")]
    lines = [
        "# 3D Ripper 9000 dump",
        "",
        f"{len(rows)} discs processed · {len(with_models)} with models · "
        f"{sum(r.get('exported', 0) for r in ok):,} models · "
        f"{sum(r.get('clips', 0) for r in ok):,} animation clips · "
        f"{sum(r.get('textures', 0) for r in ok):,} standalone textures",
        "",
        "Each `<GameID>/` folder mirrors the disc layout: `<model>.gltf` + `.bin` + `_tex/*.png`,",
        "`report.html` (browse everything with thumbnails), `disc_manifest.json`, and when the",
        "game has them: `stages/` (recompiled levels), `text/`, `audio/`, `cutscenes/`.",
        "",
        "Open models in Blender with **File > Import > GCRip glTF** after installing",
        "`gcrip_blender.py` (Edit > Preferences > Add-ons > Install from Disk); press N for the",
        "GCRip tab (expression switches, Mixamo bone renaming). Or `gcrip serve <GameID>`",
        "for the report with Open-in-Blender buttons.",
        "",
        "Full per-game numbers: [batch_matrix.md](batch_matrix.md).",
        "",
        "| game | ID | models | clips | textures | extras |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in sorted(ok, key=lambda r: (-r.get("exported", 0), r.get("title") or r["file"])):
        if not r.get("exported") and not r.get("textures"):
            continue
        lines.append(
            f"| [{r['title']}]({r.get('dir') or r['game_id']}/report.html) | "
            f"{r['game_id']} | {r['exported']} | "
            f"{r['clips']} | {r['textures']} | {_extras_cell(r)} |"
        )
    p = out_root / "README.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
