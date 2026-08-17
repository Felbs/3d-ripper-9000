"""Render a manifest as a directory tree."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from gcrip.manifest import Manifest, ManifestEntry


def human_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}B"


class _Node:
    __slots__ = ("children", "entry", "name")

    def __init__(self, name: str):
        self.name = name
        self.children: dict[str, _Node] = {}
        self.entry: ManifestEntry | None = None


def build_tree(files: Iterable[ManifestEntry], dirs: Iterable[str] = ()) -> _Node:
    root = _Node("")
    for d in dirs:
        node = root
        for part in d.split("/"):
            node = node.children.setdefault(part, _Node(part))
    for f in files:
        node = root
        parts = f.path.split("/")
        for part in parts[:-1]:
            node = node.children.setdefault(part, _Node(part))
        leaf = node.children.setdefault(parts[-1], _Node(parts[-1]))
        leaf.entry = f
    return root


def _label(node: _Node, show_hash: bool) -> str:
    e = node.entry
    if e is None:
        return node.name + "/"
    tag = e.fmt or e.kind
    if e.compression:
        tag = f"{tag}<{e.compression}>"
    s = f"{node.name}  [{tag}] {human_size(e.size)}"
    if node.children:  # archive with contents
        s = f"{node.name}/  [{tag}] {human_size(e.size)}"
    if show_hash and e.sha1:
        s += f"  {e.sha1[:10]}"
    return s


def render_tree(
    manifest: Manifest,
    *,
    ascii_only: bool = False,
    max_depth: int | None = None,
    show_hash: bool = False,
    kinds: set[str] | None = None,
) -> Iterable[str]:
    files = manifest.files
    if kinds:
        files = [f for f in files if f.kind in kinds]
    root = build_tree(files, manifest.dirs if not kinds else ())
    tee, last, pipe, blank = (
        ("|-- ", "`-- ", "|   ", "    ")
        if ascii_only
        else (
            "├── ",
            "└── ",
            "│   ",
            "    ",
        )
    )

    def walk(node: _Node, prefix: str, depth: int) -> Iterable[str]:
        # dirs first (alphabetical), then files (alphabetical)
        items = sorted(node.children.values(), key=lambda c: (c.entry is not None, c.name.lower()))
        for i, child in enumerate(items):
            is_last = i == len(items) - 1
            yield prefix + (last if is_last else tee) + _label(child, show_hash)
            if child.children and (max_depth is None or depth + 1 < max_depth):
                yield from walk(child, prefix + (blank if is_last else pipe), depth + 1)

    g = manifest.game
    yield f"{g['id']}  {g['title']}  ({g['region']}, disc {g['disc_number']}, rev {g['revision']})"
    yield from walk(root, "", 0)


def render_summary(manifest: Manifest) -> Iterable[str]:
    d: dict[str, Any] = manifest.to_dict()
    st = d["stats"]
    yield (
        f"{st['file_count']} files "
        f"({st['top_level_file_count']} on disc, "
        f"{st['file_count'] - st['top_level_file_count']} inside archives)"
    )
    by_fmt = sorted(st["by_fmt"].items(), key=lambda kv: -kv[1])
    yield "by format: " + ", ".join(f"{k}={v}" for k, v in by_fmt)
    by_kind = sorted(st["by_kind"].items(), key=lambda kv: -kv[1])
    yield "by kind:   " + ", ".join(f"{k}={v}" for k, v in by_kind)
    if manifest.errors:
        yield f"{len(manifest.errors)} errors (see manifest 'errors')"
