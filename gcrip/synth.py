"""A small sample-playback synthesizer for JAudio sequences.

Renders the :class:`gcrip.formats.bms.Sequence` produced by :func:`bms.play` with the
instrument banks (IBNK) and wave banks (WSYS + ``.aw``) that ``JaiInit.aaf`` pairs with
them, the way ``JASystem::TChannel`` does at the coarse level:

* bank / program -> instrument (or drum set) -> key region -> velocity region -> wave
* playback rate = 2^((key - wave.key) / 12) x instrument pitch x region pitch x track pitch
  (percussion ignores the key: it plays the wave at its own rate, panned by the PERC entry)
* amplitude = track volume (already the product over the track chain) x velocity / 127
  x instrument volume x region volume, equal-power panned
* envelope: a short linear attack, hold while the note is on, then an exponential
  release (the note-off release byte in 1/30 s steps, else ~60 ms); one-shot waves
  stop at their end, looping waves wrap ``loop_start..loop_end`` forever

The oscillator tables (real ADSR curves), LFO / vibrato, reverb and the DSP's
biquad filters are not modelled - those are the difference between this and the
console, not the notes. Pure numpy, no audio libraries.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from gcrip.formats import ibnk, wsys
from gcrip.formats.bms import Note, Sequence

OUT_RATE = 32000  # the GameCube DSP mixes at 32 kHz
ATTACK_SEC = 0.004
DEFAULT_RELEASE_SEC = 0.06
MAX_LOOP_NOTE_SEC = 30.0  # a held looping note longer than this is cut
MASTER_GAIN = 0.35
TARGET_PEAK = 0.9

WaveLookup = Callable[[int, int], tuple[wsys.Wave, np.ndarray] | None]
"""(bank virtual id, wave id) -> (wave header, decoded int16 mono samples), None if missing."""


@dataclass
class Voice:
    start_sec: float
    end_sec: float
    release_sec: float
    wave: wsys.Wave
    pcm: np.ndarray
    ratio: float  # source samples per output sample
    gain_l: float
    gain_r: float


def _region_for(
    bank: ibnk.Bank, note: Note
) -> tuple[ibnk.VelRegion, float, float, float | None, bool] | None:
    """-> (vel region, volume mult, pitch mult, pan override, is_percussion)."""
    prog = bank.program(note.program)
    if prog is None:
        return None
    if isinstance(prog, ibnk.DrumSet):
        perc = prog.percs.get(note.key)
        if perc is None:
            return None
        vr = perc.region(note.velocity)
        if vr is None:
            return None
        return vr, perc.volume * vr.volume, perc.pitch * vr.pitch, perc.pan, True
    vr = prog.region(note.key, note.velocity)
    if vr is None:
        return None
    return vr, prog.volume * vr.volume, prog.pitch * vr.pitch, None, False


def build_voices(
    seq: Sequence,
    banks: dict[int, ibnk.Bank],
    lookup: WaveLookup,
    *,
    out_rate: int = OUT_RATE,
    seconds: float | None = None,
) -> tuple[list[Voice], dict[str, int]]:
    """Resolve every note of the sequence to a playable voice. Returns the voices and a
    count of what could not be resolved (missing bank / program / wave)."""
    voices: list[Voice] = []
    missing = {"bank": 0, "program": 0, "wave": 0}
    limit = seconds if seconds is not None else seq.seconds
    for n in seq.notes:
        if n.start_sec >= limit:
            continue
        bank = banks.get(n.bank)
        if bank is None:
            missing["bank"] += 1
            continue
        reg = _region_for(bank, n)
        if reg is None:
            missing["program"] += 1
            continue
        vr, vol_mult, pitch_mult, pan_override, is_perc = reg
        found = lookup(n.bank, vr.wave_id)
        if found is None:
            missing["wave"] += 1
            continue
        wave, pcm = found
        if not len(pcm):
            missing["wave"] += 1
            continue
        semis = 0.0 if is_perc else float(n.key - wave.key)
        ratio = (2.0 ** (semis / 12.0)) * pitch_mult * max(n.pitch, 1e-4) * (wave.rate / out_rate)
        amp = max(n.volume, 0.0) * (n.velocity / 127.0) * vol_mult * MASTER_GAIN
        pan = pan_override if pan_override is not None else n.pan
        pan = min(max(pan, 0.0), 1.0)
        gain_l = amp * math.cos(pan * math.pi / 2.0)
        gain_r = amp * math.sin(pan * math.pi / 2.0)
        end_sec = n.end_sec if n.end is not None else limit
        end_sec = min(end_sec, limit)
        if wave.loop:
            end_sec = min(end_sec, n.start_sec + MAX_LOOP_NOTE_SEC)
        release = (n.release / 30.0) if n.release else DEFAULT_RELEASE_SEC
        voices.append(Voice(n.start_sec, end_sec, release, wave, pcm, ratio, gain_l, gain_r))
    return voices, missing


def _render_voice(v: Voice, out_rate: int, total_frames: int) -> tuple[int, np.ndarray] | None:
    """-> (first output frame, mono float32 block) for one voice."""
    start = int(round(v.start_sec * out_rate))
    if start >= total_frames:
        return None
    held = max(v.end_sec - v.start_sec, 0.0)
    length = int(round((held + v.release_sec * 4.0) * out_rate))
    if not v.wave.loop:
        # a one-shot sample cannot sound past its own end
        length = min(length, int(len(v.pcm) / v.ratio) + 1)
    length = min(length, total_frames - start)
    if length <= 0:
        return None
    pos = np.arange(length, dtype=np.float64) * v.ratio
    pcm = v.pcm
    if v.wave.loop and v.wave.loop_end > v.wave.loop_start + 1:
        ls, le = v.wave.loop_start, min(v.wave.loop_end, len(pcm))
        span = le - ls
        over = pos >= ls
        pos[over] = ls + np.mod(pos[over] - ls, span)
    idx = np.floor(pos).astype(np.int64)
    frac = (pos - idx).astype(np.float32)
    idx = np.clip(idx, 0, len(pcm) - 1)
    idx1 = np.clip(idx + 1, 0, len(pcm) - 1)
    samples = pcm[idx].astype(np.float32) * (1.0 - frac) + pcm[idx1].astype(np.float32) * frac
    samples *= 1.0 / 32768.0
    # envelope
    env = np.ones(length, dtype=np.float32)
    a = min(int(ATTACK_SEC * out_rate), length)
    if a > 1:
        env[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
    rel_start = int(round(held * out_rate))
    if rel_start < length:
        t = np.arange(length - rel_start, dtype=np.float32) / out_rate
        env[rel_start:] *= np.exp(-t / max(v.release_sec / 3.0, 1e-3)).astype(np.float32)
    return start, samples * env


def render(
    seq: Sequence,
    banks: dict[int, ibnk.Bank],
    lookup: WaveLookup,
    *,
    out_rate: int = OUT_RATE,
    seconds: float | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Mix the sequence down to int16 stereo (frames x 2) at ``out_rate``."""
    limit = seconds if seconds is not None else seq.seconds
    total = int(math.ceil(limit * out_rate)) + out_rate  # a second of tail for releases
    voices, missing = build_voices(seq, banks, lookup, out_rate=out_rate, seconds=limit)
    mix = np.zeros((total, 2), dtype=np.float32)
    for v in voices:
        r = _render_voice(v, out_rate, total)
        if r is None:
            continue
        start, block = r
        end = start + len(block)
        mix[start:end, 0] += block * v.gain_l
        mix[start:end, 1] += block * v.gain_r
    # normalise: the console's mixer / reverb chain is not modelled, so level every song
    # to the same peak instead of trusting absolute gains
    peak = float(np.max(np.abs(mix))) if len(mix) else 0.0
    if peak > 1e-6:
        mix *= TARGET_PEAK / peak
    # trim the silent tail
    nz = np.nonzero(np.max(np.abs(mix), axis=1) > 1e-4)[0]
    if len(nz):
        mix = mix[: min(len(mix), int(nz[-1]) + out_rate // 10)]
    missing["voices"] = len(voices)
    return (mix * 32767.0).astype(np.int16), missing
