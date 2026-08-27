"""Format plugins: one module per non-J3D model format on GameCube discs.

A plugin is a module in this package that defines:

    NAME = "hsd"                                  # short label, shows in the report
    def detect(path: str, head: bytes, size: int) -> bool
        # cheap sniff on the manifest path and the first bytes of the (decompressed) file
    def extract(data: bytes, path: str, src) -> list[ripcore.scene.Scene]
        # every model in the file as a Scene (textures decoded into scene.textures);
        # `src.get(other_path)` fetches sibling files (texture packs, animations) and
        # `src.by_path` is the manifest index, so a plugin can look around the archive

Optional:
    CONTAINERS: extra archive formats the walker should expand are the manifest's business
    (gcrip.manifest); a plugin only ever sees files.

The rip calls every plugin whose detect() says yes, exports each returned Scene through
ripcore.gltf (same glTF/thumbnail/report path as J3D and Dreamcast models), and records
warnings/errors per file - one broken plugin never stops a rip. Plugins are discovered by
listing this package, so adding a format is adding a file.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

_loaded: list[ModuleType] | None = None


def all_plugins() -> list[ModuleType]:
    global _loaded
    if _loaded is None:
        mods = []
        for info in pkgutil.iter_modules(__path__):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{__name__}.{info.name}")
            if hasattr(mod, "detect") and hasattr(mod, "extract"):
                mods.append(mod)
        _loaded = sorted(mods, key=lambda m: getattr(m, "NAME", m.__name__))
    return _loaded


def plugins_for(path: str, head: bytes, size: int) -> list[ModuleType]:
    out = []
    for mod in all_plugins():
        try:
            if mod.detect(path, head, size):
                out.append(mod)
        except Exception:  # noqa: BLE001 - a plugin's sniff must never break the walk
            continue
    return out
