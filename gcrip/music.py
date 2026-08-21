"""Sequenced music: ``Audiores/Seqs/JaiSeqs.arc`` songs rendered through the game's own
instrument banks to WAV (``<rip_dir>/audio/music/<song>.wav``) plus ``music.json``
(song -> JA_BGM ids, stages that play it, length, unresolved voices).

Pipeline: JaiInit.aaf (bank / wave-bank tables, sound table) -> IBNK + WSYS parse ->
.aw sample decode (cached per wave) -> :func:`bms.play` (note list) -> :mod:`gcrip.synth`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from gcrip.formats import aaf, afc, bms, ibnk, rarc, wsys, yay0, yaz0
from gcrip.stage import _Disc, _find_iso

AAF_PATH = "Audiores/JaiInit.aaf"
SEQS_PATH = "Audiores/Seqs/JaiSeqs.arc"
BANKS_DIR = "Audiores/Banks/"
DEFAULT_SECONDS = 90.0
# synth.render reports these alongside the unresolved-voice counts; they are not failures
STATS = ("voices", "vibrato_voices")
BGM_TABLE = Path(__file__).with_name("data") / "ww_bgm.json"


class JAudioBanks:
    """Every IBNK / WSYS of the disc plus lazily decoded .aw samples."""

    def __init__(self, disc: _Disc):
        self.disc = disc
        self.raw = self._read(AAF_PATH)
        self.aaf = aaf.parse(self.raw)
        self.banks: dict[int, ibnk.Bank] = {}
        self.bank_wave_bank: dict[int, int] = {}
        for i, entry in enumerate(self.aaf.banks):
            try:
                bank = ibnk.parse(self.aaf.bank_data(self.raw, i))
            except (ValueError, IndexError, KeyError):
                continue
            vid = entry.virtual_id if entry.virtual_id is not None else bank.virtual_id
            self.banks[vid] = bank
            self.bank_wave_bank[vid] = entry.wave_bank
        self._wsys: dict[int, wsys.WaveBank | None] = {}
        self._aw: dict[str, bytes] = {}
        self._pcm: dict[tuple[str, int], np.ndarray] = {}

    def _read(self, path: str) -> bytes:
        e = self.disc.entries[path]
        return self.disc.img.read(e.offset, e.size)

    def wave_bank(self, index: int) -> wsys.WaveBank | None:
        if index not in self._wsys:
            try:
                self._wsys[index] = wsys.parse(self.aaf.wave_bank_data(self.raw, index))
            except (ValueError, IndexError, KeyError):
                self._wsys[index] = None
        return self._wsys[index]

    def lookup(self, bank_vid: int, wave_id: int):
        wb_index = self.bank_wave_bank.get(bank_vid)
        if wb_index is None:
            return None
        wb = self.wave_bank(wb_index)
        if wb is None:
            return None
        found = wb.find(wave_id)
        if found is None:
            return None
        group, wave = found
        key = (group.aw_name, wave_id)
        if key not in self._pcm:
            aw = self._aw.get(group.aw_name)
            if aw is None:
                path = BANKS_DIR + group.aw_name
                if path not in self.disc.entries:
                    return None
                aw = self._read(path)
                self._aw[group.aw_name] = aw
            try:
                self._pcm[key] = wsys.decode(aw, wave)
            except (ValueError, IndexError):
                self._pcm[key] = np.zeros(0, dtype=np.int16)
        return wave, self._pcm[key]

    def songs(self) -> dict[str, bytes]:
        blob = self._read(SEQS_PATH)
        if blob[:4] == b"Yaz0":
            blob = yaz0.decompress(blob)
        elif blob[:4] == b"Yay0":
            blob = yay0.decompress(blob)
        arc = rarc.parse(blob)
        return {
            Path(f.path).name: arc.read(blob, f)
            for f in arc.files
            if f.path.lower().endswith(".bms")
        }


def bgm_table() -> dict:
    if BGM_TABLE.exists():
        return json.loads(BGM_TABLE.read_text(encoding="utf-8"))
    return {"stages": {}, "sea_rooms": {}, "bgm_songs": {}}


def songs_for_stages(stages: list[str] | None = None) -> set[str]:
    """Songs the listed stages (or every stage) play, from data/ww_bgm.json."""
    t = bgm_table()
    out = set()
    for name, info in t["stages"].items():
        if stages and name not in stages:
            continue
        if info.get("song"):
            out.add(info["song"])
    if not stages or any(s == "sea" or s.startswith("sea_r") for s in stages):
        for info in t["sea_rooms"].values():
            if info.get("song"):
                out.add(info["song"])
    return out


def render_song(
    banks: JAudioBanks, data: bytes, *, seconds: float = DEFAULT_SECONDS
) -> tuple[np.ndarray, bms.Sequence, dict[str, int]]:
    from gcrip import synth

    seq = bms.play(data, max_seconds=seconds)
    pcm, missing = synth.render(seq, banks.banks, banks.lookup, seconds=min(seq.seconds, seconds))
    return pcm, seq, missing


def dump_music(
    rip_dir,
    iso=None,
    *,
    songs: list[str] | None = None,
    seconds: float = DEFAULT_SECONDS,
    quiet: bool = False,
) -> dict:
    """Render songs to <rip_dir>/audio/music/*.wav. ``songs`` = bms names (with or without
    the extension) or None for every song in JaiSeqs.arc."""
    rip_dir = Path(rip_dir)
    disc = _Disc(_find_iso(rip_dir, iso))
    banks = JAudioBanks(disc)
    all_songs = banks.songs()
    wanted = list(all_songs)
    if songs:
        wanted = []
        for s in songs:
            n = s if s.endswith(".bms") else s + ".bms"
            if n in all_songs:
                wanted.append(n)
            elif not quiet:
                print(f"gcrip music: no such song {s!r}")
    out_dir = rip_dir / "audio" / "music"
    out_dir.mkdir(parents=True, exist_ok=True)
    table = bgm_table()
    by_song: dict[str, list[str]] = {}
    for bgm, song in table.get("bgm_songs", {}).items():
        by_song.setdefault(song, []).append(bgm)
    stages_by_song: dict[str, list[str]] = {}
    for st, info in table.get("stages", {}).items():
        if info.get("song"):
            stages_by_song.setdefault(info["song"], []).append(st)
    for room, info in table.get("sea_rooms", {}).items():
        if info.get("song"):
            stages_by_song.setdefault(info["song"], []).append(f"sea/Room{room}")

    index_path = out_dir / "music.json"
    index: dict = {}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except ValueError:
            index = {}
    t_all = time.time()
    for i, name in enumerate(wanted):
        t0 = time.time()
        try:
            pcm, seq, missing = render_song(banks, all_songs[name], seconds=seconds)
        except (bms.BmsError, ValueError, IndexError) as ex:
            if not quiet:
                print(f"[{i + 1}/{len(wanted)}] {name}: FAILED {ex}")
            index[name] = {"error": str(ex)}
            continue
        stem = name[:-4]
        afc.write_wav(out_dir / f"{stem}.wav", 32000, pcm)
        index[name] = {
            "wav": f"{stem}.wav",
            "seconds": round(len(pcm) / 32000.0, 2),
            "notes": len(seq.notes),
            "tracks": seq.tracks,
            "voices": missing.get("voices", 0),
            "vibrato_voices": missing.get("vibrato_voices", 0),
            "unresolved": {k: v for k, v in missing.items() if k not in STATS and v},
            "bgm": by_song.get(name, []),
            "stages": stages_by_song.get(name, []),
        }
        if not quiet:
            unres = sum(v for k, v in missing.items() if k not in STATS)
            print(
                f"[{i + 1}/{len(wanted)}] {stem:14s} {len(seq.notes):5d} notes "
                f"{len(pcm) / 32000.0:6.1f}s  unresolved {unres:4d}  {time.time() - t0:5.1f}s"
            )
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    if not quiet:
        print(f"{len(wanted)} songs -> {out_dir}  ({time.time() - t_all:.0f}s)")
    return index
