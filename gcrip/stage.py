"""Recompile a whole Wind Waker stage into one level glTF.

    gcrip stage out/rip/GZLE01 M_NewD2 [--rooms 0,1] [--iso PATH] [--layers]
    gcrip stage out/rip/GZLE01 --list

Reads the stage's placement files (stage.dzs + Room*/room.dzr) straight from the disc
image, resolves each placed actor to a model that `gcrip rip` already exported, and
writes <ripdir>/stages/<stage>/<stage>.gltf: room geometry placed by the MULT room
table plus one instance per actor (world-space position, Y rotation, SCOB scale).

What doesn't end up in the level (all counted in <stage>_report.json):
  - logic actors (tags, switches, triggers, Tingle Tuner hooks) - they have no model,
    but every one of them is still recorded: "tags" for Tag*/AttTag*/agb*, "logic" for
    the rest (switches, salvage points, Ajav...), same fields either way
  - vegetation (grass/flowers/trees) and some effects - drawn from display lists
    embedded in the game executable, not from any archive
  - actors whose name we still can't map to an archive: counted in "unresolved" and
    listed in "unresolved_names", AND kept in "logic" with "unresolved": true, so a
    placement on the disc can never disappear just because we don't know the name
"""

from __future__ import annotations

import contextlib
import json
import re
import struct
import time
from collections import Counter
from pathlib import Path

from gcrip.data.ww_actors import (
    CHEST_MODELS,
    CHEST_PREFIXES,
    CODE_DRAWN_NAMES,
    CODE_DRAWN_PREFIXES,
    KNOB_PAIR,
    NO_MODEL_NAMES,
    NO_MODEL_PREFIXES,
    STAGE_LOCAL_MODELS,
    WW_ACTORS,
)
from gcrip.disc.fst import parse_fst, parse_header
from gcrip.disc.image import DiscImage
from gcrip.export.gltf_merge import LevelBuilder
from gcrip.formats import dzb as dzb_mod
from gcrip.formats import dzs as dzs_mod
from gcrip.formats import rarc, yay0, yaz0

_ROOM_RE = re.compile(r"Room(\d+)\.arc$", re.IGNORECASE)


class _ModelIndex:
    """Resolve (archive, model) references against a finished rip."""

    def __init__(self, rip_dir: Path):
        self.rip_dir = rip_dir
        data = json.loads((rip_dir / "rip_results.json").read_text(encoding="utf-8"))
        models = data["models"]
        by_path = {m["path"]: m for m in models}
        self.by_key: dict[tuple[str, str], str] = {}  # (arc.lower, model stem.lower) -> out_rel
        self.best_in_arc: dict[str, tuple[int, str]] = {}  # arc.lower -> (tris, out_rel)
        # stage name -> room_no -> [out_rel, ...] (room geometry, every model in Room<N>.arc)
        self.rooms: dict[str, dict[int, list[str]]] = {}
        for m in models:
            out_rel = m.get("out_rel")
            tris = m.get("triangles", 0)
            if not out_rel and m.get("duplicate_of"):
                orig = by_path.get(m["duplicate_of"])
                out_rel = orig.get("out_rel") if orig else None
                tris = orig.get("triangles", 0) if orig else 0
            if not out_rel:
                continue
            mo = re.match(r"files/res/Object/([^/]+)\.arc/.*/([^/]+)\.(bdl|bmd)$", m["path"])
            ms = re.match(r"files/res/Stage/([^/]+)/[^/]+\.arc/.*/([^/]+)\.(bdl|bmd)$", m["path"])
            if mo:
                key, stem = mo.group(1).lower(), mo.group(2).lower()
                best = self.best_in_arc.get(key)
                if best is None or tris > best[0]:
                    self.best_in_arc[key] = (tris, out_rel)
            elif ms:
                key, stem = f"stage:{ms.group(1)}", ms.group(2).lower()
                mr = re.match(r"files/res/Stage/[^/]+/Room(\d+)\.arc/", m["path"])
                if mr:
                    stage_rooms = self.rooms.setdefault(ms.group(1), {})
                    stage_rooms.setdefault(int(mr.group(1)), []).append(out_rel)
            else:
                continue
            self.by_key.setdefault((key, stem), out_rel)

    def find(self, arc: str, model: str | None) -> Path | None:
        """model is a path inside the archive ('bdlm/kb.bdl') or None for 'biggest'."""
        arc = arc.lower()
        if model:
            stem = Path(model).stem.lower()
            rel = self.by_key.get((arc, stem))
            if rel:
                return self.rip_dir / rel
        best = self.best_in_arc.get(arc)
        return self.rip_dir / best[1] if best else None

    def find_stage_local(self, stage: str, name: str) -> Path | None:
        """Match a door/prop name against the stage's own Stage.arc models."""
        rel = self.by_key.get((f"stage:{stage}", name.lower()))
        return self.rip_dir / rel if rel else None


def _bridge_spans(placements, paths, mult, offset) -> list[dict]:
    """Resolve every `bridge` actor into the span its PATH describes.

    d_a_bridge.cpp:1450-1479: pathId = (params >> 16) & 0xFF, 0xFF fails to create; points
    [0] and [1] of that path are the two ends; plank spacing is (47 + (len > 1300 ? 3 : 0))
    * 1.5 and a bridge needing 50 or more planks refuses to spawn.  Path points are
    world-space, like actor positions, so only the export offset applies.
    """
    import math

    out: list[dict] = []
    seen: set[tuple] = set()
    for room_no, pl, _scls in placements:
        if pl.name != "bridge":
            continue
        path_id = (pl.params >> 16) & 0xFF
        runs = paths.get(room_no) or paths.get(None) or []
        if path_id == 0xFF or path_id >= len(runs):
            continue
        pts = runs[path_id].points
        if len(pts) < 2:
            continue
        # path points are world-space like actor positions - MULT moves only room geometry
        # (dzs.py's header note), so the export offset is the whole transform
        ends = [[px - offset[0], py, pz - offset[2]] for px, py, pz in pts[:2]]
        key = (round(ends[0][0]), round(ends[0][2]), round(ends[1][0]), round(ends[1][2]))
        if key in seen:      # the same bridge repeats on every story layer
            continue
        seen.add(key)
        dx = ends[1][0] - ends[0][0]
        dy = ends[1][1] - ends[0][1]
        dz = ends[1][2] - ends[0][2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        spacing = (47.0 + (3.0 if length > 1300.0 else 0.0)) * 1.5
        planks = int(length / spacing)
        if planks >= 50 or planks < 2:   # the game refuses this one too
            continue
        out.append({
            "room": room_no,
            "a": [round(v, 2) for v in ends[0]],
            "b": [round(v, 2) for v in ends[1]],
            "planks": planks,
            "spacing": round(spacing, 2),
            "type": pl.params & 0xFF,
        })
    return out


class _Disc:
    def __init__(self, iso: Path):
        self.img = DiscImage(iso)
        hdr = parse_header(self.img.read(0, 0x2450))
        self.game_id = hdr.game_id
        self.entries = {
            e.path: e
            for e in parse_fst(self.img.read(hdr.fst_offset, hdr.fst_size))
            if not e.is_dir
        }

    def stages(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in self.entries:
            m = re.match(r"res/Stage/([^/]+)/([^/]+\.arc)$", p)
            if m:
                out.setdefault(m.group(1), []).append(m.group(2))
        return out

    def read_inner(self, arc_path: str, suffix: str) -> bytes | None:
        e = self.entries.get(arc_path)
        if e is None:
            return None
        blob = self.img.read(e.offset, e.size)
        if blob[:4] == b"Yaz0":
            blob = yaz0.decompress(blob)
        elif blob[:4] == b"Yay0":
            blob = yay0.decompress(blob)
        arc = rarc.parse(blob)
        for f in arc.files:
            if f.path.lower().endswith(suffix.lower()):
                return arc.read(blob, f)
        return None

    def all_scls(self) -> dict[str, list]:
        """stage name -> its exit entries (stage.dzs + every room.dzr), file order."""
        if not hasattr(self, "_scls_cache"):
            cache: dict[str, list] = {}
            for name, arcs in self.stages().items():
                entries = []
                for arc in sorted(arcs):
                    suffix = "stage.dzs" if arc == "Stage.arc" else "room.dzr"
                    raw = self.read_inner(f"res/Stage/{name}/{arc}", suffix)
                    if raw:
                        with contextlib.suppress(ValueError, IndexError):
                            entries += dzs_mod.parse(raw).scls
                cache[name] = entries
            self._scls_cache = cache
        return self._scls_cache

    def incoming_exits(self, stage_name: str) -> list[tuple[str, int, int]]:
        """[(other_stage, room, spawn_id), ...]: every exit on the disc that ARRIVES in
        stage_name. A door near that arrival spawn leads back into other_stage."""
        out = set()
        for other, entries in self.all_scls().items():
            if other == stage_name:
                continue
            for e in entries:
                if e.dest_stage == stage_name:
                    out.add((other, e.room, e.spawn))
        return sorted(out)

    def close(self):
        self.img.close()


def _find_iso(rip_dir: Path, iso: Path | None) -> Path:
    if iso:
        if not Path(iso).exists():
            raise SystemExit(f"--iso {iso} does not exist")
        return Path(iso)
    manifest = rip_dir / "disc_manifest.json"
    if not manifest.exists():
        raise SystemExit(
            f"{rip_dir.resolve()} has no disc_manifest.json - pass the rip folder of a "
            f"finished rip (paths are relative to the current directory: {Path.cwd()}; "
            f'e.g. gcrip stage "Z:/3d ripper/out/rip/GZLE01" M_NewD2)'
        )
    filename = json.loads(manifest.read_text(encoding="utf-8"))["image"]["filename"]
    dirs = [Path.cwd() / "roms", Path.cwd(), rip_dir]
    for anc in rip_dir.resolve().parents:  # e.g. out/rip/GZLE01 -> <project>/roms
        dirs += [anc / "roms", anc]
    for cand_dir in dirs:
        cand = cand_dir / filename
        if cand.exists():
            return cand
    raise SystemExit(
        f"disc image {filename!r} not found (looked in ./roms, the current directory and "
        f"every roms/ folder above {rip_dir.resolve()}) - pass --iso PATH"
    )


def _classify(name: str) -> str | None:
    # exact names first: a prefix test would let short ones swallow their neighbours
    # ("sea" would eat "Search"), and these were each traced to a specific actor.
    if name in NO_MODEL_NAMES:
        return "logic"
    if name in CODE_DRAWN_NAMES:
        return "code_drawn"
    low = name.lower()
    if low.startswith(NO_MODEL_PREFIXES):
        return "logic"
    if low.startswith(CODE_DRAWN_PREFIXES):
        return "code_drawn"
    return None


def build_stage(
    rip_dir: Path,
    stage_name: str,
    *,
    iso: Path | None = None,
    rooms: list[int] | None = None,
    layers: bool = False,
    spawns: bool = False,
    rigs: bool = False,
    world: bool = False,
    layer: int | None = None,
    out_dir: Path | None = None,
    quiet: bool = False,
) -> dict:
    """layer: place only this one story layer; the default (None) places EVERY layer and
    records each actor's layer, so the engine can switch sets as the story advances."""
    t0 = time.monotonic()
    rip_dir = Path(rip_dir)
    disc = _Disc(_find_iso(rip_dir, iso))
    try:
        return _build(
            disc, rip_dir, stage_name, rooms, layers, spawns, rigs, world, out_dir, quiet, t0,
            layer=layer,
        )
    finally:
        disc.close()


def _build(
    disc, rip_dir, stage_name, rooms, layers, spawns, rigs, world, out_dir, quiet, t0,
    layer: int | None = None,
) -> dict:
    stages = disc.stages()
    if stage_name not in stages:
        close = [s for s in stages if stage_name.lower() in s.lower()]
        hint = f" (did you mean {', '.join(close[:5])}?)" if close else ""
        raise SystemExit(f"stage {stage_name!r} not on this disc{hint}")

    index = _ModelIndex(rip_dir)
    if out_dir is None:  # room-filtered builds get their own folder (don't clobber the full stage)
        suffix = "_r" + "-".join(str(r) for r in rooms) if rooms else ""
        out_dir = rip_dir / "stages" / f"{stage_name}{suffix}"
    out_dir = Path(out_dir)
    builder = LevelBuilder(out_dir / f"{stage_name}.gltf", flatten=not rigs)

    # ---- placement data (each placement carries its exit table: room SCLS, else stage's)
    stage_arcs = stages[stage_name]
    mult: dict[int, dzs_mod.RoomTransform] = {}
    placements: list[tuple[int | None, dzs_mod.Placement, list]] = []
    stage_scls: list = []
    own_scls: list = []
    ship_pts: list[dict] = []  # SHIP chunk: King of Red Lions mooring points
    tag_recs: list[dict] = []  # invisible trigger actors (TagEv, AttTag, TagMsg...)
    logic_recs: list[dict] = []  # every other model-less actor (switches, salvage, Ajav)
    event_table: list[str] = []  # stage.dzs EVNT names (TagEv params >> 24 indexes them)
    room_sets: list[dict] = []  # RTBL: which rooms stay resident together
    paths: dict[int | None, list] = {}  # room -> PATH/RPAT runs (actors index them by id)
    cameras: list[dict] = []  # CAMR/RCAM: the camera type a region switches to
    cam_arrows: list[dict] = []  # AROB/RARO: fixed eye points those regions point at
    if "Stage.arc" in stage_arcs:
        raw = disc.read_inner(f"res/Stage/{stage_name}/Stage.arc", "stage.dzs")
        if raw:
            d = dzs_mod.parse(raw)
            mult = d.mult
            stage_scls = d.scls
            event_table = list(d.events)
            room_sets = [vars(rs) for rs in d.room_sets]
            cameras += [vars(c) for c in d.cameras]
            cam_arrows += [
                {**vars(a), "pos": list(a.pos), "yaw_deg": a.yaw_deg, "pitch_deg": a.pitch_deg}
                for a in d.cam_arrows
            ]
            own_scls += d.scls
            paths[None] = d.paths
            placements += [(None, p, stage_scls) for p in d.placements]
    room_nos = []
    for arc_name in sorted(stage_arcs):
        m = _ROOM_RE.match(arc_name)
        if not m:
            continue
        room_no = int(m.group(1))
        if rooms is not None and room_no not in rooms:
            continue
        room_nos.append(room_no)
        raw = disc.read_inner(f"res/Stage/{stage_name}/{arc_name}", "room.dzr")
        if raw:
            d = dzs_mod.parse(raw)
            own_scls += d.scls
            paths[room_no] = d.paths
            scls = d.scls or stage_scls
            placements += [(room_no, p, scls) for p in d.placements]
            ship_pts += [
                {"room": room_no, "id": sp.ship_id, "pos": list(sp.pos),
                 "rot_y_deg": round(sp.rot_y_deg, 2)}
                for sp in d.ships
            ]
            # RCAM/RARO: most authored cameras are per ROOM, not per stage - the stage-level
            # CAMR/AROB pair is only a fraction of the 574 on the disc
            cameras += [{**vars(c), "room": room_no} for c in d.cameras]
            cam_arrows += [
                {**vars(a), "room": room_no, "pos": list(a.pos),
                 "yaw_deg": a.yaw_deg, "pitch_deg": a.pitch_deg}
                for a in d.cam_arrows
            ]

    # ---- room geometry (already ripped; MULT places it)
    room_models = 0
    room_node_ids: list[int] = []  # recentring anchors: rooms, not far-flung actors
    for room_no in room_nos:
        t = mult.get(room_no)
        for rel in index.rooms.get(stage_name, {}).get(room_no, []):
            idx = builder.add_instance(
                rip_dir / rel,
                f"Room{room_no}/{Path(rel).stem}",
                translation=(t.trans_x, 0.0, t.trans_z) if t else (0.0, 0.0, 0.0),
                rot_y_deg=t.rot_y_deg if t else 0.0,
                group=f"Room{room_no}",
            )
            if idx is not None:
                room_models += 1
                room_node_ids.append(idx)
    if not room_models and not quiet:
        print(f"warning: no ripped room models found for {stage_name} under {rip_dir}")

    # ---- actors
    counts = Counter()
    spawn_pts = []  # PLYR entries: where the game can place the player
    actor_recs = []  # every placed actor instance: node name + params (for behaviours)
    unresolved = Counter()
    skipped_names = Counter()
    door_pts: list[dict] = []
    for room_no, p, _scls in placements:
        if rooms is not None and room_no is None:
            # a --rooms build wants just those rooms; stage-wide actors (sea: ships,
            # salvage points...) live all over the map
            counts["stage_wide_skipped"] += 1
            continue
        if p.layer >= 0 and layer is not None and not layers and p.layer != layer:
            counts["layered_skipped"] += 1
            continue
        if p.chunk in ("DOOR", "TGDR") or p.name.upper().startswith("KNOB"):
            door_pts.append({"room": room_no, "pos": list(p.pos), "rot": round(p.rot_y_deg, 2)})
        if p.chunk == "PLYR":
            spawn_pts.append(
                {
                    # stage-wide spawns name their room in params bits 0-5
                    "room": room_no if room_no is not None else p.params & 0x3F,
                    "id": p.rot[2] & 0xFF,  # PLYR spawn id lives in z_rot's low byte
                    # params >> 24 indexes the stage EVNT table: arriving auto-plays it
                    "event": (p.params >> 24) & 0xFF,
                    "params": p.params,
                    "pos": list(p.pos),
                    "rot_y_deg": round(p.rot_y_deg, 2),
                }
            )
            if not spawns:
                counts["spawns_skipped"] += 1
                continue
            pair_list = [("Link", "bdl/cl.bdl")]
        elif p.name.lower().startswith(CHEST_PREFIXES):
            pair_list = [CHEST_MODELS.get((p.params >> 20) & 0xF, CHEST_MODELS[0])]
        elif p.name.upper().startswith("KNOB"):
            pair_list = [KNOB_PAIR]
        else:
            cat = _classify(p.name)
            if cat:
                counts[cat] += 1
                skipped_names[p.name] += 1
                # no model to place, but the placement is the only record of WHERE the
                # thing is - keep it either way, never drop it on the floor
                rec = {
                    "actor": p.name,
                    "chunk": p.chunk,
                    "params": p.params,
                    "rot": list(p.rot),
                    "room": room_no,
                    "layer": p.layer,
                    "pos": list(p.pos),
                    "rot_y_deg": round(p.rot_y_deg, 2),
                    "scale": list(p.scale),
                }
                if p.name.startswith(("Tag", "AttTag", "agb")):
                    tag_recs.append(rec)  # player triggers: the engine's tag pass reads these
                else:
                    logic_recs.append(rec)  # switches, salvage points, the Jabun wall...
                continue
            pair_list = WW_ACTORS.get(p.name)
            if pair_list is None:
                # bare archive-name match, with and without trailing digits
                base = re.sub(r"\d+$", "", p.name)
                pair_list = [(p.name, None), (base, None)] if base else [(p.name, None)]

        target = None
        for arc, model in pair_list:
            target = index.find(arc, model)
            if target:
                break
        if target is None:  # doors/props shipped inside this stage's own Stage.arc
            target = index.find_stage_local(
                stage_name, STAGE_LOCAL_MODELS.get(p.name, p.name)
            )
        if target is None:
            counts["unresolved"] += 1
            unresolved[p.name] += 1
            # we don't know what model this name wants - but the placement is still the
            # only record that something stands HERE.  Keep it beside the other
            # model-less actors, flagged, instead of dropping it on the floor.
            logic_recs.append(
                {
                    "actor": p.name,
                    "chunk": p.chunk,
                    "params": p.params,
                    "rot": list(p.rot),
                    "room": room_no,
                    "layer": p.layer,
                    "pos": list(p.pos),
                    "rot_y_deg": round(p.rot_y_deg, 2),
                    "scale": list(p.scale),
                    "unresolved": True,
                }
            )
            continue

        group = f"Room{room_no}_actors" if room_no is not None else "Stage_actors"
        node_name = f"{p.name}.{counts['placed']}"
        idx = builder.add_instance(
            target,
            node_name,
            translation=p.pos,
            rot_y_deg=p.rot_y_deg,
            scale=p.scale,
            group=group,
        )
        counts["placed" if idx is not None else "empty_model"] += 1
        if idx is not None:
            actor_recs.append(
                {
                    "node": node_name,
                    "actor": p.name,
                    "chunk": p.chunk,
                    "params": p.params,
                    "rot": list(p.rot),
                    "room": room_no,
                    "layer": p.layer,
                    "pos": list(p.pos),
                    "rot_y_deg": round(p.rot_y_deg, 2),
                    "scale": list(p.scale),
                    "model": str(target.relative_to(rip_dir).as_posix()),
                }
            )

    exits = _bind_exits(disc, stage_name, own_scls, door_pts, spawn_pts)
    offset = (0.0, 0.0, 0.0) if world else builder.recenter(anchor=room_node_ids)
    out_path = builder.save()
    collision = _build_collision(disc, stage_name, room_nos, out_dir, offset)
    try:  # put the level on report.html (its Levels section scans stages/)
        from gcrip.rip import load_results, write_report

        write_report(load_results(rip_dir))
    except Exception:  # noqa: BLE001, S110 - a broken report must not fail the build
        pass
    seconds = round(time.monotonic() - t0, 1)
    report = {
        "stage": stage_name,
        "rooms": room_nos,
        "room_models": room_models,
        "placements": len(placements),
        "placed": counts["placed"],
        "logic_skipped": counts["logic"],
        "code_drawn_skipped": counts["code_drawn"],
        "layered_skipped": counts["layered_skipped"],
        "spawns_skipped": counts["spawns_skipped"],
        "unresolved": counts["unresolved"],
        "unresolved_names": dict(unresolved.most_common()),
        "unique_models": builder.stats.models,
        "instances": builder.stats.instances,
        "triangles": builder.stats.triangles,
        "world_offset": list(offset),
        "collision": collision,
        "exits": [
            {**e, "pos": [e["pos"][0] - offset[0], e["pos"][1], e["pos"][2] - offset[2]]}
            for e in exits
        ],
        # room-local spawns first: with --rooms, stage-wide PLYR entries can sit on
        # other islands and would drop the player in the middle of the ocean
        "actors": [
            {**a, "pos": [a["pos"][0] - offset[0], a["pos"][1], a["pos"][2] - offset[2]]}
            for a in actor_recs
        ],
        "spawns": [
            {**sp, "pos": [sp["pos"][0] - offset[0], sp["pos"][1], sp["pos"][2] - offset[2]]}
            for sp in sorted(spawn_pts, key=lambda sp: sp["room"] is None)
        ],
        "ships": [
            {**sp, "pos": [sp["pos"][0] - offset[0], sp["pos"][1], sp["pos"][2] - offset[2]]}
            for sp in ship_pts
        ],
        "tags": [
            {**t, "pos": [t["pos"][0] - offset[0], t["pos"][1], t["pos"][2] - offset[2]]}
            for t in tag_recs
        ],
        # model-less actors that aren't triggers: salvage points, switches, Ajav, plus
        # any still-unmapped name (those carry "unresolved": true).  Kept out of
        # "actors" on purpose - stage.gd resolves a mesh for everything in there.
        "logic": [
            {**t, "pos": [t["pos"][0] - offset[0], t["pos"][1], t["pos"][2] - offset[2]]}
            for t in logic_recs
        ],
        # counts every model-less name, tags included (it was tallied and then binned)
        "skipped_names": dict(skipped_names.most_common()),
        "event_table": event_table,
        # authored camera behaviour: a CAMR/RCAM region names a dCamera_c type by string and
        # may point at an AROB/RARO arrow giving a fixed eye point (d_stage.h:166-185).  Which
        # region applies comes from the collision polygon Link stands on, not from a volume.
        # RTBL: the game keeps only these rooms resident at once (d_stage.cpp:213-247).
        # On the Great Sea every entry is {room 0, one island} - two rooms, never 49.
        "bridges": _bridge_spans(placements, paths, mult, offset),
        "room_sets": room_sets,
        "cameras": cameras,
        "cam_arrows": cam_arrows,
        "wave_max": {str(r): t.wave_max for r, t in mult.items() if r in room_nos},
        "offset": [offset[0], 0.0, offset[2]],
        "gltf": str(out_path),
        "seconds": seconds,
    }
    (out_dir / f"{stage_name}_report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8"
    )
    # the stage's cutscene / event scripts (Stage.arc dat/event_list.dat) as JSON
    ev_blob = disc.read_inner(f"res/Stage/{stage_name}/Stage.arc", "event_list.dat")
    if ev_blob:
        try:
            from gcrip.formats import evt as evt_mod

            evt_mod.dump_json(ev_blob, out_dir / f"{stage_name}_events.json")
        except (ValueError, struct.error, KeyError, IndexError):
            pass
    if not quiet:
        print(
            f"{stage_name}: {room_models} room models + {counts['placed']} actors placed "
            f"({builder.stats.models} unique models, {builder.stats.triangles:,} tris) "
            f"in {seconds}s\n"
            f"  skipped: {counts['logic']} logic, {counts['code_drawn']} vegetation/effects, "
            f"{counts['layered_skipped']} on conditional layers, "
            f"{counts['unresolved']} unresolved (kept in 'logic')"
        )
        if unresolved:
            top = ", ".join(f"{n} x{c}" for n, c in unresolved.most_common(8))
            print(f"  unresolved names: {top}")
        print(f"  -> {out_path}")
    return report


def _bind_exits(disc, stage_name, own, door_pts, spawn_pts) -> list[dict]:
    """Doors don't store which exit they use, but every destination's OWN exit table
    points back to an arrival spawn here - and that spawn stands right in front of the
    door. Invert that: arrival spawn -> nearest door -> that door leads to the arriving
    stage. Destination spawn/room comes from this stage's exit entries for that stage
    (paired in file order when a stage is entered through several doors)."""
    own_by_dest: dict[str, list] = {}
    for e in own:
        if e.dest_stage != stage_name:
            own_by_dest.setdefault(e.dest_stage, []).append(e)
    spawn_by_key = {}
    for sp in spawn_pts:
        spawn_by_key.setdefault((sp["room"], sp["id"]), sp)
    exits = []
    used_doors: set[int] = set()
    seen_from: dict[str, int] = {}
    for other, room, spawn_id in sorted(disc.incoming_exits(stage_name)):
        if other not in own_by_dest:
            continue  # one-way arrival (cutscene warp); no door leads back
        sp = spawn_by_key.get((room, spawn_id))
        if sp is None:
            continue
        best, best_d2 = None, 600.0**2
        for i, dp in enumerate(door_pts):
            if i in used_doors:
                continue
            dx = dp["pos"][0] - sp["pos"][0]
            dy = dp["pos"][1] - sp["pos"][1]
            dz = dp["pos"][2] - sp["pos"][2]
            d2 = dx * dx + dy * dy * 4 + dz * dz
            if d2 < best_d2:
                best, best_d2 = i, d2
        if best is None:
            continue
        used_doors.add(best)
        k = seen_from.get(other, 0)
        seen_from[other] = k + 1
        entries = own_by_dest[other]
        e = entries[min(k, len(entries) - 1)]
        dp = door_pts[best]
        exits.append(
            {
                "pos": list(dp["pos"]),
                "rot_y_deg": dp["rot"],
                "dest_stage": other,
                "spawn": e.spawn,
                "room": e.room,
            }
        )
    return exits


def _build_collision(disc, stage_name, room_nos, out_dir, offset) -> dict:
    """Write <stage>_col.gltf: the game's own .dzb collision, split by surface class.
    dzb vertices are stored pre-transformed in world space (verified: they match the
    MULT-placed visual geometry exactly), so only the recentre offset is applied."""
    from gcrip.export.gltf_merge import LevelBuilder

    col = LevelBuilder(out_dir / f"{stage_name}_col.gltf")
    shift = (-offset[0], 0.0, -offset[2])
    stats: Counter = Counter()
    for room_no in room_nos:
        raw = disc.read_inner(f"res/Stage/{stage_name}/Room{room_no}.arc", "room.dzb")
        if not raw:
            continue
        try:
            d = dzb_mod.parse(raw)
        except (ValueError, IndexError) as e:
            stats[f"error_room{room_no}"] = str(e)
            continue
        # solid ground is split by footstep material as well as by surface class, so the
        # collider Link stands on names its sound_id (Room3_solid_s13 = stone) and the
        # player can pick the right footstep wave straight off the ray hit
        solid_mask = d.surface_mask("solid") & ((d.tri_pass & dzb_mod.PASS_LINK) == 0)
        snd = d.tri_sound
        for m in sorted({int(v) for v in snd[solid_mask]}):
            sv, st_ = d.mesh_by(solid_mask & (snd == m))
            if len(st_) == 0:
                continue
            col.add_mesh(
                f"Room{room_no}_solid_s{m}",
                sv,
                st_,
                translation=(float(-offset[0]), 0.0, float(-offset[2])),
                extras={"gcrip_surface": "solid", "gcrip_sound": m},
            )
            stats["solid"] += len(st_)
        for surface in ("water", "lava", "poison"):
            verts, tris = d.mesh(surface)
            if not len(tris):
                continue
            col.add_mesh(
                f"Room{room_no}_{surface}",
                verts,
                tris,
                translation=shift,
                group=f"Room{room_no}_col",
                extras={"gcrip_surface": surface},
            )
            stats[surface] += len(tris)
        # wall codes the player code reads: ladders (4/5), vine walls (1), no-hang (2)
        for tag in ("ladder", "ladder_top", "climb", "nohang", "hookshot"):
            try:
                verts, tris = d.tagged(tag)
            except (KeyError, ValueError, AttributeError):
                continue
            if not len(tris):
                continue
            col.add_mesh(
                f"Room{room_no}_{tag}",
                verts,
                tris,
                translation=shift,
                group=f"Room{room_no}_col",
                extras={"gcrip_surface": tag},
            )
            stats[tag] += len(tris)
    if col.stats.triangles:
        col.save()
    return dict(stats)


def build_all(
    rip_dir: Path,
    *,
    iso: Path | None = None,
    layers: bool = False,
    spawns: bool = False,
    rigs: bool = False,
    world: bool = False,
    layer: int | None = None,
    quiet: bool = True,
) -> list[dict]:
    """Build every stage on the disc; write <ripdir>/stages/stage_matrix.md."""
    rip_dir = Path(rip_dir)
    disc = _Disc(_find_iso(rip_dir, iso))
    try:
        names = sorted(disc.stages(), key=str.lower)
        rows = []
        for i, name in enumerate(names):
            try:
                r = _build(
                    disc, rip_dir, name, None, layers, spawns, rigs, world, None, quiet,
                    time.monotonic(), layer=layer,
                )
            except Exception as e:  # noqa: BLE001
                r = {"stage": name, "error": f"{type(e).__name__}: {e}"}
            rows.append(r)
            if not quiet:
                continue
            tag = r.get("error") or (
                f"{r['room_models']} rooms {r['placed']} actors "
                f"{r['unresolved']} unresolved"
            )
            print(f"[{i + 1}/{len(names)}] {name:12} {tag}", flush=True)
    finally:
        disc.close()

    ok = [r for r in rows if not r.get("error")]
    unresolved: Counter = Counter()
    for r in ok:
        unresolved.update(r.get("unresolved_names", {}))
    lines = [
        "# Stage recompile matrix",
        "",
        f"{len(ok)}/{len(rows)} stages built · "
        f"{sum(r['placed'] for r in ok):,} actors placed · "
        f"{sum(r['room_models'] for r in ok)} room models · "
        f"{sum(r['unresolved'] for r in ok):,} unresolved placements",
        "",
        "| stage | rooms | room models | actors | logic | vegetation | layered | unresolved "
        "| tris | top unresolved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['stage']} | ⚠ {r['error']} | | | | | | | | |")
            continue
        top = ", ".join(f"{n}×{c}" for n, c in list(r["unresolved_names"].items())[:4])
        lines.append(
            f"| {r['stage']} | {len(r['rooms'])} | {r['room_models']} | {r['placed']} | "
            f"{r['logic_skipped']} | {r['code_drawn_skipped']} | {r['layered_skipped']} | "
            f"{r['unresolved']} | {r['triangles']:,} | {top} |"
        )
    lines += [
        "",
        "## Most-wanted unresolved actors (whole disc)",
        "",
        "| actor | placements |",
        "|---|---:|",
    ]
    lines += [f"| {n} | {c} |" for n, c in unresolved.most_common(30)]
    matrix = rip_dir / "stages" / "stage_matrix.md"
    matrix.parent.mkdir(parents=True, exist_ok=True)
    matrix.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"-> {matrix}")
    return rows


def list_stages(rip_dir: Path, iso: Path | None = None) -> None:
    disc = _Disc(_find_iso(Path(rip_dir), iso))
    try:
        stages = disc.stages()
        for name in sorted(stages, key=str.lower):
            rooms = sum(1 for a in stages[name] if _ROOM_RE.match(a))
            print(f"  {name:12} {rooms:3d} rooms")
        print(f"{len(stages)} stages")
    finally:
        disc.close()
