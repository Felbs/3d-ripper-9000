"""Rip many discs in one go and keep a per-game scoreboard.

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
    quiet: bool = False,
) -> list[dict]:
    from gcrip.rip import rip

    folder, out_root = Path(folder), Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    results_path = out_root / "batch_results.jsonl"
    done = {d["file"]: d for d in _load_jsonl(results_path)}
    if survey_path:
        discs = [d for d in _load_jsonl(Path(survey_path)) if not d.get("error")]
        if engine:
            discs = [d for d in discs if d["engine"] == engine]
        files = [folder / d["file"] for d in discs]
    else:
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".iso", ".gcm"))
    if only:
        files = [f for f in files if any(o.lower() in f.name.lower() for o in only)]
    if limit:
        files = files[:limit]
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
                res = rip(
                    f,
                    out_root,
                    quiet=quiet,
                    thumbnails=thumbnails,
                    animations=animations,
                )
                ok = [m for m in res.models if m.out_rel]
                errs = [m for m in res.models if m.error and not m.error.startswith("skipped")]
                warn = Counter()
                for m in ok:
                    for w in m.warnings:
                        warn[w.split(":")[0][:60]] += 1
                row.update(
                    game_id=res.game_id,
                    title=res.title,
                    models_total=len(res.models),
                    exported=len(ok),
                    duplicates=sum(1 for m in res.models if m.duplicate_of),
                    failed=len(errs),
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
            except Exception as e:  # noqa: BLE001
                row.update(error=f"{type(e).__name__}: {e}", seconds=round(time.monotonic() - t0))
                if not quiet:
                    traceback.print_exc()
            done[f.name] = row
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            write_matrix(out_root, list(done.values()))
    write_matrix(out_root, list(done.values()))
    return list(done.values())


def write_matrix(out_root: Path, rows: list[dict]) -> Path:
    rows = sorted(rows, key=lambda r: (bool(r.get("error")), r.get("title") or r["file"]))
    tot_models = sum(r.get("exported", 0) for r in rows)
    tot_clips = sum(r.get("clips", 0) for r in rows)
    lines = [
        "# Batch rip matrix",
        "",
        f"{len(rows)} games · {tot_models:,} models exported · {tot_clips:,} animation clips · "
        f"{sum(r.get('failed', 0) for r in rows)} model failures · "
        f"{sum(1 for r in rows if r.get('error'))} games errored",
        "",
        "| game | ID | exported | dups | failed | tris | clips | animated | expr | Mixamo rigs "
        "| textured % | textures | s | top warnings |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| {r['file']} | | ⚠ {r['error']} | | | | | | | | | | {r.get('seconds', 0)} | |"
            )
            continue
        warns = "; ".join(f"{k} ×{v}" for k, v in r.get("warnings", {}).items())[:160]
        fails = "; ".join(r.get("fail_examples", []))[:160]
        note = warns + ((" ‖ " + fails) if fails else "")
        lines.append(
            f"| [{r['title']}]({r['report']}) | {r['game_id']} | {r['exported']} | "
            f"{r['duplicates']} | "
            f"{r['failed']} | {r['triangles']:,} | {r['clips']} | {r['animated_models']} | "
            f"{r['expressions']} | {r['mixamo_rigs']} | {r['textured_pct']} | {r['textures']} | "
            f"{r['seconds']} | {note} |"
        )
    p = out_root / "batch_matrix.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
