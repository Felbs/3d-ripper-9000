"""Format plugins: one module per non-J3D model format on GameCube discs.

A plugin is a module in this package that defines:

    NAME = "hsd"                                  # short label, shows in the report
    def detect(path: str, head: bytes, size: int) -> bool
        # cheap sniff on the manifest path and the first bytes of the (decompressed) file
    def extract(data: bytes, path: str, src) -> list[ripcore.scene.Scene]
        # every model in the file as a Scene (textures decoded into scene.textures);
        # `src.get(other_path)` fetches sibling files (texture packs, animations) and
        # `src.by_path` is the manifest index, so a plugin can look around the archive

Optional - container support, so the disc walker expands archives the plugin knows:
    def is_container(name: str, head: bytes) -> bool
    def expand(data: bytes) -> list[tuple[str, bytes]]   # (inner path, inner bytes)
The manifest walks the returned entries like RARC members (nested paths, classification,
further expansion), so models inside such archives reach the plugins as plain files.

A plugin may set ``FALLBACK = True``: it is only consulted for files (or containers) that
no ordinary plugin claimed - the structure-based crackers in ``generic`` and ``gx`` live
there, so a known format always wins over a guess.

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
            try:
                mod = importlib.import_module(f"{__name__}.{info.name}")
            except Exception as e:  # noqa: BLE001 - one broken plugin must not stop a rip
                import sys

                print(f"gcrip: plugin {info.name} failed to import: {e}", file=sys.stderr)
                continue
            if hasattr(mod, "detect") and hasattr(mod, "extract"):
                mods.append(mod)
        _loaded = sorted(mods, key=lambda m: getattr(m, "NAME", m.__name__))
    return _loaded


def is_fallback(mod: ModuleType) -> bool:
    return bool(getattr(mod, "FALLBACK", False))


def container_plugins() -> list[ModuleType]:
    """Ordinary container plugins first, fallbacks (generic table/compression) last."""
    mods = [m for m in all_plugins() if hasattr(m, "is_container") and hasattr(m, "expand")]
    return sorted(mods, key=is_fallback)


def plugins_for(path: str, head: bytes, size: int) -> list[ModuleType]:
    """Plugins claiming this file; fallbacks only when no ordinary plugin does."""
    out = []
    for mod in all_plugins():
        try:
            if mod.detect(path, head, size):
                out.append(mod)
        except Exception:  # noqa: BLE001 - a plugin's sniff must never break the walk
            continue
    ordinary = [m for m in out if not is_fallback(m)]
    return ordinary or out
