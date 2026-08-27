"""Regenerate docs/COMPATIBILITY.md from a dump folder's batch_results.jsonl and the
library survey. No game data goes in - only counts and titles.

    python tools/compat_doc.py "D:/3d dump/GameCube" [docs/COMPATIBILITY.md]
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

NOTES = {
    "GLME01": "few BMDs; rooms/characters use Luigi's Mansion's own `.mdl` + `.bin` formats "
    "- future module",
    "GPXE01": "8 Pokémon storage models",
    "PZLE01": "the Wind Waker demo inside `ZL_WindWakerUSASHOP_*.tgc`; OoT/MM are N64 ROMs "
    "(not J3D)",
    "G4SE01": "GBA-era assets; small BMDs",
    "GMSE01": "byte-identical duplicates skipped (every level .szs repeats the NPC set)",
}


def load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def extras_cell(r: dict) -> str:
    parts = []
    for k, v in (r.get("extras") or {}).items():
        if not v.get("ok"):
            parts.append(f"{k} ⚠")
            continue
        n = next((v[a] for a in ("built", "streams", "songs", "scenes", "written") if a in v), None)
        parts.append(k if n is None else f"{k} {n}")
    return ", ".join(parts)


def main(dump: Path, out: Path) -> None:
    rows = load(dump / "batch_results.jsonl")
    survey = load(dump / "_survey" / "survey.jsonl")
    ok = [r for r in rows if not r.get("error")]
    errs = [r for r in rows if r.get("error")]
    j3d = sorted((r for r in ok if r.get("exported")), key=lambda r: -r["exported"])
    tex_only = sorted(
        (r for r in ok if not r.get("exported") and r.get("textures")),
        key=lambda r: -r["textures"],
    )
    nothing = [r for r in ok if not r.get("exported") and not r.get("textures")]
    n_discs = len(rows)
    today = dt.date.today().isoformat()
    L = [
        "# Compatibility",
        "",
        f"`gcrip survey` + `gcrip dump` over a {len(survey) or n_discs}-disc GameCube library "
        f"(USA set), {today}. {n_discs} discs processed, {len(errs)} errored. "
        "No game data is stored here - only counts.",
        "",
        "## Games that rip (J3D models -> glTF)",
        "",
        "| game | ID | models | dups | failed | clips | animated | expressions | Mixamo rigs "
        "| textured % | textures | extras | s | notes |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for r in j3d:
        L.append(
            f"| {r['title']} | {r['game_id']} | {r['exported']:,} | {r['duplicates']:,} | "
            f"{r['failed']} | {r['clips']:,} | {r['animated_models']} | {r['expressions']} | "
            f"{r['mixamo_rigs']} | {r['textured_pct']} | {r['textures']:,} | {extras_cell(r)} | "
            f"{r['seconds']} | {NOTES.get(r['game_id'], '')} |"
        )
    L += [
        "",
        f"**Total: {len(j3d)} games, {sum(r['exported'] for r in j3d):,} unique models, "
        f"{sum(r['clips'] for r in j3d):,} animation clips, "
        f"{sum(r['failed'] for r in j3d)} model failures.**",
        "",
        "## Games where only standalone textures come out (TPL/BTI, no J3D models)",
        "",
        "Every one of these ran through the full pipeline without error; their models are in",
        "formats gcrip does not parse yet (see the engine guesses below).",
        "",
        "| game | ID | textures | engine guess |",
        "|---|---|---:|---|",
    ]
    eng = {d["game_id"]: d["engine"] for d in survey}
    for r in tex_only:
        L.append(
            f"| {r['title']} | {r['game_id']} | {r['textures']:,} | {eng.get(r['game_id'], '')} |"
        )
    L += [
        "",
        f"## Games that produce nothing yet ({len(nothing)})",
        "",
        "Walked and manifested without error (disc filesystem, archives), but no format gcrip",
        "knows how to decode. Grouped by the survey's engine guess; each group is a candidate",
        "for a new parser module or the Dolphin capture fork.",
        "",
        "| engine / publisher guess | discs | examples |",
        "|---|---:|---|",
    ]
    groups: dict[str, list[str]] = {}
    for r in nothing:
        groups.setdefault(eng.get(r["game_id"], "unknown"), []).append(r["title"])
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        L.append(f"| {k} | {len(v)} | {', '.join(sorted(v)[:4])} |")
    if errs:
        L += ["", "## Discs that errored", "", "| file | error |", "|---|---|"]
        for r in errs:
            L.append(f"| {r['file']} | {r['error'][:120]} |")
    if survey:
        by_engine = Counter(d["engine"] for d in survey)
        L += [
            "",
            "## Survey engine guesses (whole library)",
            "",
            "| engine / publisher guess | discs |",
            "|---|---:|",
        ]
        L += [f"| {k} | {v} |" for k, v in by_engine.most_common()]
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{len(j3d)} ripping, {len(tex_only)} textures-only, {len(nothing)} nothing, "
          f"{len(errs)} errored -> {out}")


if __name__ == "__main__":
    dump = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/COMPATIBILITY.md")
    main(dump, out)
