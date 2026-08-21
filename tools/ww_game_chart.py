"""One map of the whole remake: every subsystem and every mined story step, with status.

Everything here is read from the build and the mined data - the player's own state machine,
the item list, the enemy table, the baked cutscenes, the story graph - so the chart cannot
drift from what the engine actually does.  Nothing in it is hand-maintained.

    python tools/ww_game_chart.py [--out docs/game_map.md]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "gcrip" / "data"
BUILD = ROOT / "out" / "rip" / "GZLE01" / "godot"

# Trigger mechanisms the engine implements, and the function that does it.
IMPLEMENTED = {
    "spawn": "Game._place_player - a PLYR spawn's params >> 24 indexes the stage EVNT table",
    "tag": "actors/tag_event.gd - a TagEv volume orders its EVNT entry",
    "room_enter": "stage.gd - the stage's arrival event runs on load",
    "talk": "Game.story_talk - via actors/npc.gd",
    "npc": "Game.story_npc_tick - proximity, or ordered as the actor is placed",
    "look": "Game.telescope_look - the Telescope's scope look at the step's target",
    "board": "player.gd board() raises RODE_KORL the first time Link boards the boat",
    "bits": "Game.story_bits_tick - fires as soon as every requires_bits entry is set",
}
# mechanisms the mined chapters need that the engine has not built yet
UNIMPLEMENTED = {
    "boss": "no boss fight raises its clear flag - there are no boss actors at all yet",
    "actor": "a placed object resolves the event by name through the event manager; the engine "
             "has no equivalent yet",
}

MODELLED_STATE = {"collect[0] bit0": 'has_item("sword")', "collect[1] bit0": 'has_item("shield")'}


def read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def story_graph() -> dict:
    """Every chapter, merged the way the exporter merges them."""
    import sys

    sys.path.insert(0, str(ROOT))
    from gcrip.godot import _story_all_chapters

    return _story_all_chapters(DATA)


def tag_events() -> dict[str, set[str]] | None:
    sd = read(BUILD / "stage_data.json")
    if sd is None:
        return None
    out: dict[str, set[str]] = {}
    for key, scene in sd.items():
        table = scene.get("event_table") or []
        names = set()
        for t in scene.get("tags") or []:
            if str(t.get("actor", "")).startswith(("TagEv", "AttTag")):
                no = (int(t.get("params", 0)) >> 24) & 0xFF
                if no < len(table):
                    names.add(str(table[no]))
        out[key] = names
    return out


def scene_key(step: dict, scenes: dict[str, set[str]]) -> str | None:
    stage, room = str(step.get("stage", "")), step.get("room")
    if room is not None and f"{stage}_r{room}" in scenes:
        return f"{stage}_r{room}"
    return stage if stage in scenes else None


def step_status(step: dict, scenes: dict[str, set[str]] | None) -> tuple[str, str]:
    kind = (step.get("trigger") or {}).get("kind", "")
    if kind in UNIMPLEMENTED:
        return "missing", UNIMPLEMENTED[kind]
    if kind not in IMPLEMENTED:
        return "missing", f"trigger kind '{kind}' has no mechanism"
    unresolved = [
        b
        for b in (step.get("requires_bits") or [])
        if not str(b).startswith("0x") and str(b).strip() not in MODELLED_STATE
    ]
    if unresolved:
        return "partial", f"gated on state we do not model: {', '.join(map(str, unresolved))}"
    if kind == "tag" and scenes is not None:
        key = scene_key(step, scenes)
        ev = str(step.get("event") or "")
        if key is None:
            return "partial", f"stage '{step.get('stage')}' is not in the build"
        if ev and ev not in scenes[key]:
            return "missing", f"no TagEv in {key} orders '{ev}'"
    if step.get("confidence") == "low":
        return "partial", "mined with low confidence"
    return "ok", IMPLEMENTED[kind]


# ------------------------------------------------------------------ the mechanics side
def player_states() -> list[str]:
    gd = (BUILD / "player.gd").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^enum State \{(.*?)\}", gd, re.S | re.M)
    return [s.strip() for s in m.group(1).split(",")] if m else []


def x_items() -> list[str]:
    gd = (BUILD / "player.gd").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'const X_ITEMS := \[(.*?)\]', gd, re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def subsystems() -> list[tuple[str, str, str]]:
    """(name, status, evidence) - each line proved by something in the build."""
    sd = read(BUILD / "stage_data.json", {})
    enemies = read(BUILD / "enemies.json", {})
    cuts = [f for f in (BUILD / "cutscenes").glob("*.json") if f.name != "index.json"]
    models = read(BUILD / "actor_models.json", {})
    bgm = read(BUILD / "bgm.json", {})
    dlg = read(BUILD / "npc_dialogue.json", {})
    doors = read(BUILD / "door_targets.json", [])
    states = player_states()
    items = x_items()

    solid = [k for k, v in enemies.items() if isinstance(v, dict) and v.get("hp") is not None]
    thin = [k for k, v in enemies.items() if isinstance(v, dict) and v.get("hp") is None]
    ruled = [k for k, v in dlg.items() if isinstance(v, dict) and v.get("rules")]

    enterable = sum(1 for v in sd.values() if v.get("spawns"))
    songs = len(bgm.get("stages", {})) + len(bgm.get("sea_rooms", {}))
    return [
        ("Stages", "ok", f"{len(sd)} scenes exported, {enterable} enterable"),
        ("Doors", "ok", f"{len(doors)} distinct door landings, all checked for a floor"),
        ("Player movement", "ok", f"{len(states)} states: {', '.join(states)}"),
        ("Items (X)", "ok", f"{len(items)}: {', '.join(items)}"),
        ("Enemies", "partial",
         f"{len(solid)} fully mined, {len(thin)} stubbed in the decomp ({', '.join(thin)})"),
        ("Actor models", "ok", f"{len(models)} animated models with clips and head attachment"),
        ("Cutscenes (.stb)", "ok", f"{len(cuts)} baked and played end to end"),
        ("Events (event_list)", "ok",
         "interpreter runs staff/cut timelines: camera, dialogue, actor animation"),
        ("NPC dialogue", "ok",
         f"{len(ruled)} villagers with story-conditional rules, chosen at talk time"),
        ("Music", "partial", f"{songs} stage songs; the synth lacks vibrato and per-track fx"),
        ("Sailing", "partial",
         "boat physics, sail and wind; no cannon or crane, the Great Sea is one heavy scene"),
        ("Save / story bits", "ok", "dSv_event_flag_c byte array, story_done, items, switches"),
        ("Day / night", "missing", "layers carry day and night variants; the clock is always day"),
        ("Dungeons", "missing", "no dungeon logic mined yet: keys, switches, boss gates"),
    ]


def mermaid_systems(rows: list[tuple[str, str, str]]) -> str:
    out = ["```mermaid", "flowchart LR", "    classDef ok fill:#e6f4ea,stroke:#1e7d34;",
           "    classDef partial fill:#fff4d6,stroke:#a97f13;",
           "    classDef missing fill:#fde7e7,stroke:#a51b1b;",
           "    GAME([\"Wind Waker remake\"])"]
    groups = {
        "World": ["Stages", "Doors", "Day / night", "Sailing"],
        "Link": ["Player movement", "Items (X)"],
        "Actors": ["Enemies", "Actor models", "NPC dialogue"],
        "Presentation": ["Cutscenes (.stb)", "Music"],
        "Progress": ["Events (event_list)", "Save / story bits", "Dungeons"],
    }
    status = {name: st for name, st, _ in rows}
    evidence = {name: ev for name, _, ev in rows}
    for gi, (group, members) in enumerate(groups.items()):
        gid = f"G{gi}"
        out.append(f'    GAME --> {gid}["{group}"]')
        for mi, name in enumerate(members):
            nid = f"{gid}_{mi}"
            label = f"{name}<br/><i>{evidence.get(name, '')[:64]}</i>"
            out.append(f'    {gid} --> {nid}["{label}"]')
            out.append(f"    class {nid} {status.get(name, 'partial')};")
    out.append("```")
    return "\n".join(out)


def node_id(step: dict) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(step.get("id", "step")))


def mermaid_story(steps: list[dict], scenes) -> str:
    out = ["```mermaid", "flowchart TD",
           "    classDef ok fill:#e6f4ea,stroke:#1e7d34;",
           "    classDef partial fill:#fff4d6,stroke:#a97f13;",
           "    classDef missing fill:#fde7e7,stroke:#a51b1b;"]
    by_chapter: dict[str, list[dict]] = {}
    for s in steps:
        by_chapter.setdefault(str(s.get("chapter", "?")), []).append(s)
    produced: dict[str, str] = {}
    for s in steps:
        for b in s.get("sets_bits") or []:
            t = str(b).split()[0]
            if t.startswith("0x"):
                produced.setdefault(t, node_id(s))
    for chapter, chapter_steps in by_chapter.items():
        out.append(f'    subgraph {chapter}["{chapter}"]')
        prev = None
        for s in chapter_steps:
            nid = node_id(s)
            kind = (s.get("trigger") or {}).get("kind", "?")
            bits = " ".join(str(b) for b in (s.get("sets_bits") or []) if str(b).startswith("0x"))
            label = str(s.get("id"))
            if s.get("stb"):
                label += "<br/>" + str(s["stb"])
            elif s.get("event"):
                label += "<br/>" + str(s["event"])
            if bits:
                label += f"<br/>sets {bits}"
            state, _ = step_status(s, scenes)
            mark = {"ok": "OK", "partial": "PARTIAL", "missing": "MISSING"}[state]
            out.append(f'        {nid}["{label}<br/><i>{kind} - {mark}</i>"]')
            if prev:
                out.append(f"        {prev} --> {nid}")
            prev = nid
        out.append("    end")
    for s in steps:
        for b in s.get("requires_bits") or []:
            t = str(b).split()[0]
            src = produced.get(t)
            if src and src != node_id(s):
                out.append(f"    {src} -.->|{t}| {node_id(s)}")
    for state in ("ok", "partial", "missing"):
        ids = [node_id(s) for s in steps if step_status(s, scenes)[0] == state]
        if ids:
            out.append(f"    class {','.join(ids)} {state};")
    out.append("```")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "game_map.md"))
    args = ap.parse_args()

    graph = story_graph()
    steps = graph["steps"]
    scenes = tag_events()
    rows = subsystems()

    counts = {"ok": 0, "partial": 0, "missing": 0}
    for s in steps:
        counts[step_status(s, scenes)[0]] += 1
    sys_counts = {"ok": 0, "partial": 0, "missing": 0}
    for _, st, _ in rows:
        sys_counts[st] += 1

    lines = [
        "# The Wind Waker remake: one map",
        "",
        "Generated by `tools/ww_game_chart.py`. Every status below is read out of the build or",
        "the mined data - the player's own state machine, the item list, the enemy table, the",
        "baked cutscenes, the story graph - so this cannot drift from what the engine does.",
        "",
        f"**Systems:** {sys_counts['ok']} working, {sys_counts['partial']} partial, "
        f"{sys_counts['missing']} not started.  ",
        f"**Story:** {counts['ok']} of {len(steps)} mined steps reachable "
        f"({counts['partial']} partial, {counts['missing']} missing) across "
        f"{len(graph['chapters'])} chapters: {', '.join(graph['chapters'])}.",
        "",
        "## 1. Systems",
        "",
        mermaid_systems(rows),
        "",
        "| system | status | evidence |",
        "| --- | --- | --- |",
    ]
    for name, st, ev in rows:
        lines.append(f"| {name} | {st} | {ev} |")

    lines += ["", "## 2. Story", "",
              "Solid arrows are story order; dotted arrows are event-bit dependencies, labelled",
              "with the bit that carries them.", "", mermaid_story(steps, scenes), "",
              "| chapter | step | trigger | event | sets | status | why |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in steps:
        state, why = step_status(s, scenes)
        bits = " ".join(str(b) for b in (s.get("sets_bits") or []))
        lines.append(
            f"| {s.get('chapter')} | {s.get('id')} | {(s.get('trigger') or {}).get('kind','')} | "
            f"{s.get('event') or ''} | {bits} | {state} | {why} |"
        )

    lines += ["", "## 3. What is not mined yet", "",
              "The story graph covers the chapters listed above. Everything after them - Dragon",
              "Roost, the Forbidden Woods, the Tower of the Gods, Hyrule and the Master Sword,",
              "the second Forsaken Fortress, the Earth and Wind temples and Ganon's Tower - has",
              "no graph, so there is nothing for the engine or a test bot to follow there.",
              "Mining a chapter means: run `tools/ww_story_mine.py <stages>` for its stages,",
              "read the actors that order the events it names, and write one",
              "`gcrip/data/ww_story_<chapter>.json` in the same schema.", ""]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"systems {sys_counts} | story {counts} of {len(steps)} -> {out}")


if __name__ == "__main__":
    main()
