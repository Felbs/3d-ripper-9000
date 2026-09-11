"""Whole-ROM extraction: every actor with a skeleton, exported as a rigged glTF.

Mirrors what ``gcrip.rip`` does for a disc, and writes the same ``rip_results.json`` shape, so
the library browser, the quality auditor, the MCP tools and the Blender add-on read an N64 rip
exactly as they read a GameCube one.

Segment binding is the honest part.  An actor's own file is segment 6, which is what makes
most characters work standalone.  Segment 4 is ``gameplay_keep``, a shared bank several actors
borrow textures from, so it is bound when it can be identified.  Segments 8-0F are written by
actor code while the game runs and cannot be bound at all - models that use them come out with
some textures missing, and say so rather than pretending.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from n64rip import f3dex2, objects as obj_mod, skeleton as skel_mod, zobj
from n64rip.rom import Rom, RomFile
from ripcore import gltf

MIN_TRIANGLES = 4


@dataclass
class ModelResult:
    name: str
    file_index: int
    vrom: str
    out_rel: str = ""
    thumb: str = ""
    triangles: int = 0
    vertices: int = 0
    textures: int = 0
    textures_missing: int = 0
    limbs: int = 0
    drawn_limbs: int = 0
    skinned: bool = True
    unresolved_segments: list[int] = field(default_factory=list)
    object_id: int | None = None  # its slot in the game's object table, when it has one
    error: str = ""
    warnings: list[str] = field(default_factory=list)


# segment binding now comes from the game's own object table; see n64rip.objects


def extract_rom(
    rom: Rom,
    out_dir: Path,
    *,
    limit: int | None = None,
    progress=None,
) -> dict:
    """Export every skeleton-bearing file in *rom*.  Returns the rip_results dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    models: list[ModelResult] = []
    # The game's object table says which files are objects and which is gameplay_keep, and it
    # validates against the DMA table, so nothing outside the ROM is needed to find it.
    table = obj_mod.find_object_table(rom)
    shared = obj_mod.keep_segments(rom, table)
    object_ids: dict[int, int] = {}
    if table is not None:
        for oid, fidx in enumerate(table.entries):
            if fidx is not None:
                object_ids.setdefault(fidx, oid)
    files = rom.live[:limit] if limit else rom.live
    for n, f in enumerate(files):
        if progress and n % 50 == 0:
            progress(n, len(files), len(models))
        if f.size < 128:
            continue
        try:
            data = rom.read(f)
        except Exception as exc:  # noqa: BLE001 - a bad entry must not stop the rip
            continue
        try:
            skels = skel_mod.find_skeletons(data)
        except Exception as exc:  # noqa: BLE001
            models.append(ModelResult(f.label, f.index, f"{f.vrom_start:#x}",
                                      error=f"skeleton scan: {exc}"))
            continue
        if not skels:
            continue
        segments = f3dex2.Segments({6: data, **shared})
        for si, sk in enumerate(skels):
            name = f.label if len(skels) == 1 else f"{f.label}_skel{si}"
            res = ModelResult(name, f.index, f"{f.vrom_start:#x}", limbs=sk.count)
            res.object_id = object_ids.get(f.index)
            try:
                scene = zobj.build(name, data, sk, segments)
            except Exception as exc:  # noqa: BLE001
                res.error = f"{type(exc).__name__}: {exc}"
                models.append(res)
                continue
            if scene.triangles < MIN_TRIANGLES:
                continue
            base = out_dir / name
            try:
                st = gltf.export(scene, base, thumbnail=True)
                thumb = gltf.thumbnail(st, base, size=256)
            except Exception as exc:  # noqa: BLE001
                res.error = f"export: {type(exc).__name__}: {exc}"
                models.append(res)
                continue
            res.out_rel = f"{name}.gltf"
            res.thumb = f"{name}_thumb.png" if thumb else ""
            res.triangles = scene.triangles
            res.vertices = scene.vertices
            res.textures = len(scene.textures)
            res.textures_missing = int(scene.extras.get("textures_missing", 0))
            res.drawn_limbs = int(scene.extras.get("drawn_limbs", 0))
            res.unresolved_segments = list(scene.extras.get("unresolved_segments", []))
            res.warnings = list(scene.warnings)
            models.append(res)
    ok = [m for m in models if m.out_rel]
    report = {
        "rom": rom.name,
        "title": rom.title,
        "code": rom.code,
        "crc": f"{rom.crc1:08x}/{rom.crc2:08x}",
        "seconds": round(time.time() - t0),
        "files": len(rom.files),
        "object_table": None if table is None else {
            "offset": table.offset,
            "in_file": table.file_index,
            "slots": len(table.entries),
            "object_files": len(table.object_files),
            "gameplay_keep": table.file_for(obj_mod.GAMEPLAY_KEEP),
        },
        "models": [asdict(m) for m in models],
        "totals": {
            "exported": len(ok),
            "triangles": sum(m.triangles for m in ok),
            "textures": sum(m.textures for m in ok),
            "textures_missing": sum(m.textures_missing for m in ok),
            "rigged": sum(1 for m in ok if m.limbs > 1),
            "failed": sum(1 for m in models if m.error),
        },
    }
    (out_dir / "rip_results.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
