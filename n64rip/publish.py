"""Publish an N64 rip into a gcrip dump root so the library browser can show it.

Everything downstream of the rip - the browser, the model search, the quality auditor, the
MCP tools, the Blender add-on - reads two JSON files and a folder of glTFs.  None of it knows
or cares what console the models came from, so an N64 rip only has to write the same shapes:

* ``<root>/<GID>/rip_results.json`` with a ``models`` list, and
* one row appended to ``<root>/batch_results.jsonl``.

The row is written from Python rather than a shell tool on purpose: PowerShell's
``Set-Content -Encoding utf8`` puts a UTF-8 BOM on line 1, which used to make the next rip
die before it touched a disc.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

BATCH = "batch_results.jsonl"


def _model_rows(report: dict) -> list[dict]:
    """The rip's own models, in the shape gcrip's library reads."""
    out = []
    for m in report["models"]:
        if not m.get("out_rel"):
            continue
        out.append(
            {
                # the UI names a model from its source path, so give it the file it came from
                "path": f"{report['code']}/{m['name']}",
                "out_rel": m["out_rel"],
                "thumb": m.get("thumb") or "",
                "triangles": int(m.get("triangles") or 0),
                "vertices": int(m.get("vertices") or 0),
                "textures": int(m.get("textures") or 0),
                "skinned": bool(m.get("limbs", 0) > 1),
                "joints": int(m.get("limbs") or 0),
                "animations": [],
                "warnings": list(m.get("warnings") or []),
                "error": m.get("error") or "",
                "extras": {
                    "console": "n64",
                    "drawn_limbs": m.get("drawn_limbs"),
                    "textures_missing": m.get("textures_missing"),
                    "unresolved_segments": m.get("unresolved_segments"),
                    "vrom": m.get("vrom"),
                },
            }
        )
    return out


def publish(rip_dir: Path, root: Path, gid: str, title: str, disc_label: str) -> dict:
    """Copy a finished N64 rip into *root* under *gid* and register it in the batch file.

    Returns the batch row that was written.  Re-publishing the same gid replaces both the
    folder contents and the row, so this is safe to run again after a re-rip.
    """
    rip_dir, root = Path(rip_dir), Path(root)
    report = json.loads((rip_dir / "rip_results.json").read_text(encoding="utf-8"))
    dest = root / gid
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(rip_dir, dest)

    models = _model_rows(report)
    (dest / "rip_results.json").write_text(
        json.dumps({"game_id": gid, "title": title, "models": models}, indent=1),
        encoding="utf-8",
    )

    ok = [m for m in models if m["triangles"] > 0]
    row = {
        "file": disc_label,
        "game_id": gid,
        "dir": gid,
        "title": title,
        "models_total": len(report["models"]),
        "exported": len(ok),
        "duplicates": 0,
        "failed": int(report["totals"].get("failed") or 0),
        "triangles": sum(m["triangles"] for m in ok),
        "clips": 0,
        "animated_models": 0,
        "expressions": 0,
        "mixamo_rigs": 0,
        "textured_pct": round(100 * sum(1 for m in ok if m["textures"]) / max(1, len(ok)), 1),
        "textures": sum(m["textures"] for m in ok),
        "seconds": int(report.get("seconds") or 0),
        "report": str((dest / "report.html").as_posix()),
        "console": "n64",
    }

    batch = root / BATCH
    lines = []
    if batch.exists():
        for line in batch.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                if json.loads(line).get("game_id") == gid:
                    continue  # replacing a previous publish of this ROM
            except json.JSONDecodeError:
                pass
            lines.append(line)
    lines.append(json.dumps(row))
    batch.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return row
