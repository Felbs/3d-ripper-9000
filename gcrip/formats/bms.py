"""BMS - JAudio sequenced music (``Audiores/Seqs/JaiSeqs.arc`` -> ``bms/*.bms``).

A re-implementation of the parse loop in ``JASystem::TSeqParser::parseSeq``
(JASSeqParser.cpp) plus the track/register plumbing of ``JASystem::TTrack``
that the Wind Waker songs actually exercise.  The byte code, per the decomp:

    00-7F      note on: key; flags byte (bits 0-2 voice id, bits 3-4 duration
               byte count, bit 5 tie, bit 6 sweep, bit 7 key-from-register);
               velocity; voice 0 additionally carries gate% and a duration
    80 / 88    wait: 1 / 2 byte tick count
    81-87, F9  note off (voice id in the low 3 bits; bit 3 = release byte follows)
    9x         set timed parameter (volume 0, pitch 1, fxmix 2, pan 3, dolby 4):
               target byte, then a value and an optional move time, encoded per the
               low nibble (``cmdSetParam``)
    Ax         register write with arithmetic (``TTrack::writeRegParam``)
    Bx         command with per-argument register indirection (``RegCmd_Process``)
    C0-FF      ``sCmdPList`` commands with argument sizes from ``Arglist``

Timing: ``TTrack::updateTempo`` gives ``ticks per DSP frame = timebase * tempo /
dacRate * 4/3``, i.e. seconds per tick = 60 / (tempo * timebase) - tempo is BPM
and timebase ticks per beat.  Ports (game <-> song communication) read as 0,
``syncCPU`` returns 0, interrupts are never raised, which selects the "plain"
layer of dynamic songs such as sea.bms.

The player runs every open track in tick order, emits :class:`Note` and
:class:`Event` records with absolute ticks and seconds, and stops at a time
limit or an instruction cap (songs loop forever).
"""

from __future__ import annotations

import heapq
import struct
from dataclasses import dataclass, field

# JASystem::Arglist: (argument count, 2-bit type per argument: 0 byte, 1 u16, 2 u24, 3 register)
ARGLIST: tuple[tuple[int, int], ...] = (
    (0, 0x0000), (2, 0x0008), (2, 0x0008), (1, 0x0002), (0, 0x0000), (0, 0x0000),
    (1, 0x0000), (1, 0x0002), (0, 0x0000), (1, 0x0001), (0, 0x0000), (2, 0x0000),
    (2, 0x000C), (1, 0x0000), (1, 0x0000), (1, 0x0003), (0, 0x0000), (2, 0x000C),
    (2, 0x000C), (0, 0x0000), (1, 0x0000), (1, 0x0000), (1, 0x0000), (2, 0x0008),
    (5, 0x0155), (1, 0x0000), (1, 0x0000), (1, 0x0000), (1, 0x0001), (2, 0x0004),
    (1, 0x0000), (2, 0x0008), (1, 0x0000), (0, 0x0000), (0, 0x0000), (0, 0x0000),
    (2, 0x0004), (1, 0x0000), (1, 0x0001), (1, 0x0001), (0, 0x0000), (0, 0x0000),
    (1, 0x0002), (5, 0x0000), (4, 0x0055), (1, 0x0002), (1, 0x0002), (3, 0x0000),
    (1, 0x0000), (1, 0x0000), (3, 0x0028), (1, 0x0000), (1, 0x0000), (0, 0x0000),
    (0, 0x0000), (0, 0x0000), (0, 0x0000), (0, 0x0000), (1, 0x0001), (0, 0x0000),
    (0, 0x0000), (1, 0x0001), (1, 0x0001), (0, 0x0000),
)

CMD_OPEN_TRACK = 0xC1
CMD_OPEN_TRACK_BROS = 0xC2
CMD_CALL = 0xC4
CMD_RET = 0xC6
CMD_JMP = 0xC8
CMD_LOOP_S = 0xC9
CMD_LOOP_E = 0xCA
CMD_READ_PORT = 0xCB
CMD_WRITE_PORT = 0xCC
CMD_CHECK_PORT_IMPORT = 0xCD
CMD_CHECK_PORT_EXPORT = 0xCE
CMD_WAIT_REG = 0xCF
CMD_SET_LAST_NOTE = 0xD4
CMD_TIME_RELATE = 0xD5
CMD_SIMPLE_ADSR = 0xD8
CMD_TRANSPOSE = 0xD9
CMD_CLOSE_TRACK = 0xDA
CMD_SYNC_CPU = 0xE7
CMD_WAIT_24 = 0xEA
CMD_CHECK_WAVE = 0xFA
CMD_PRINTF = 0xFB
CMD_TEMPO = 0xFD
CMD_TIMEBASE = 0xFE
CMD_FINISH = 0xFF

PARAM_VOLUME = 0
PARAM_PITCH = 1
PARAM_FXMIX = 2
PARAM_PAN = 3

REG_BANK = 0x20
REG_PROGRAM = 0x21
REG_BANKPROG = 6  # TRegisterParam::field_0xc
REG_PITCH_RANGE = 7  # TRegisterParam::field_0xe, default 12 semitones

DEFAULT_TEMPO = 120
DEFAULT_TIMEBASE = 48


class BmsError(ValueError):
    pass


@dataclass
class Note:
    track: int
    start: int  # ticks
    key: int
    velocity: int
    bank: int
    program: int
    volume: float  # product over the track chain of vol^2 (JAudio volume mode 0)
    pan: float  # 0 left .. 1 right
    pitch: float  # frequency ratio from the pitch registers
    end: int | None = None  # ticks; None = still sounding at the time limit
    release: int = 0  # release time from the note-off byte (0 = instrument default)
    start_sec: float = 0.0
    end_sec: float = 0.0


@dataclass
class Event:
    track: int
    tick: int
    kind: str
    value: object = None
    sec: float = 0.0


@dataclass
class Sequence:
    notes: list[Note] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    tempo_map: list[tuple[int, int]] = field(default_factory=list)  # (tick, bpm)
    timebase: int = DEFAULT_TIMEBASE
    ticks: int = 0  # last tick reached
    seconds: float = 0.0
    tracks: int = 0
    stopped_by: str = ""

    def tick_to_seconds(self, tick: int) -> float:
        secs = 0.0
        last_tick, tempo = 0, DEFAULT_TEMPO
        for t, bpm in self.tempo_map:
            if t >= tick:
                break
            secs += (t - last_tick) * 60.0 / (max(tempo, 1) * self.timebase)
            last_tick, tempo = t, bpm
        return secs + (tick - last_tick) * 60.0 / (max(tempo, 1) * self.timebase)


def _s8(v: int) -> int:
    return v - 256 if v & 0x80 else v


def _s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class _Track:
    def __init__(self, player: _Player, index: int, parent: _Track | None, pos: int):
        self.player = player
        self.index = index
        self.parent = parent
        self.pos = pos
        self.children: dict[int, _Track] = {}
        self.regs = [0] * 0x40
        self.regs[REG_PITCH_RANGE] = 12
        self.bank = parent.bank if parent else 0
        self.program = parent.program if parent else 0
        if parent:
            self.regs[REG_PITCH_RANGE] = parent.regs[REG_PITCH_RANGE]
        self.flag = 0  # TRegisterParam condition flag
        self.transpose = 0
        self.volume = 1.0
        self.pitch = 0.0
        self.pan = 0.5
        self.volume_mode = 0
        self.call_stack: list[int] = []
        self.loop_stack: list[tuple[int, int]] = []  # (position, remaining)
        self.voices: dict[int, Note] = {}
        self.last_note = 0
        self.tie_mode = False
        self.open = True
        self.wake = 0
        self.time_relate = 0

    # --- byte reading -------------------------------------------------------------------
    def read_byte(self) -> int:
        d = self.player.data
        if self.pos >= len(d):
            raise BmsError(f"track {self.index} ran off the end of the sequence")
        b = d[self.pos]
        self.pos += 1
        return b

    def read16(self) -> int:
        return (self.read_byte() << 8) | self.read_byte()

    def read24(self) -> int:
        return (self.read16() << 8) | self.read_byte()

    # --- registers (TTrack::readReg16 / readReg32 / writeRegDirect) ----------------------
    def reg16(self, target: int) -> int:
        if target == REG_BANK:
            return self.bank & 0xFF
        if target == REG_PROGRAM:
            return self.program & 0xFF
        if target == 0x22:
            return ((self.regs[0] & 0xFF) << 8) | (self.regs[1] & 0xFF)
        if target == 0x2C:
            return sum(1 << i for i, c in self.children.items() if c.open)
        if target == 0x2D:
            return sum(1 << i for i in range(8) if i not in self.voices)
        if target == 0x30:
            return self.loop_stack[-1][1] if self.loop_stack else 0
        if target == REG_BANKPROG:
            return ((self.bank & 0xFF) << 8) | (self.program & 0xFF)
        if 0 <= target < 0x40:
            return self.regs[target] & 0xFFFF
        return 0

    def reg32(self, target: int) -> int:
        if 0x28 <= target <= 0x2B:
            return self.regs[target]
        if target == 0x23:
            return (self.reg16(4) << 16) | self.reg16(5)
        return self.reg16(target)

    def exchange(self, target: int) -> int:
        """TTrack::exchangeRegisterValue: registers below 0x40, ports (always 0) above."""
        if target < 0x40:
            return self.reg32(target)
        return 0

    def write_reg(self, target: int, value: int) -> None:
        value &= 0xFFFF
        if target in (0, 1, 2):
            value &= 0xFF
            self.regs[target] = value
            self.flag = _s8(value) & 0xFFFF
            return
        if target in (REG_BANK, REG_PROGRAM):
            return
        if target == 0x22:
            self.write_reg(0, value >> 8)
            self.regs[1] = value & 0xFF
            self.flag = value
            return
        if target < 0x40:
            self.regs[target] = value
        self.flag = value

    def effective_transpose(self) -> int:
        return self.transpose + (self.parent.effective_transpose() if self.parent else 0)

    def effective_volume(self) -> float:
        v = self.volume * self.volume if self.volume_mode == 0 else self.volume
        return v * (self.parent.effective_volume() if self.parent else 1.0)

    def effective_pitch(self) -> float:
        """Player::pitchToCent: semitones = pitch * 4 * pitch-range register."""
        semis = self.pitch * 4.0 * self.regs[REG_PITCH_RANGE]
        ratio = 2.0 ** (semis / 12.0)
        return ratio * (self.parent.effective_pitch() if self.parent else 1.0)


class _Player:
    def __init__(self, data: bytes, max_seconds: float, max_ops: int):
        self.data = data
        self.seq = Sequence()
        self.max_seconds = max_seconds
        self.max_ops = max_ops
        self.ops = 0
        self.tempo = DEFAULT_TEMPO
        self.timebase = DEFAULT_TIMEBASE
        self.tick = 0
        self.tracks: list[_Track] = []
        self.queue: list[tuple[int, int, _Track]] = []
        self.serial = 0
        self.tempo_map: list[tuple[int, int]] = [(0, DEFAULT_TEMPO)]
        self.timebase_set = False

    # --- track management ----------------------------------------------------------------
    def add_track(self, parent: _Track | None, pos: int) -> _Track:
        t = _Track(self, len(self.tracks), parent, pos)
        t.wake = self.tick
        self.tracks.append(t)
        self.schedule(t)
        return t

    def schedule(self, t: _Track) -> None:
        self.serial += 1
        heapq.heappush(self.queue, (t.wake, self.serial, t))

    def event(self, t: _Track, kind: str, value=None) -> None:
        self.seq.events.append(Event(t.index, self.tick, kind, value))

    def seconds_at(self, tick: int) -> float:
        secs = 0.0
        last_tick, tempo = 0, DEFAULT_TEMPO
        for tt, bpm in self.tempo_map:
            if tt >= tick:
                break
            secs += (tt - last_tick) * 60.0 / (max(tempo, 1) * self.timebase)
            last_tick, tempo = tt, bpm
        return secs + (tick - last_tick) * 60.0 / (max(tempo, 1) * self.timebase)

    # --- main loop -----------------------------------------------------------------------
    def run(self) -> Sequence:
        self.add_track(None, 0)
        stopped = "finished"
        while self.queue:
            wake, _, t = heapq.heappop(self.queue)
            if not t.open:
                continue
            self.tick = wake
            if self.seconds_at(self.tick) > self.max_seconds:
                stopped = "time limit"
                break
            if self.ops > self.max_ops:
                stopped = "instruction cap"
                break
            if self.step(t) and t.open:
                self.schedule(t)
        seq = self.seq
        seq.tempo_map = self.tempo_map
        seq.timebase = self.timebase
        seq.ticks = self.tick
        seq.tracks = len(self.tracks)
        seq.stopped_by = stopped
        for n in seq.notes:
            n.start_sec = self.seconds_at(n.start)
            n.end_sec = self.seconds_at(n.end) if n.end is not None else self.max_seconds
        for e in seq.events:
            e.sec = self.seconds_at(e.tick)
        seq.seconds = min(self.seconds_at(self.tick), self.max_seconds)
        return seq

    def step(self, t: _Track) -> bool:
        """Parse until the track waits (True) or finishes (False)."""
        while True:
            self.ops += 1
            if self.ops > self.max_ops:
                return True
            op = t.read_byte()
            if op < 0x80:
                r = self.note_on(t, op)
            elif (op & 0xF0) == 0x80 and not (op & 0x07):
                r = self.wait(t, t.read16() if op == 0x88 else t.read_byte())
            elif (op & 0xF0) == 0x80 or op == 0xF9:
                r = self.note_off(t, op)
            elif (op & 0xF0) == 0x90:
                r = self.set_param(t, op & 0xF)
            elif (op & 0xF0) == 0xA0:
                r = self.write_reg_param(t, op & 0xF)
            elif (op & 0xF0) == 0xB0:
                r = self.reg_cmd(t, (op >> 3) & 1, op & 7)
            else:
                r = self.command(t, op, 0)
            if r == 1:
                return True
            if r == 3:
                self.close_track(t)
                return False

    def wait(self, t: _Track, ticks: int) -> int:
        if ticks <= 0:
            return 0
        t.wake = self.tick + ticks
        return 1

    def close_track(self, t: _Track) -> None:
        t.open = False
        for v in list(t.voices):
            self.voice_off(t, v, 0)
        for c in t.children.values():
            self.close_track(c)
        self.event(t, "close")

    # --- notes ---------------------------------------------------------------------------
    def voice_off(self, t: _Track, voice: int, release: int) -> None:
        n = t.voices.pop(voice, None)
        if n is not None and n.end is None:
            n.end = self.tick
            n.release = release

    def note_on(self, t: _Track, key: int) -> int:
        flags = t.read_byte()
        if flags & 0x80:
            key = t.exchange(key) & 0xFF
        key = (key + t.effective_transpose()) & 0xFF
        connect = (flags >> 5) & 3
        sweep_target = None
        if connect & 2:
            sweep_target = key
            key = t.last_note
        vel = t.read_byte()
        if vel & 0x80:
            vel = t.exchange(vel & 0x7F) & 0xFF
        voice = flags & 7
        duration = -1
        gate = 100
        if voice == 0:
            gate = t.read_byte()
            if gate & 0x80:
                gate = t.exchange(gate & 0x7F) & 0xFF
            count = (flags >> 3) & 3
            duration = 0
            for _ in range(count):
                duration = (duration << 8) | t.read_byte()
            if count == 1 and duration & 0x80:
                duration = t.exchange(duration & 0x7F)
        else:
            if (flags >> 3) & 3:
                voice = t.exchange(voice - 1) & 7
            if connect & 1:
                t.exchange(t.read_byte())
                connect ^= 1
        tie = bool(connect & 1)
        if t.tie_mode and voice in t.voices:
            # gateOn: retarget the sounding voice instead of starting a new one
            cur = t.voices[voice]
            cur.key = key
            if not tie and duration >= 0:
                cur.end = self.tick + max(1, duration * gate // 100)
                del t.voices[voice]
        else:
            self.voice_off(t, voice, 0)
            note = Note(
                t.index, self.tick, key, min(vel, 127), t.bank, t.program,
                t.effective_volume(), t.pan, t.effective_pitch(),
            )
            self.seq.notes.append(note)
            if duration >= 0 and not tie:
                note.end = self.tick + max(1, duration * gate // 100)
            else:
                t.voices[voice] = note
        t.tie_mode = tie
        if sweep_target is not None:
            key = sweep_target
        t.last_note = key
        if duration < 0:
            return 0
        t.wake = self.tick + (duration if duration else 1)
        return 1

    def note_off(self, t: _Track, op: int) -> int:
        if op == 0xF9:
            r = t.read_byte()
            voice = t.exchange(r & 7) & 0xFF
            op = 0x80 + (voice & 7)
            if r & 0x80:
                op |= 0x08
        release = 0
        if op & 0x08:
            release = t.read_byte()
            if release > 100:
                release = (release - 98) * 20
        self.voice_off(t, op & 7, release)
        return 0

    # --- parameters / registers --------------------------------------------------------
    def set_param(self, t: _Track, low: int) -> int:
        target = t.read_byte()
        kind = low & 0xC
        if kind == 0:
            data = _s16(t.reg16(t.read_byte()))
        elif kind == 4:
            data = t.read_byte()
        elif kind == 8:
            b = t.read_byte()
            data = _s16((b << 8) if b & 0x80 else ((b << 8) | (b << 1)))
        else:
            data = _s16(t.read16())
        mode = low & 3
        move = -1
        if mode == 1:
            move = _s16(t.reg16(t.read_byte()))
        elif mode == 2:
            move = t.read_byte()
        elif mode == 3:
            move = t.read16()
        value = data / 0x7FFF
        if target == PARAM_VOLUME:
            t.volume = max(0.0, value)
        elif target == PARAM_PITCH:
            t.pitch = value
        elif target == PARAM_PAN:
            t.pan = min(1.0, max(0.0, value))
        self.event(t, "param", (target, value, move))
        return 0

    def write_reg_param(self, t: _Track, param: int) -> int:
        size = param & 0xC
        op = param & 3
        tbl_shift = 0
        if param == 11:
            size, op = 0, 11
        elif param == 10:
            b = t.read_byte()
            size, tbl_shift, op = b & 0xC, (b >> 4) + 4, 10
        elif param == 9:
            b = t.read_byte()
            size, op = b & 0xC, b & 0xF0
            if size == 8:
                size = 16
        dest = t.read_byte()
        tbl_base = t.reg32(t.read_byte()) if op == 10 else 0
        if size == 0:
            val = _s16(t.reg16(t.read_byte()))
        elif size == 4:
            val = t.read_byte()
        elif size == 12:
            val = _s16(t.read16())
        elif size == 8:
            b = t.read_byte()
            val = _s16((b << 8) if b & 0x80 else ((b << 8) | (b << 1)))
        else:
            val = -1
        cur = _s16(t.reg16(dest))
        if op == 1:
            if size == 4:
                val = _s8(val)
            val = cur + val
        elif op == 2:
            prod = (cur & 0xFFFF) * (val & 0xFFFF)
            t.write_reg(4, prod >> 16)
            t.write_reg(5, prod & 0xFFFF)
            return 0
        elif op == 3:
            t.flag = (cur - val) & 0xFFFF
            return 0
        elif op == 11:
            val = cur - val
        elif op in (0x10, 0x20):
            if size == 4:
                val = _s8(val)
            base = (cur & 0xFFFF) if op == 0x10 else cur
            val = base >> -val if val < 0 else base << val
        elif op == 0x30:
            val &= cur
        elif op == 0x40:
            val |= cur
        elif op == 0x50:
            val ^= cur
        elif op == 0x60:
            val = -cur
        elif op == 0x90:
            val = 0  # Player::getRandomS32() % val - deterministic stand-in
        elif op == 0xA:
            val = self.load_table(tbl_base, val, tbl_shift)
        val &= 0xFFFF
        if dest == REG_PROGRAM:
            t.program = val & 0xFF
            self.event(t, "program", (t.bank, t.program))
            return 0
        if dest == REG_BANK:
            t.bank = val & 0xFF
            self.event(t, "bank", (t.bank, t.program))
            return 0
        if dest == REG_BANKPROG:
            t.bank, t.program = val >> 8, val & 0xFF
            self.event(t, "program", (t.bank, t.program))
            return 0
        if dest in (0x2E, 0x2F):
            return 0
        if 0x28 <= dest <= 0x2B:
            t.regs[dest] = val
            return 0
        t.write_reg(dest, val)
        return 0

    def load_table(self, base: int, index: int, kind: int) -> int:
        """TTrack::loadTbl: fetch entry `index` of a table at `base` (size from kind)."""
        width = {4: 1, 5: 2, 6: 4}.get(kind & 7, 1)
        p = base + index * width
        if p < 0 or p + width > len(self.data):
            return 0
        return int.from_bytes(self.data[p : p + width], "big")

    def reg_cmd(self, t: _Track, indirect_cmd: int, nbits: int) -> int:
        cmd = t.read_byte()
        if indirect_cmd:
            cmd = t.exchange(cmd) & 0xFF
        mask = 0
        if not indirect_cmd or nbits:
            b = t.read_byte()
            m = 3
            for _ in range(nbits + 1):
                if b & 0x80:
                    mask |= m
                b = (b << 1) & 0xFF
                m <<= 2
        if cmd < 0xC0:
            return 0
        return self.command(t, cmd, mask)

    # --- C0+ commands --------------------------------------------------------------------
    def command(self, t: _Track, op: int, mask: int) -> int:
        if op == CMD_CALL:
            return self.call(t)
        if op == CMD_JMP:
            return self.jmp(t)
        if op == CMD_PRINTF:
            return self.printf(t)
        count, types = ARGLIST[op - 0xC0]
        types |= mask
        args = []
        for _ in range(count):
            kind = types & 3
            if kind == 0:
                args.append(t.read_byte())
            elif kind == 1:
                args.append(t.read16())
            elif kind == 2:
                args.append(t.read24())
            else:
                args.append(t.exchange(t.read_byte()))
            types >>= 2
        if op in (CMD_OPEN_TRACK, CMD_OPEN_TRACK_BROS):
            owner = t if op == CMD_OPEN_TRACK else t.parent
            if owner is None:
                return 0
            child_id = args[0] & 0xF
            old = owner.children.get(child_id)
            if old is not None:
                self.close_track(old)
            owner.children[child_id] = self.add_track(owner, args[1])
            self.event(t, "open_track", (child_id, args[1]))
        elif op == CMD_RET:
            if self.condition(t, args[0]):
                if not t.call_stack:
                    return 3
                t.pos = t.call_stack.pop()
        elif op == CMD_LOOP_S:
            t.loop_stack.append((t.pos, args[0]))
            if len(t.loop_stack) > 8:
                t.loop_stack.pop(0)
        elif op == CMD_LOOP_E:
            if t.loop_stack:
                pos, remaining = t.loop_stack.pop()
                if remaining:
                    remaining -= 1
                if remaining:
                    t.loop_stack.append((pos, remaining))
                    t.pos = pos
        elif op == CMD_READ_PORT:
            t.write_reg(args[1], 0)
        elif op in (CMD_CHECK_PORT_IMPORT, CMD_CHECK_PORT_EXPORT, CMD_CHECK_WAVE, CMD_SYNC_CPU):
            t.flag = 0
        elif op in (CMD_WAIT_REG, CMD_WAIT_24):
            return self.wait(t, args[0])
        elif op == CMD_SET_LAST_NOTE:
            t.last_note = (args[0] + t.effective_transpose()) & 0xFF
        elif op == CMD_TIME_RELATE:
            t.time_relate = args[0]
        elif op == CMD_TRANSPOSE:
            t.transpose = _s8(args[0] & 0xFF)
        elif op == CMD_CLOSE_TRACK:
            c = t.children.pop(args[0] & 0xF, None)
            if c is not None:
                self.close_track(c)
        elif op == 0xF3:  # volumeMode
            t.volume_mode = args[0]
        elif op == CMD_TEMPO:
            self.tempo = max(1, args[0])
            if self.tempo_map and self.tempo_map[-1][0] == self.tick:
                self.tempo_map[-1] = (self.tick, self.tempo)
            else:
                self.tempo_map.append((self.tick, self.tempo))
            self.event(t, "tempo", self.tempo)
        elif op == CMD_TIMEBASE:
            if args[0] > 0 and not self.timebase_set:
                self.timebase = args[0]
                self.timebase_set = True
            self.event(t, "timebase", args[0])
        elif op == CMD_FINISH:
            return 3
        elif op == CMD_SIMPLE_ADSR:
            self.event(t, "adsr", tuple(args))
        return 0

    def condition(self, t: _Track, flag: int) -> bool:
        v = t.flag & 0xFFFF
        c = flag & 0xF
        if c == 0:
            return True
        if c == 1:
            return v == 0
        if c == 2:
            return v != 0
        if c == 3:
            return v == 1
        if c == 4:
            return v >= 0x8000
        if c == 5:
            return v < 0x8000
        return False

    def get24(self, off: int) -> int:
        if off + 3 > len(self.data):
            return 0
        return int.from_bytes(self.data[off : off + 3], "big")

    def call(self, t: _Track) -> int:
        flag = t.read_byte()
        if flag & 0x80:
            data = t.reg16(t.read_byte())
            if flag & 0x40:
                offs = t.reg16(t.read_byte()) if flag & 0x20 else t.read24()
                data = self.get24(offs + data * 3)
        else:
            data = t.read24()
        if self.condition(t, flag):
            t.call_stack.append(t.pos)
            if len(t.call_stack) > 8:
                t.call_stack.pop(0)
            t.pos = data
        return 0

    def jmp(self, t: _Track) -> int:
        flag = t.read_byte()
        if flag & 0x80:
            c = t.read_byte()
            if flag & 0x40:
                data = t.reg16(c) & 0xFFFF
                offs = t.reg16(t.read_byte()) if flag & 0x20 else t.read24()
                data = self.get24(offs + data * 3)
            else:
                data = t.reg32(c)
        else:
            data = t.read24()
        if self.condition(t, flag):
            if data >= len(self.data):
                return 3
            t.pos = data
        return 0

    def printf(self, t: _Track) -> int:
        count = 0
        for _ in range(128):
            c = t.read_byte()
            if c == 0:
                break
            if c == ord("\\"):
                if t.read_byte() == 0:
                    break
                continue
            if c == ord("%"):
                if t.read_byte() == 0:
                    break
                count += 1
        for _ in range(count):
            t.read_byte()
        return 0


def play(data: bytes, max_seconds: float = 120.0, max_ops: int = 2_000_000) -> Sequence:
    """Run a .bms and return every note/event with absolute ticks and seconds."""
    if len(data) < 2:
        raise BmsError("empty BMS")
    return _Player(data, max_seconds, max_ops).run()


# --- MIDI export ----------------------------------------------------------------------------


def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append(0x80 | (v & 0x7F))
        v >>= 7
    return bytes(reversed(out))


def to_midi(seq: Sequence) -> bytes:
    """Standard MIDI file (type 1) with one MIDI track per BMS track.

    Tempo and timebase map 1:1 (division = BMS timebase, tempo = BPM); the
    bank goes to CC0, the program (masked to 7 bits) to a program change,
    track volume to CC7 and pan to CC10.  Percussion programs (>= 0xE4) are
    put on channel 10.
    """
    per_track: dict[int, list[tuple[int, int, bytes]]] = {}
    order = 0
    for tr in range(seq.tracks):
        per_track[tr] = []
    for tick, bpm in seq.tempo_map:
        us = int(60_000_000 / max(bpm, 1))
        per_track.setdefault(0, []).append(
            (tick, order, b"\xff\x51\x03" + us.to_bytes(3, "big"))
        )
        order += 1
    chan_of: dict[int, int] = {}
    last_prog: dict[int, tuple[int, int]] = {}
    for n in seq.notes:
        ch = chan_of.setdefault(n.track, 9 if n.program >= 0xE4 else (n.track % 15 + 1) % 16)
        if ch == 9 and n.program < 0xE4:
            ch = 10 if n.track % 2 else 11
            chan_of[n.track] = ch
        msgs = per_track.setdefault(n.track, [])
        if last_prog.get(n.track) != (n.bank, n.program):
            last_prog[n.track] = (n.bank, n.program)
            msgs.append((n.start, order, bytes([0xB0 | ch, 0, n.bank & 0x7F])))
            order += 1
            msgs.append((n.start, order, bytes([0xC0 | ch, n.program & 0x7F])))
            order += 1
        vol = int(min(1.0, n.volume ** 0.5) * 127)
        msgs.append((n.start, order, bytes([0xB0 | ch, 7, vol])))
        order += 1
        msgs.append((n.start, order, bytes([0xB0 | ch, 10, int(n.pan * 127)])))
        order += 1
        msgs.append((n.start, order, bytes([0x90 | ch, n.key & 0x7F, max(1, n.velocity & 0x7F)])))
        order += 1
        end = n.end if n.end is not None else seq.ticks
        msgs.append((max(end, n.start + 1), order, bytes([0x80 | ch, n.key & 0x7F, 0])))
        order += 1
    chunks = []
    for tr in sorted(per_track):
        msgs = sorted(per_track[tr], key=lambda m: (m[0], m[1]))
        body = bytearray()
        last = 0
        for tick, _, msg in msgs:
            body += _vlq(max(0, tick - last)) + msg
            last = max(last, tick)
        body += b"\x00\xff\x2f\x00"
        chunks.append(b"MTrk" + struct.pack(">I", len(body)) + bytes(body))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), max(1, seq.timebase))
    return header + b"".join(chunks)
