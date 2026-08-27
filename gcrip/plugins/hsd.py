"""HAL sysdolphin .dat archives (Super Smash Bros. Melee, Kirby Air Ride): every JOBJ tree
the file names (`*_joint`, `map_head` model groups, `*_scene_data` / `*_model_set` sets)
plus JOBJs buried in game tables, each as a skinned, textured Scene."""

from __future__ import annotations

import re
import struct
from pathlib import PurePosixPath

from gcrip.formats import hsd, hsd_anim, hsd_eval
from ripcore.scene import Scene

NAME = "hsd"

_EXTS = {".dat", ".usd", ".hsd"}
_FIGHTER = re.compile(r"^(Pl[A-Z][a-z])[A-Za-z0-9]*\.(dat|usd)$")
_IMAGE_SUFFIX = re.compile(
    r"_(MIPMAP_)?(CMPR|C4|C8|C14X2|I4|I8|IA4|IA8|RGB565|RGB5A3|RGBA8)_image$"
)


def detect(path: str, head: bytes, size: int) -> bool:
    if PurePosixPath(path.replace("\\", "/")).suffix.lower() not in _EXTS:
        return False
    if size < hsd.HEADER + 8 or len(head) < 0x14:
        return False
    fsz, dsz, nrel, nroot, nref = struct.unpack_from(">IIIII", head, 0)
    if fsz != size or nroot + nref == 0:
        return False
    tables = hsd.HEADER + dsz + nrel * 4 + (nroot + nref) * 8
    return tables <= size and dsz >= 0x10


def _safe(name: str) -> str:
    """Root names come from the file's string table; a few Kirby Air Ride files carry
    binary junk there, and the name ends up in an output file name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")[:80] or "model"


def _image_names(dat: hsd.DatFile) -> dict[int, str]:
    """Root names of image descriptors (`Foo_CMPR_image`) so textures keep their names."""
    names: dict[int, str] = {}
    for r in dat.roots:
        if r.reference or not r.name.endswith("_image"):
            continue
        n = _IMAGE_SUFFIX.sub("", r.name)
        names[r.offset] = n if n != r.name else r.name[: -len("_image")]
    return names


def _animation_archive(path: str, src) -> tuple[bytes, str] | None:
    """Melee keeps a fighter's animations in Pl<Xx>AJ.dat next to the costume files
    Pl<Xx><Costume>.dat; return that archive when the file looks like a costume."""
    posix = path.replace("\\", "/")
    name = PurePosixPath(posix).name
    m = _FIGHTER.match(name)
    if m is None or name.startswith(m.group(1) + "AJ"):
        return None
    sep = "\\" if "\\" in path else "/"
    aj_path = sep.join([*path.replace("\\", "/").split("/")[:-1], f"{m.group(1)}AJ.dat"])
    by_path = getattr(src, "by_path", None)
    if by_path and aj_path not in by_path:
        return None
    try:
        blob = src.get(aj_path)
    except Exception:  # noqa: BLE001 - a missing archive just means no clips
        return None
    return (blob, aj_path) if blob and hsd_anim.is_archive(blob) else None


def extract(data: bytes, path: str, src) -> list[Scene]:
    dat = hsd.DatFile(data)
    stem = PurePosixPath(path.replace("\\", "/")).stem
    parser = hsd.Parser(dat)
    textures = hsd_eval.TextureCache(dat, _image_names(dat), stem)
    scenes: list[Scene] = []
    models = []
    for model in hsd.models(dat, parser):
        name = _safe(model.name)
        scene = hsd_eval.evaluate(dat, model, f"{stem}.{name}" if name != stem else stem, textures)
        if not scene.primitives:
            continue
        scenes.append(scene)
        models.append(model)
    if scenes and src is not None:
        archive = _animation_archive(path, src)
        if archive:
            blob, aj_path = archive
            for scene, model in zip(scenes, models, strict=True):
                joints = [j for r in model.roots for j in r.walk()]
                joints.sort(key=lambda j: j.index)
                clips, warns = hsd_anim.archive_clips(blob, joints, key=(aj_path,))
                if clips:
                    scene.clips += clips
                    scene.warnings += warns
                    break
    return scenes
