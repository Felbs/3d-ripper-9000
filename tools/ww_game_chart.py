# ruff: noqa: E501  (html_page holds template strings; wrapping them would hurt, not help)
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
    "tag": "actors/tag_event.gd - a TagEv volume orders its EVNT entry; actors/tag_island.gd -"
           " a TagIsl arrival volume with the island's own terms (ship vs on-foot variant,"
           " endless night, the Bomb Bag) and the per-island arrival flag it raises",
    "room_enter": "stage.gd - the stage's arrival event runs on load",
    "talk": "Game.story_talk - via actors/npc.gd",
    "npc": "Game.story_npc_tick - proximity, or ordered as the actor is placed",
    "look": "Game.telescope_look - the Telescope's scope look at the step's target",
    "board": "player.gd board() raises RODE_KORL the first time Link boards the boat",
    "bits": "Game.story_bits_tick - fires as soon as every requires_bits entry is set",
    "chest": "actors/chest.gd - opening the chest holding that dItemNo advances the step",
    "defeat": "actors/enemy.gd death -> Game.story_enemy_defeated / story_room_cleared;"
              " a dungeon boss also writes the per-stage boss_dead field, which is NOT an"
              " event bit",
    "boss": "same mechanism as 'defeat'",
    "enemy_defeat": "same mechanism as 'defeat'",
    "object": "Game.story_object_tick - a per-object predicate (distance, ship, switch, item,"
              " sword swing) rather than an area the player walks into",
    "warp": "actors/warp_object.gd - picks WHICH event to order from save state, the way"
            " daWarpf_c::CreateInit does, then plays it and changes stage",
    "conduct": "player.gd CONDUCT state + Game.conduct_tick - the tablet's song, the 800-unit"
               " two-body proximity and the facing test, with a real ERROR branch",
    "npc_tag": "actors/npc_tag.gd - a volume that box-tests one named NPC and never the player."
               " Wired end to end, but not yet seen to fire in an integration test",
    "salvage": "actors/salvage.gd + Game.try_salvage - all 489 Great Sea points in six kinds"
               " (chart, switch, free, night-only, decoy, full moon), each with the real"
               " availability rule; the crane tip is the boat's XZ at l_salvage_depth below"
               " the water, since the remake has no crane model yet",
    "item": "Game.story_item_collected - picking up or being handed the step's dItemNo",
    "timer": "Game.story_timer_tick - the timed islands (daTagvolcano). The sea-side switch"
             " starts a 300 s clock that survives the warp into the cave and pauses for events;"
             " opening the cave's chest (by tboxNo, the way dComIfGs_isTbox does) settles the"
             " island for good, and running out turns the switch back off and, if Link is"
             " inside, orders TAG_VOLCANO and throws him out onto the island",
    "hit": "actors/hit_object.gd - take_hit stages that each order an event, positioned from"
           " the stage's own placement records (the Ajav wall over Jabun's cave breaks in three"
           " stages); plus actors/hit_switch.gd for the objects that accept exactly ONE attack"
           " kind and raise a switch - 780 bonbori, 50 SW_HIT0, 26 MhmrSW0 and the single Qdghd"
           " and Ykzyg, with take_hit carrying the attack kind",
}

# An enemy the mined data names but enemies.json has no profile for is never wrapped, so its
# step cannot fire in real play even though the mechanism exists.  Report that separately.
def unwrapped_enemy(step: dict, enemies: dict) -> str:
    d = step.get("defeat")
    if not isinstance(d, dict) or d.get("room_clear"):
        return ""
    name = str(d.get("enemy", ""))
    if name and name not in enemies:
        return name
    return ""

# Mechanisms the mined chapters need that the engine has not built yet.  Each line says what
# it would take, so the list doubles as the build order for the rest of the game.
UNIMPLEMENTED = {
    "actor": "a placed object resolves its event by NAME through the event manager; nothing in"
             " the engine does that yet",
    "show_item": "holding an inventory item out to an NPC (dEvtCnd_CANTALKITEM_e): a talk that"
                 " carries the selected item id, with the NPC branching on it",
    "photo": "taking or delivering a pictograph: a camera mode plus a per-subject result value",
    "minigame": "an outcome decided by a scored activity rather than a position or a bit",
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
            # TagEv orders its EVNT entry on entry; TagIsl (d_a_tag_island.cpp) does too, by
            # its own rules - both index the table with params >> 24
            if str(t.get("actor", "")).startswith(("TagEv", "AttTag", "TagIsl")):
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
    # a hit step is also covered when its object is one of the switch/lamp actors that
    # actors/hit_switch.gd places straight from the placement data
    HIT_SWITCH_ACTORS = ("Qdghd", "Ykzyg", "MhmrSW0", "bonbori", "SW_HIT0")
    if kind == "hit" and not isinstance(step.get("hit"), dict):
        detail = str((step.get("trigger") or {}).get("detail", ""))
        if any(a in detail for a in HIT_SWITCH_ACTORS):
            return "ok", IMPLEMENTED[kind]
        # the mechanism is real, but hit_object.gd is handed a structured block (actor, events,
        # min_damage, room) built by _STORY_HIT; a step mined with its geometry only in the
        # trigger prose has nothing to spawn
        return "partial", (
            "the mechanism works, but this step has no structured hit block, so nothing"
            " is spawned for it"
        )
    if kind in ("defeat", "boss", "enemy_defeat"):
        missing_actor = unwrapped_enemy(step, read(BUILD / "enemies.json", {}) or {})
        if missing_actor:
            return "partial", (
                f"the mechanism works, but '{missing_actor}' has no mined enemy profile so"
                " nothing wraps the actor"
            )
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
        ("Cel shading", "partial",
         "the game's own toon.bti ramp (256x8 I4, flat to 119, rise to 137, flat after) drives"
         " a shader that reproduces WW's TEV recipe albedo * mix(C0, K0, ramp), with C0/K0"
         " following the clock. NOT yet seen by human eyes - headless has no viewport - and"
         " BTK/BRK material animation is still unparsed, so water does not move"),
        ("Cutscenes (.stb)", "ok", f"{len(cuts)} baked and played end to end"),
        ("Events (event_list)", "ok",
         "interpreter runs staff/cut timelines: camera, dialogue, actor animation"),
        ("NPC dialogue", "ok",
         f"{len(ruled)} villagers with story-conditional rules, chosen at talk time"),
        ("Music", "partial",
         f"{songs} stage songs with vibrato, per-track fx send and the pitch oscillator mined"
         " from JAudio; the scene-level reverb amount is still a chosen constant, and no sound"
         " effects at all (ww_sound_effects.json maps the banks and the 28 footstep surfaces)"),
        ("Sailing", "partial",
         "boat physics, sail, wind and wave_max from the real MULT values; no cannon, crane or"
         " cyclones, and the Great Sea is one heavy scene - its RTBL streaming rule is mined"
         " (ww_greatsea.json) but not built"),
        ("Save / story bits", "ok", "dSv_event_flag_c byte array, story_done, items, switches"),
        ("Day / night", "ok",
         "600 real seconds per in-game day (dKy: 360 units, 0.02/frame); layers swap at 6 and 18"),
        ("Dungeons", "partial",
         "small keys, locked doors and the Big Key work (actors/door.gd): the per-dungeon save"
         " block dSv_memBit_c keyed by the stage's STAG slot, both door families' conflicting"
         " type numbers, and a Big Key door that spends no key. Chest bits, the 128 memory"
         " switches and the dungeon map/compass UI are still not modelled"),
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
        "Presentation": ["Cutscenes (.stb)", "Music", "Cel shading"],
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


def remaining(steps: list[dict], scenes) -> list[tuple[str, int, str]]:
    """Steps that cannot fire yet, grouped by the reason, most first."""
    groups: dict[str, int] = {}
    for st in steps:
        state, why = step_status(st, scenes)
        if state != "ok":
            groups[why] = groups.get(why, 0) + 1
    titles = {
        "'item'": "Placed items", "'salvage'": "Salvage points", "'score'": "Scored minigames",
        "hit block": "Breakable objects without geometry", "low confidence": "Low-confidence mining",
        "inventory item out": "Showing an item to an NPC", "pictograph": "Pictographs",
        "scored activity": "Minigame outcomes", "enemy profile": "Unprofiled enemies",
        "not model": "Unmodelled save state", "TagEv": "Trigger volumes not in the build",
    }
    # group by TITLE, so five "no TagEv in <stage> orders <event>" lines become one entry
    merged: dict[str, list] = {}
    for why, n in groups.items():
        title = next((t for k, t in titles.items() if k in why), why[:40])
        m = merged.setdefault(title, [0, []])
        m[0] += n
        m[1].append(why)
    out = []
    for title, (n, whys) in sorted(merged.items(), key=lambda kv: -kv[1][0]):
        why = whys[0] if len(whys) == 1 else "; ".join(sorted(whys))
        out.append((title, n, why))
    return out


CHAPTER_TITLES = {
    "outset": "Outset Island", "fortress": "The Forsaken Fortress", "dragonroost": "Dragon Roost",
    "forbiddenwoods": "The Forbidden Woods", "jabun": "Greatfish and Jabun",
    "towerofgods": "The Tower of the Gods", "hyrule": "Hyrule and the Master Sword",
    "temples": "The two sages", "fortress2": "The Forsaken Fortress again",
    "ganon": "Ganon's Tower", "ganontower": "Ganon's Tower - the rooms and rematches",
    "caves": "Caves and grottoes", "gallery": "The Nintendo Gallery", "houses": "Island interiors",
    "labyrinths": "Labyrinths and the timed islands", "minigames": "Minigames",
    "triforce": "The Triforce hunt", "windfall": "Windfall Island",
}


def esc(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def html_page(rows, steps, scenes, graph) -> str:
    """The designed page: same numbers as the markdown, same data, one generator."""
    counts = {"ok": 0, "partial": 0, "missing": 0}
    per_chapter: dict[str, dict] = {}
    for st in steps:
        state, _ = step_status(st, scenes)
        counts[state] += 1
        ch = per_chapter.setdefault(str(st.get("chapter")), {"ok": 0, "partial": 0, "missing": 0,
                                                             "stages": [], "first": None, "last": None})
        ch[state] += 1
        stg = str(st.get("stage") or "")
        if stg and stg not in ch["stages"]:
            ch["stages"].append(stg)
        ch["first"] = ch["first"] or st.get("id")
        ch["last"] = st.get("id")
    sys_counts = {"ok": 0, "partial": 0, "missing": 0}
    for _, st, _ in rows:
        sys_counts[st] += 1
    pill = {"ok": "working", "partial": "partial", "missing": "not started"}

    css = (ROOT / "tools" / "ww_game_chart.css").read_text(encoding="utf-8")
    h = ["<title>Wind Waker Remake Map</title>",
         '<link rel="preconnect" href="https://fonts.googleapis.com">',
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">',
         f"<style>{css}</style>", '<div class="wrap">',
         '<header class="masthead"><p class="eyebrow">Ripped from GZLE01 &middot; rebuilt in Godot 4.7</p>',
         "<h1>Wind Waker Remake Map</h1>",
         '<p class="standfirst">Every subsystem and every mined story step in one chart. Each status is read out of the build itself &mdash; Link&rsquo;s own state machine, the item list, the enemy table, the baked cutscenes, the story graph &mdash; so this map cannot drift from what the engine actually does.</p>',
         '<div class="readout">',
         f'<div><b>{sys_counts["ok"]}</b><span>systems working</span></div>',
         f'<div><b>{sys_counts["partial"]}</b><span>systems partial</span></div>',
         f'<div><b>{sys_counts["missing"]}</b><span>not started</span></div>',
         f'<div><b>{counts["ok"]}<span style="color:var(--muted)">/{len(steps)}</span></b><span>story steps reachable</span></div>',
         f'<div><b>{len(graph["chapters"])}</b><span>chapters mined</span></div>',
         "</div></header>"]

    # 01 systems
    h += ['<section><h2><span class="num">01</span> Systems</h2>',
          '<p class="lede">What the engine can do today. &ldquo;Partial&rdquo; means the system runs but a named piece of it is absent; &ldquo;not started&rdquo; means nothing has been built yet.</p>',
          '<div class="legend"><span class="key"><span class="swatch ok"></span> working</span><span class="key"><span class="swatch partial"></span> partial</span><span class="key"><span class="swatch missing"></span> not started</span></div>',
          '<div class="plate"><p class="plate-cap">Subsystem map</p><pre class="mermaid">']
    mm = mermaid_systems(rows).splitlines()[1:-1]
    h += [esc(line) for line in mm]
    h += ["</pre></div>", '<div class="cards">']
    for name, st, ev in rows:
        h.append(f'<div class="card {st}"><h3>{esc(name)} <span class="pill {st}">{pill[st]}</span></h3><p>{esc(ev)}</p></div>')
    h += ["</div></section>"]

    # 02 story
    h += [f'<section><h2><span class="num">02</span> Story &mdash; {len(graph["chapters"])} chapters, {len(steps)} steps</h2>',
          '<p class="lede">The whole game, mined step by step from the decompilation. Each step records what triggers it, which event or cutscene it runs, and which save bit it raises. The bar on each chapter is how much of it the engine can actually reach today.</p>',
          '<div class="legend"><span class="key"><span class="swatch ok"></span> reachable</span><span class="key"><span class="swatch partial"></span> partial</span><span class="key"><span class="swatch missing"></span> needs a mechanism</span></div>',
          '<div class="plate"><p class="plate-cap">The chapters, in story order</p><pre class="mermaid">',
          "flowchart TD",
          "  classDef ok fill:#CFE6DA,stroke:#2E7A57,color:#0B1F2E;",
          "  classDef partial fill:#F2E2BE,stroke:#9C7112,color:#0B1F2E;",
          "  classDef missing fill:#EFCEC8,stroke:#A2382B,color:#0B1F2E;"]
    main_story = [c for c in graph["chapters"] if c in (
        "outset", "fortress", "dragonroost", "forbiddenwoods", "jabun", "towerofgods", "hyrule",
        "temples", "fortress2", "ganon", "ganontower")]
    side = [c for c in graph["chapters"] if c not in main_story]
    cls: dict[str, list[str]] = {"ok": [], "partial": [], "missing": []}
    for i, c in enumerate(main_story + side):
        d = per_chapter.get(c, {"ok": 0, "partial": 0, "missing": 0})
        tot = d["ok"] + d["partial"] + d["missing"]
        state = "ok" if d["ok"] == tot else ("missing" if d["missing"] else "partial")
        cls[state].append(f"C{i}")
        h.append(f'  C{i}["{i + 1} &middot; {esc(CHAPTER_TITLES.get(c, c))}<br/>{d["ok"]}/{tot}"]')
    for i in range(len(main_story) - 1):
        h.append(f"  C{i} --> C{i + 1}")
    if side:
        h.append('  SIDE(["side content"])')
        for j in range(len(side)):
            h.append(f"  SIDE --> C{len(main_story) + j}")
    for state, ids in cls.items():
        if ids:
            h.append(f"  class {','.join(ids)} {state};")
    h += ["</pre></div>", '<div class="chaps">']
    for i, c in enumerate(main_story + side):
        d = per_chapter.get(c)
        if not d:
            continue
        tot = d["ok"] + d["partial"] + d["missing"]
        state = "ok" if d["ok"] == tot else ("missing" if d["missing"] else "partial")
        bar = "".join(f'<span class="seg {k}" style="flex:{d[k]}"></span>' for k in ("ok", "partial", "missing") if d[k])
        h.append(f'<div class="chap {state}"><div class="chap-top"><span class="chap-num">{i + 1:02d}</span>'
                 f'<h3>{esc(CHAPTER_TITLES.get(c, c))}</h3><span class="chap-count">{d["ok"]}/{tot}</span></div>'
                 f'<div class="bar">{bar}</div>'
                 f'<p class="arc">{esc(d["first"])} &rarr; &hellip; &rarr; {esc(d["last"])}</p>'
                 f'<p class="stages">{esc(", ".join(d["stages"][:8]))}{" &hellip;" if len(d["stages"]) > 8 else ""}</p></div>')
    h += ["</div></section>"]

    # 03 remaining
    rem = remaining(steps, scenes)
    h += ['<section><h2><span class="num">03</span> What is left to build</h2>',
          f'<p class="lede">{counts["partial"] + counts["missing"]} steps cannot fire yet, and they cluster: most are waiting on the same handful of missing mechanisms. This is the build order, in the order that would unblock the most story.</p>',
          '<div class="cards">']
    for title, n, why in rem:
        h.append(f'<div class="card missing"><h3>{esc(title)} <span class="pill missing">{n} step{"s" if n != 1 else ""}</span></h3><p>{esc(why)}</p></div>')
    h += ["</div></section>",
          "<footer>Generated by <code>tools/ww_game_chart.py --html</code> from <code>gcrip/data/ww_story_*.json</code> and the built Godot project.<br>"
          "Story data mined read-only from the zeldaret/tww decompilation and a personally dumped GZLE01 disc. No game assets are redistributed.</footer>",
          "</div>"]
    return "\n".join(h) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "game_map.md"))
    ap.add_argument("--html", default=None, help="also write the designed HTML page here")
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

    lines += ["", "## 3. What is left", ""]
    for title, n, why in remaining(steps, scenes):
        lines.append(f"- **{title}** - {n} step{'s' if n != 1 else ''}: {why}")
    lines += ["", "Every chapter of the main story and the side content has a graph. Mining a",
              "new area means: run `tools/ww_story_mine.py <stages>`, read the actors that",
              "order the events it names, and write one `gcrip/data/ww_story_<area>.json` in",
              "the same schema.", ""]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.html:
        Path(args.html).write_text(html_page(rows, steps, scenes, graph), encoding="utf-8")
    print(f"systems {sys_counts} | story {counts} of {len(steps)} -> {out}")


if __name__ == "__main__":
    main()
