"""SA Tools split configurations for the GameCube Sonic Adventure games, bundled under
``gcrip/data/satools/GC_SADX`` and ``GC_SA2B`` (from github.com/X-Hax/sa_tools GameConfig -
thank you, X-Hax).  Each INI names a disc file (``datafile=STG00.rel``), its load address
(``key=C900000``) and the structures inside: ``[Label] type=basicmodel|chunkmodel|landtable
|... address=HEX filename=... texture=NAME``."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "satools"


@dataclass
class Entry:
    label: str
    type: str
    address: int
    filename: str = ""
    texture: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Config:
    game: str  # "SADX" | "SA2B"
    name: str  # ini stem
    datafile: str
    key: int
    entries: list[Entry]


def _parse(text: str, game: str, name: str) -> Config | None:
    datafile = ""
    key = 0
    entries: list[Entry] = []
    cur: dict | None = None
    label = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if cur is not None and "type" in cur:
                entries.append(_entry(label, cur))
            label = line[1:-1]
            cur = {}
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().lower(), v.strip()
        if cur is None:
            if k == "datafile":
                datafile = v
            elif k == "key":
                key = int(v, 16)
        else:
            cur[k] = v
    if cur is not None and "type" in cur:
        entries.append(_entry(label, cur))
    if not datafile:  # SA Tools' project XML maps such INIs to <stem>.rel
        datafile = f"{name}.rel"
    return Config(game, name, datafile, key or 0xC900000, entries)


def _entry(label: str, kv: dict) -> Entry:
    addr = kv.get("address", "0")
    try:
        address = int(addr, 16)
    except ValueError:
        address = 0
    extra = {k: v for k, v in kv.items() if k not in ("type", "address", "filename", "texture")}
    return Entry(
        label, kv.get("type", ""), address, kv.get("filename", ""), kv.get("texture", ""), extra
    )


@functools.lru_cache(maxsize=1)
def configs() -> list[Config]:
    out = []
    for game in ("SADX", "SA2B"):
        folder = DATA / f"GC_{game}"
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() != ".ini":
                continue
            try:
                cfg = _parse(p.read_text(encoding="utf-8", errors="replace"), game, p.stem)
            except Exception:  # noqa: BLE001
                continue
            if cfg:
                out.append(cfg)
    return out


def for_datafile(name: str) -> list[Config]:
    """Configs whose datafile matches this disc file name (case-insensitive)."""
    base = name.rsplit("/", 1)[-1].lower()
    return [c for c in configs() if c.datafile.lower() == base]


_STAGE = re.compile(r"stg(\d\d)", re.I)


def stage_number(name: str) -> str | None:
    m = _STAGE.search(name)
    return m.group(1) if m else None
