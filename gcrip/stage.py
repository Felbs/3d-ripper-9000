"""Recompile a whole Wind Waker stage into one level glTF.

    gcrip stage out/rip/GZLE01 M_NewD2 [--rooms 0,1] [--iso PATH] [--layers]
    gcrip stage out/rip/GZLE01 --list

Reads the stage's placement files (stage.dzs + Room*/room.dzr) straight from the disc
image, resolves each placed actor to a model that `gcrip rip` already exported, and
writes <ripdir>/stages/<stage>/<stage>.gltf: room geometry placed by the MULT room
table plus one instance per actor (world-space position, Y rotation, SCOB scale).

What doesn't end up in the level (all counted in <stage>_report.json):
  - logic actors (tags, switches, triggers, Tingle Tuner hooks) - they have no model
  - vegetation (grass/flowers/trees) and some effects - drawn from display lists
    embedded in the game executable, not from any archive
  - actors whose name we can't map to an archive yet (logged with counts)
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from gcrip.data.ww_actors import (
    CHEST_MODELS,
    CHEST_PREFIXES,
    CODE_DRAWN_PREFIXES,
    KNOB_PAIR,
    NO_MODEL_PREFIXES,
    WW_ACTORS,
)
from gcrip.disc.fst import parse_fst, parse_header
from gcrip.disc.image import DiscImage
from gcrip.export.gltf_merge import LevelBuilder
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
    out_dir: Path | None = None,
    quiet: bool = False,
) -> dict:
    t0 = time.monotonic()
    rip_dir = Path(rip_dir)
    disc = _Disc(_find_iso(rip_dir, iso))
    try:
        return _build(
            disc, rip_dir, stage_name, rooms, layers, spawns, rigs, world, out_dir, quiet, t0
        )
    finally:
        disc.close()


def _build(
    disc, rip_dir, stage_name, rooms, layers, spawns, rigs, world, out_dir, quiet, t0
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

    # ---- placement data
    stage_arcs = stages[stage_name]
    mult: dict[int, dzs_mod.RoomTransform] = {}
    placements: list[tuple[int | None, dzs_mod.Placement]] = []  # (room_no, placement)
    if "Stage.arc" in stage_arcs:
        raw = disc.read_inner(f"res/Stage/{stage_name}/Stage.arc", "stage.dzs")
        if raw:
            d = dzs_mod.parse(raw)
            mult = d.mult
            placements += [(None, p) for p in d.placements]
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
            placements += [(room_no, p) for p in dzs_mod.parse(raw).placements]

    # ---- room geometry (already ripped; MULT places it)
    room_models = 0
    for room_no in room_nos:
        t = mult.get(room_no)
        for rel in index.rooms.get(stage_name, {}).get(room_no, []):
            ok = builder.add_instance(
                rip_dir / rel,
                f"Room{room_no}/{Path(rel).stem}",
                translation=(t.trans_x, 0.0, t.trans_z) if t else (0.0, 0.0, 0.0),
                rot_y_deg=t.rot_y_deg if t else 0.0,
                group=f"Room{room_no}",
            )
            room_models += ok
    if not room_models and not quiet:
        print(f"warning: no ripped room models found for {stage_name} under {rip_dir}")

    # ---- actors
    counts = Counter()
    unresolved = Counter()
    skipped_names = Counter()
    for room_no, p in placements:
        if p.layer >= 0 and not layers:
            counts["layered_skipped"] += 1
            continue
        if p.chunk == "PLYR":
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
            target = index.find_stage_local(stage_name, p.name)
        if target is None:
            counts["unresolved"] += 1
            unresolved[p.name] += 1
            continue

        group = f"Room{room_no}_actors" if room_no is not None else "Stage_actors"
        ok = builder.add_instance(
            target,
            f"{p.name}.{counts['placed']}",
            translation=p.pos,
            rot_y_deg=p.rot_y_deg,
            scale=p.scale,
            group=group,
        )
        counts["placed" if ok else "empty_model"] += 1

    offset = (0.0, 0.0, 0.0) if world else builder.recenter()
    out_path = builder.save()
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
        "gltf": str(out_path),
        "seconds": seconds,
    }
    (out_dir / f"{stage_name}_report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8"
    )
    if not quiet:
        print(
            f"{stage_name}: {room_models} room models + {counts['placed']} actors placed "
            f"({builder.stats.models} unique models, {builder.stats.triangles:,} tris) "
            f"in {seconds}s\n"
            f"  skipped: {counts['logic']} logic, {counts['code_drawn']} vegetation/effects, "
            f"{counts['layered_skipped']} on conditional layers, {counts['unresolved']} unresolved"
        )
        if unresolved:
            top = ", ".join(f"{n} x{c}" for n, c in unresolved.most_common(8))
            print(f"  unresolved names: {top}")
        print(f"  -> {out_path}")
    return report


def build_all(
    rip_dir: Path,
    *,
    iso: Path | None = None,
    layers: bool = False,
    spawns: bool = False,
    rigs: bool = False,
    world: bool = False,
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
                    time.monotonic(),
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
