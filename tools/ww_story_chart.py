# ruff: noqa: E501
"""Compare the original game's opening flow with what our remake actually executes.

The left chart is Wind Waker as the decompilation describes it (gcrip/data/ww_story_outset.json,
mined step by step with file:line citations).  The right chart is the same graph annotated with
what the Godot remake can really trigger today, worked out from the engine's capabilities rather
than from hope: each step's trigger kind is matched against the mechanisms `gcrip/godot.py`
implements, and every step that cannot fire is called out with the reason.

usage: python tools/ww_story_chart.py [--out docs/story_chart.md]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "gcrip" / "data" / "ww_story_outset.json"

# Trigger mechanisms the engine implements, and how.
IMPLEMENTED = {
    "spawn": "PLYR params >> 24 indexes the stage EVNT table (Game._place_player)",
    "tag": "TagEv volumes order their EVNT entry (actors/tag_event.gd)",
    "room_enter": "a stage's StartCamera event runs on arrival (stage.gd)",
    "talk": "story-graph talk steps (Game.story_talk) via actors/npc.gd",
    "look": "the Telescope's scope look at the step's target (Game.telescope_look)",
    "npc": "the NPC orders it itself, by proximity or on being placed (Game.story_npc_tick)",
}

BUILD = ROOT / "out" / "rip" / "GZLE01" / "godot" / "stage_data.json"
SCENES: dict[str, set[str]] | None = None   # set from the build in main()

# save-file state the engine models beyond the raw event bits
MODELLED_STATE = {
    "collect[0] bit0": "Game.has_item(\"sword\")",
    "collect[1] bit0": "Game.has_item(\"shield\")",
}

# actor each talk step is about, read out of the mined trigger prose
ACTOR_RE = re.compile(r"\b(Ba1|Ls1|Ji1|Zl1|ZL1|Aj1|Ko1|Ko2|Ob1|Yw1|Ym1|Ym2|Bm1|Dk)\b")
ID_HINTS = {"grandma": "Ba1", "aryll": "Ls1", "orca": "Ji1", "tetra": "Zl1", "aj_": "Aj1"}


def step_actor(step: dict) -> str | None:
    detail = (step.get("trigger") or {}).get("detail", "")
    m = ACTOR_RE.search(detail)
    if m:
        return "Zl1" if m.group(1).upper() == "ZL1" else m.group(1)
    for hint, actor in ID_HINTS.items():
        if step.get("id", "").startswith(hint):
            return actor
    return None


def bits(step: dict, key: str) -> list[str]:
    out = []
    for b in step.get(key) or []:
        t = str(b).split()[0]
        if t.startswith("0x"):
            out.append(t)
    return out


def tag_events(build: Path) -> dict[str, set[str]] | None:
    """scene key -> the event names its TagEv / AttTag volumes can order.

    A step mined as "tag" is only really reachable if some volume in that scene names its
    event: getEventNo() is params >> 24 into the stage's EVNT table (d_a_tag_event.cpp:19)."""
    if not build.exists():
        return None
    data = json.loads(build.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for key, scene in data.items():
        table = scene.get("event_table") or []
        names = set()
        for t in scene.get("tags") or []:
            if not str(t.get("actor", "")).startswith(("TagEv", "AttTag")):
                continue
            no = (int(t.get("params", 0)) >> 24) & 0xFF
            if no < len(table):
                names.add(str(table[no]))
        out[key] = names
    return out


def scene_key(step: dict, scenes: dict[str, set[str]]) -> str | None:
    stage = str(step.get("stage", ""))
    room = step.get("room")
    if room is not None and f"{stage}_r{room}" in scenes:
        return f"{stage}_r{room}"
    return stage if stage in scenes else None


def status(step: dict, scenes: dict[str, set[str]] | None = None) -> tuple[str, str]:
    scenes = SCENES if scenes is None else scenes
    """-> (state, why). state is ok / partial / missing."""
    kind = (step.get("trigger") or {}).get("kind", "")
    if kind not in IMPLEMENTED:
        return "missing", f"trigger kind '{kind}' has no mechanism"
    if kind == "talk" and not step_actor(step):
        return "partial", "talk step whose actor could not be identified"
    if step.get("stb") and not step.get("event"):
        return "partial", "cutscene with no event to launch it"
    unresolved = [
        b
        for b in (step.get("requires_bits") or [])
        if not str(b).startswith("0x") and str(b).strip() not in MODELLED_STATE
    ]
    if unresolved:
        return "partial", f"gated on non-bit state: {', '.join(str(u) for u in unresolved)}"
    if kind == "tag" and scenes is not None:
        key = scene_key(step, scenes)
        ev = str(step.get("event") or "")
        if key is None:
            return "partial", f"stage '{step.get('stage')}' is not in the build"
        if ev and ev not in scenes[key]:
            return "missing", f"no TagEv in {key} orders '{ev}' - the original drives it from actor code"
    if step.get("confidence") == "low":
        return "partial", "mined with low confidence"
    return "ok", IMPLEMENTED[kind]


def node_id(step: dict) -> str:
    return re.sub(r"\W", "_", step.get("id", "step"))


def label(step: dict) -> str:
    parts = [step.get("id", "?")]
    what = step.get("stb") or step.get("event")
    if what:
        parts.append(str(what))
    sets = bits(step, "sets_bits")
    if sets:
        parts.append("sets " + " ".join(sets))
    return "<br/>".join(p.replace('"', "'") for p in parts)


def chart(steps: list[dict], *, annotate: bool) -> str:
    lines = ["flowchart TD"]
    produced: dict[str, str] = {}       # bit -> the node that sets it
    for s in steps:
        for b in bits(s, "sets_bits"):
            produced.setdefault(b, node_id(s))
    for s in steps:
        nid = node_id(s)
        kind = (s.get("trigger") or {}).get("kind", "?")
        text = label(s)
        if annotate:
            state, _why = status(s)
            mark = {"ok": "OK", "partial": "PARTIAL", "missing": "MISSING"}[state]
            lines.append(f'    {nid}["{text}<br/><i>{kind} - {mark}</i>"]')
        else:
            lines.append(f'    {nid}["{text}<br/><i>{kind}</i>"]')
    prev = None
    for s in steps:
        nid = node_id(s)
        wired = False
        for b in bits(s, "requires_bits"):
            src = produced.get(b)
            if src and src != nid:
                lines.append(f"    {src} -- {b} --> {nid}")
                wired = True
        if not wired and prev is not None:
            lines.append(f"    {prev} -.-> {nid}")
        prev = nid
    if annotate:
        lines += [
            "    classDef ok fill:#dff5dd,stroke:#3a7d33;",
            "    classDef partial fill:#fff4d6,stroke:#a97f13;",
            "    classDef missing fill:#fadbd8,stroke:#a93226;",
        ]
        for state in ("ok", "partial", "missing"):
            ids = [node_id(s) for s in steps if status(s)[0] == state]
            if ids:
                lines.append(f"    class {','.join(ids)} {state};")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "story_chart.md"))
    args = ap.parse_args()
    data = json.loads(STORY.read_text(encoding="utf-8"))
    steps = data["steps"]
    global SCENES
    SCENES = tag_events(BUILD)
    if SCENES is None:
        print(f"note: {BUILD} is not built - tag steps are not cross-checked")

    counts = {"ok": 0, "partial": 0, "missing": 0}
    rows = []
    for s in steps:
        state, why = status(s)
        counts[state] += 1
        rows.append(
            f"| {s.get('id')} | {(s.get('trigger') or {}).get('kind','')} | "
            f"{step_actor(s) or ''} | {s.get('event') or ''} | {s.get('stb') or ''} | "
            f"{' '.join(bits(s,'requires_bits'))} | {' '.join(bits(s,'sets_bits'))} | "
            f"**{state}** | {why} |"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# Wind Waker opening: original flow vs. our remake\n\n"
        "Generated by `tools/ww_story_chart.py` from `gcrip/data/ww_story_outset.json`\n"
        "(mined from the zeldaret/tww decompilation, every step carrying file:line sources).\n"
        "Re-run it after changing the engine's trigger mechanisms.\n\n"
        f"**{counts['ok']} of {len(steps)} steps are reachable in the remake** "
        f"({counts['partial']} partial, {counts['missing']} missing).\n\n"
        "## 1. The original game\n\n```mermaid\n" + chart(steps, annotate=False) + "\n```\n\n"
        "## 2. The same flow in our remake\n\n"
        "Solid arrows are event-bit dependencies; dotted arrows are play order.\n\n"
        "```mermaid\n" + chart(steps, annotate=True) + "\n```\n\n"
        "## 3. Step by step\n\n"
        "| step | trigger | actor | event | cutscene | needs | sets | state | note |\n"
        "|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    print(f"{counts['ok']} ok / {counts['partial']} partial / {counts['missing']} missing -> {out}")


if __name__ == "__main__":
    main()
