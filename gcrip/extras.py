"""Everything beyond models that gcrip knows how to pull off a disc, run in one go after a
rip: recompiled levels, text, streamed audio, sequenced music, cutscenes, and optionally
one .blend per model. Each step checks whether the disc has that kind of data, runs
in isolation, and reports counts/seconds/errors - a failure in one step never blocks the
next, and never fails the game.

    run_extras(iso, game_dir, game_id) -> {"stages": {...}, "text": {...}, ...}
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from pathlib import Path

WW_IDS = ("GZL",)  # Wind Waker: stage recompiler, cutscenes and message tables are WW-specific


def _timed(fn: Callable[[], dict]) -> dict:
    t0 = time.monotonic()
    try:
        out = fn() or {}
        out.setdefault("ok", True)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


def applicable(iso: Path, game_id: str) -> dict[str, bool]:
    """Which extras this disc has data for (cheap: header + FST only)."""
    from gcrip.audio import AAF_PATH, STREAM_RE
    from gcrip.msg import MSG_ARC
    from gcrip.music import SEQS_PATH
    from gcrip.stage import _Disc

    disc = _Disc(iso)
    try:
        paths = disc.entries
        ww = game_id.startswith(WW_IDS)
        return {
            "stages": ww and bool(disc.stages()),
            "text": MSG_ARC in paths,
            "streams": any(STREAM_RE.match(p) for p in paths),
            "music": AAF_PATH in paths and SEQS_PATH in paths,
            "cutscenes": ww,
        }
    finally:
        disc.img.close()


def _count(r: object) -> int:
    return len(r) if hasattr(r, "__len__") else 0


def _wavs(folder: Path) -> int:
    return sum(1 for _ in folder.glob("*.wav")) if folder.is_dir() else 0


def run_extras(
    iso: Path,
    game_dir: Path,
    game_id: str,
    *,
    quiet: bool = True,
    blend: bool = False,
    blender: str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, dict]:
    iso, game_dir = Path(iso), Path(game_dir)
    say = log or (lambda m: None)
    todo = applicable(iso, game_id)
    out: dict[str, dict] = {}

    if todo["stages"]:
        say("stages: recompiling every level ...")

        def _stages() -> dict:
            from gcrip.stage import build_all

            rows = build_all(game_dir, iso=iso, quiet=True)
            ok = [r for r in rows if not r.get("error")]
            return {
                "built": len(ok),
                "total": len(rows),
                "actors": sum(r["placed"] for r in ok),
                "unresolved": sum(r["unresolved"] for r in ok),
                "matrix": str((game_dir / "stages" / "stage_matrix.md").as_posix()),
            }

        out["stages"] = _timed(_stages)

    if todo["text"]:
        say("text: dumping message tables ...")

        def _text() -> dict:
            from gcrip.msg import dump_messages

            p = dump_messages(game_dir, iso=iso, quiet=True)
            return {"path": str(Path(p).as_posix())}

        out["text"] = _timed(_text)

    if todo["streams"]:
        say("audio: decoding streamed music ...")

        def _streams() -> dict:
            from gcrip.audio import dump_streams

            dump_streams(game_dir, iso=iso, quiet=True)
            return {"streams": _wavs(game_dir / "audio" / "streams")}

        out["streams"] = _timed(_streams)

    if todo["music"]:
        say("music: rendering sequenced songs ...")

        def _music() -> dict:
            from gcrip.music import dump_music

            dump_music(game_dir, iso=iso, quiet=True)
            return {"songs": _wavs(game_dir / "audio" / "music")}

        out["music"] = _timed(_music)

    if todo["cutscenes"]:
        say("cutscenes: baking .stb scenes ...")

        def _cut() -> dict:
            from gcrip.cutscene import dump_cutscenes

            return {"scenes": _count(dump_cutscenes(game_dir, iso=iso, quiet=True))}

        out["cutscenes"] = _timed(_cut)

    if any(v.get("ok") for v in out.values()):
        # the report gets stage cards / links for what was just added
        def _report() -> dict:
            from gcrip.rip import load_results, write_report

            write_report(load_results(game_dir))
            return {}

        _timed(_report)

    if blend:
        say("blend: writing one .blend per model (Blender) ...")

        def _blend() -> dict:
            from gcrip.blend import blend as run_blend

            r = run_blend(game_dir, blender=blender, quiet=True)
            return {"written": r.done, "existing": r.skipped, "failed": len(r.failed)}

        out["blend"] = _timed(_blend)

    for k, v in out.items():
        if v.get("ok"):
            say(f"{k}: " + ", ".join(f"{a}={b}" for a, b in v.items() if a not in ("ok", "trace")))
        else:
            say(f"{k}: FAILED {v.get('error')}")
    return out
