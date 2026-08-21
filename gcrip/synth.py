# ruff: noqa: E501
"""A small sample-playback synthesizer for JAudio sequences.

Renders the :class:`gcrip.formats.bms.Sequence` produced by :func:`bms.play` with the
instrument banks (IBNK) and wave banks (WSYS + ``.aw``) that ``JaiInit.aaf`` pairs with
them, the way ``JASystem::TChannel`` does at the coarse level:

* bank / program -> instrument (or drum set) -> key region -> velocity region -> wave
* playback rate = 2^((key - wave.key) / 12) x instrument pitch x region pitch x track pitch
  (percussion ignores the key: it plays the wave at its own rate, panned by the PERC entry)
* amplitude = track volume (already the product over the track chain) x velocity / 127
  x instrument volume x region volume, equal-power panned
* envelope: the instrument's volume oscillator (IBNK ``OSCT``): rows of (mode, time,
  value) run by ``JASystem::TOscillator`` - time in 1/600 s (``time * (dacRate/80/600)``
  driver updates), value / 0x8000 as the target level, modes 0 linear, 1 square,
  2 square-root, 3 "sample cell" (exponential-ish 16-entry tables), 13 loop, 14 hold,
  15 stop; the release table takes over at note-off (or a direct release: percussion
  ``release`` / the note-off byte, also 1/600 s units). Output = phase x width + vertex.
  Instruments without tables get a 4 ms attack / 60 ms release. One-shot waves stop at
  their end, looping waves wrap ``loop_start..loop_end`` forever
* vibrato: the track's ``JASystem::TVibrate`` pitch LFO. Its counter advances by the
  rate every driver update and wraps at 4.0 (JASTrack.cpp:1533), and the value is a
  plain sine of that counter (JASTrack.cpp:1542 folds a quarter-sine table, which is
  ``sin(pi * counter / 2)``) turned into a frequency ratio by ``Player::pitchToCent``
  (JASPlayer_impl.cpp:40) = ``2^(4 * depth * sin)``. The BMS commands are E5/E6
  (depth) and F4 (rate)
* the instrument's pitch oscillator (IBNK ``OSCT`` with target 1) multiplies the
  playback rate the same way the volume oscillator multiplies amplitude
  (``TChannel::effectOsc`` case 1, JASChannel.cpp:155) - in Wind Waker these are
  short pitch scoops into the note, not loops
* a light Schroeder reverb fed from a per-voice effect send. The DSP's bus table
  (JASChannelMgr.cpp:42-45) routes each channel dry to L/R and again to the fx line
  scaled by ``sin(pi/2 * fxmix)``, where fxmix is the track's timed parameter 2
  (``TChannel::updateMixer``, JASChannel.cpp:740/756)

Not modelled: the DSP biquads (IIR/FIR), Dolby, the scene's own fx settings (JAI's
outer fxmix lives in game data, not in the sequence), timed-parameter ramps inside a
note. Pure numpy, no audio libraries.
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
OSC_TIME_UNIT = 1.0 / 600.0  # envelope row time -> seconds (dacRate / 80 / 600 updates)
# the driver updates every 80 samples of the 32 kHz DSP (JASOscillator.cpp:207 divides
# envelope times by dacRate/80), so tempo, envelopes and the vibrato counter all tick at
# 400 Hz; that puts the songs' vibrato rates at 5.1-5.7 Hz, which is what they sound like
DRIVER_HZ = OUT_RATE / 80.0
VIB_WRAP = 4.0  # TVibrate counter period (JASTrack.cpp:1538)
VIB_SEMITONES = 48.0  # pitchToCent(x, 12) = 2^(4x) = 48 semitones per unit of depth
REVERB_RETURN = 0.7  # fx-line return level
# JAI's own scene fxmix (JAInter::Fx tables) is game data, not sequence data, so it is not
# in the rip; this stands in for it and is added to the track's fxmix the way calcEffect
# sums the three sources (JASChannel.cpp:612). 0.16 chosen to keep a song that never sets
# fxmix at roughly the flat 15 % wet mix this synth used before per-track sends existed.
BASE_FXMIX = 0.16
# TOscillator curve tables (index 0..16 over the segment); 0 = linear
_REL_SAMPLE_CELL = [1.0, 0.970489, 0.781274, 0.546281, 0.399792, 0.289315, 0.212104, 0.157476,
                    0.112613, 0.0817896, 0.0579852, 0.0436415, 0.0308237, 0.0237129, 0.0152593,
                    0.00915555, 0.0]
_REL_SQ_ROOT = [1.0, 0.878906, 0.765625, 0.660156, 0.5625, 0.472656, 0.390625, 0.316406, 0.25,
                0.191406, 0.140625, 0.0976562, 0.0625, 0.0351562, 0.015625, 0.00390625, 0.0]
_REL_SQUARE = [1.0, 0.968246, 0.935414, 0.901388, 0.866025, 0.829156, 0.790569, 0.75, 0.707107,
               0.661438, 0.612372, 0.559017, 0.5, 0.433013, 0.353553, 0.25, 0.0]
_CURVES = {1: _REL_SQUARE, 2: _REL_SQ_ROOT, 3: _REL_SAMPLE_CELL}
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
    osc: ibnk.Oscillator | None = None  # volume oscillator (target 0) if the bank has one
    direct_release: int = 0  # percussion PER2 / note-off release in 1/600 s units
    send_l: float = 0.0  # fx-line send, panned like the dry signal
    send_r: float = 0.0
    pitch_osc: ibnk.Oscillator | None = None  # OSCT target 1: a pitch curve over the note
    vib: Vibrato | None = None  # the track's pitch LFO, None when it never has depth


class Vibrato:
    """A track's ``JASystem::TVibrate`` over the whole song: piecewise-constant depth and
    rate set by the E5/E6/F4 commands, with the counter carried across the changes."""

    def __init__(self, changes: list[tuple[float, float, float]]):
        # (start second, depth, rate), always starting at 0 with the engine defaults
        self.times = np.array([c[0] for c in changes], dtype=np.float64)
        self.depths = np.array([c[1] for c in changes], dtype=np.float64)
        self.rates = np.array([c[2] for c in changes], dtype=np.float64)
        # the counter never resets, so each segment starts where the previous one ended
        steps = self.rates[:-1] * np.diff(self.times) * DRIVER_HZ
        self.phase0 = np.concatenate([[0.0], np.cumsum(steps)])

    def active(self, start: float, end: float) -> bool:
        """True if any depth is non-zero while the voice sounds - depth 0 returns a flat
        1.0 (JASTrack.cpp:1543), so a silent LFO is worth skipping."""
        i = max(int(np.searchsorted(self.times, start, side="right")) - 1, 0)
        j = int(np.searchsorted(self.times, end, side="right"))
        return bool(np.any(self.depths[i:j] != 0.0))

    def ratio(self, secs: np.ndarray) -> np.ndarray:
        """Frequency ratio at each of ``secs``."""
        i = np.clip(np.searchsorted(self.times, secs, side="right") - 1, 0, len(self.times) - 1)
        phase = self.phase0[i] + self.rates[i] * (secs - self.times[i]) * DRIVER_HZ
        phase = np.mod(phase, VIB_WRAP)
        sine = np.sin(np.pi * phase / 2.0)
        return np.exp2(VIB_SEMITONES / 12.0 * self.depths[i] * sine)


def _track_curves(seq: Sequence) -> tuple[dict[int, Vibrato], dict[int, list[tuple[float, float]]]]:
    """Per-track vibrato and fxmix timelines from the sequence's events."""
    vib_changes: dict[int, list[tuple[float, float, float]]] = {}
    fx: dict[int, list[tuple[float, float]]] = {}
    for e in seq.events:
        if e.kind == "vibrato":
            depth, rate = e.value  # type: ignore[misc]
            vib_changes.setdefault(e.track, [(0.0, 0.0, 1.0 / 18.0)]).append((e.sec, depth, rate))
        elif e.kind == "param" and e.value[0] == 2:  # type: ignore[index]
            fx.setdefault(e.track, [(0.0, 0.0)]).append((e.sec, float(e.value[1])))  # type: ignore[index]
    vibs = {t: Vibrato(c) for t, c in vib_changes.items() if any(d for _s, d, _r in c)}
    return vibs, fx


def _fxmix_at(changes: list[tuple[float, float]] | None, sec: float) -> float:
    """Track fxmix (timed parameter 2) in force at ``sec``."""
    if not changes:
        return 0.0
    value = 0.0
    for t, v in changes:
        if t > sec:
            break
        value = v
    return value


def _segment(start: float, target: float, n: int, mode: int) -> np.ndarray:
    """One envelope row: phase moves start -> target over n samples along the mode's curve."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.linspace(0.0, 1.0, n, endpoint=False, dtype=np.float32)
    curve = _CURVES.get(mode)
    if curve is None:
        frac = t
    else:
        # TOscillator indexes the 16-entry table by the remaining fraction of the segment
        tab = np.asarray(curve, dtype=np.float32)
        idx = (1.0 - t) * 16.0
        i0 = np.clip(idx.astype(np.int64), 0, 15)
        frac = 1.0 - (tab[i0] + (idx - i0) * (tab[i0 + 1] - tab[i0]))
    return (start + (target - start) * frac).astype(np.float32)


def _run_table(table, phase: float, max_samples: int, out_rate: int) -> tuple[np.ndarray, float, bool]:
    """Play oscillator rows until hold / stop / the sample budget. Returns (envelope,
    final phase, reached_stop)."""
    parts: list[np.ndarray] = []
    total = 0
    pos = 0
    guard = 0
    while table and pos < len(table) and total < max_samples and guard < 64:
        guard += 1
        mode, time, value = table[pos]
        if mode == 15:  # stop
            return (np.concatenate(parts) if parts else np.zeros(0, np.float32)), phase, True
        if mode == 14:  # hold
            break
        if mode == 13:  # loop back to row `value`
            pos = max(0, min(int(value), len(table) - 1))
            if table[pos][0] in (13, 14, 15):
                break
            continue
        target = value / 32768.0
        n = int(round(time * OSC_TIME_UNIT * out_rate))
        n = min(n, max_samples - total)
        if n > 0:
            parts.append(_segment(phase, target, n, mode))
            total += n
        phase = target
        pos += 1
    env = np.concatenate(parts) if parts else np.zeros(0, np.float32)
    if len(env) < max_samples:  # hold the last level
        env = np.concatenate([env, np.full(max_samples - len(env), phase, dtype=np.float32)])
    return env, phase, False


def _osc_envelope(v: Voice, held_samples: int, out_rate: int) -> np.ndarray:
    """Volume envelope for a voice with oscillator tables: attack/hold while the note is on,
    then the release table (or a direct release) down to silence."""
    o = v.osc
    attack, phase, stopped = _run_table(o.table, 0.0, held_samples, out_rate)
    if stopped:
        return attack * o.width + o.vertex
    if v.direct_release or not o.rel_table:
        units = v.direct_release if v.direct_release else int(v.release_sec / OSC_TIME_UNIT)
        n = max(int(units * OSC_TIME_UNIT * out_rate), 1)
        rel = _segment(phase, 0.0, n, 0)
    else:
        rel, _end, _stopped = _run_table(o.rel_table, phase, int(4.0 * out_rate), out_rate)
        # a release table that holds above zero is cut off where it stops falling
        below = np.nonzero(rel <= 1e-3)[0]
        if len(below):
            rel = rel[: int(below[0]) + 1]
    return np.concatenate([attack, rel]) * o.width + o.vertex


def _pitch_curve(o: ibnk.Oscillator, held_samples: int, length: int, out_rate: int) -> np.ndarray:
    """Frequency-ratio curve of an OSCT target-1 oscillator: ``TChannel::effectOsc`` case 1
    multiplies the channel's rate by phase x width + vertex (JASChannel.cpp:155)."""
    attack, phase, stopped = _run_table(o.table, 0.0, held_samples, out_rate)
    if stopped or not o.rel_table:
        curve = attack
    else:
        rel, _end, _stopped = _run_table(o.rel_table, phase, max(length - len(attack), 0), out_rate)
        curve = np.concatenate([attack, rel])
    curve = curve * o.width + o.vertex
    if len(curve) < length:  # a pitch curve holds its last value, it does not fall to zero
        tail = curve[-1] if len(curve) else 1.0
        curve = np.concatenate([curve, np.full(length - len(curve), tail, dtype=np.float32)])
    # a zero ratio would freeze the read pointer; the engine cannot reach it either
    return np.clip(curve[:length], 1.0 / 64.0, 64.0)


def _region_for(bank: ibnk.Bank, note: Note):
    """-> (vel region, volume mult, pitch mult, pan override, is_percussion, volume osc,
    direct release, pitch osc)."""
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
        return (vr, perc.volume * vr.volume, perc.pitch * vr.pitch, perc.pan, True, None,
                perc.release & 0x3FFF, None)
    vr = prog.region(note.key, note.velocity)
    if vr is None:
        return None
    osc = next((o for o in prog.oscillators if o.target == ibnk.OSC_VOLUME and o.table), None)
    posc = next((o for o in prog.oscillators if o.target == ibnk.OSC_PITCH and o.table), None)
    return vr, prog.volume * vr.volume, prog.pitch * vr.pitch, None, False, osc, 0, posc


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
    missing = {"bank": 0, "program": 0, "wave": 0, "vibrato_voices": 0}
    limit = seconds if seconds is not None else seq.seconds
    vibs, fxmix = _track_curves(seq)
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
        vr, vol_mult, pitch_mult, pan_override, is_perc, osc, direct_rel, posc = reg
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
        if n.release and osc is not None:
            direct_rel = n.release  # note-off release byte: 1/600 s units like PER2
        # the fx send is a second, quieter copy of the same panned signal
        # (JASChannelMgr.cpp:44-45 route buses 2/3 through sin(pi/2 * fxmix))
        fx = min(max(_fxmix_at(fxmix.get(n.track), n.start_sec) + BASE_FXMIX, 0.0), 1.0)
        send = math.sin(fx * math.pi / 2.0)
        vib = vibs.get(n.track)
        if vib is not None and not vib.active(n.start_sec, end_sec):
            vib = None
        if vib is not None:
            missing["vibrato_voices"] += 1
        voices.append(
            Voice(n.start_sec, end_sec, release, wave, pcm, ratio, gain_l, gain_r, osc,
                  direct_rel, gain_l * send, gain_r * send, posc, vib)
        )
    return voices, missing


def _render_voice(v: Voice, out_rate: int, total_frames: int) -> tuple[int, np.ndarray] | None:
    """-> (first output frame, mono float32 block) for one voice."""
    start = int(round(v.start_sec * out_rate))
    if start >= total_frames:
        return None
    held = max(v.end_sec - v.start_sec, 0.0)
    held_samples = int(round(held * out_rate))
    env_osc: np.ndarray | None = None
    if v.osc is not None:
        env_osc = _osc_envelope(v, held_samples, out_rate)
        length = len(env_osc)
    else:
        length = int(round((held + v.release_sec * 4.0) * out_rate))
    modulated = v.pitch_osc is not None or v.vib is not None
    if not v.wave.loop and not modulated:
        # a one-shot sample cannot sound past its own end
        length = min(length, int(len(v.pcm) / v.ratio) + 1)
    length = min(length, total_frames - start)
    if length <= 0:
        return None
    if modulated:
        # the read pointer has to be integrated, not scaled: the rate moves under it
        rate = np.full(length, v.ratio, dtype=np.float64)
        if v.pitch_osc is not None:
            rate *= _pitch_curve(v.pitch_osc, held_samples, length, out_rate)
        if v.vib is not None:
            rate *= v.vib.ratio(v.start_sec + np.arange(length, dtype=np.float64) / out_rate)
        pos = np.cumsum(rate) - rate[0]
        if not v.wave.loop:
            past = np.nonzero(pos >= len(v.pcm))[0]
            if len(past):
                length = int(past[0]) + 1
                pos = pos[:length]
    else:
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
    if env_osc is not None:
        env = env_osc[:length]
        if len(env) < length:
            env = np.concatenate([env, np.zeros(length - len(env), dtype=np.float32)])
        return start, samples * np.clip(env, 0.0, 4.0)
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
    send = np.zeros((total, 2), dtype=np.float32)  # the fx line, a second bus per channel
    for v in voices:
        r = _render_voice(v, out_rate, total)
        if r is None:
            continue
        start, block = r
        end = start + len(block)
        mix[start:end, 0] += block * v.gain_l
        mix[start:end, 1] += block * v.gain_r
        if v.send_l or v.send_r:
            send[start:end, 0] += block * v.send_l
            send[start:end, 1] += block * v.send_r
    if len(mix) > out_rate // 10 and float(np.max(np.abs(send))) > 1e-6:
        mix = mix + reverb(send, out_rate) * REVERB_RETURN
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


def _comb(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    """y[n] = x[n] + g y[n - delay], block-wise (each block only depends on the previous)."""
    y = np.zeros_like(x)
    n = len(x)
    for start in range(0, n, delay):
        end = min(start + delay, n)
        y[start:end] = x[start:end]
        if start >= delay:
            y[start:end] += g * y[start - delay : start - delay + (end - start)]
    return y


def _allpass(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    """y[n] = -g x[n] + x[n - delay] + g y[n - delay]."""
    y = np.zeros_like(x)
    n = len(x)
    for start in range(0, n, delay):
        end = min(start + delay, n)
        y[start:end] = -g * x[start:end]
        if start >= delay:
            w = end - start
            y[start:end] += x[start - delay : start - delay + w] + g * y[start - delay : start - delay + w]
    return y


def reverb(mix: np.ndarray, out_rate: int) -> np.ndarray:
    """Schroeder reverb (Freeverb-ish tunings scaled to the rate), mono send, stereo return."""
    mono = mix.mean(axis=1).astype(np.float32)
    scale = out_rate / 44100.0
    combs = [int(d * scale) for d in (1116, 1188, 1277, 1356)]
    wet = np.zeros_like(mono)
    for d in combs:
        wet += _comb(mono, max(d, 1), 0.84)
    wet *= 0.25
    for d in (int(556 * scale), int(441 * scale)):
        wet = _allpass(wet, max(d, 1), 0.5)
    out = np.empty_like(mix)
    out[:, 0] = wet
    out[:, 1] = np.roll(wet, int(0.0007 * out_rate))  # a hair of decorrelation
    return out
