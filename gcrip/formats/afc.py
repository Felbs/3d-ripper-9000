"""AFC - JAudio streamed ADPCM (``Audiores/Stream/*.afc`` in Wind Waker).

Layout verified against the Wind Waker decomp (``JAInter::StreamLib`` in
``JAIStreamMgr.cpp`` / ``StreamHeader`` in ``JAIStreamMgr.h``) and against every
stream on the USA disc:

    0x00  u32  data_size     bytes of ADPCM after the 0x20-byte header
    0x04  u32  sample_count  PCM frames per channel
    0x08  u16  sample_rate   32000 or 44100 on the disc
    0x0A  u16  format        2 = raw PCM16, 4 = 4-bit ADPCM (all disc streams)
    0x0C  u16  bit_depth     16 on every disc stream (decoded sample width)
    0x0E  u16  unknown       30 or 60 on the disc (unused by the decoder)
    0x10  u32  loop_flag     non-zero = loops back to loop_start at the end
    0x14  u32  loop_start    loop point, in samples
    0x18  u32  padding
    0x1C  u32  padding

ADPCM data: always stereo, 9-byte frames holding 16 samples, interleaved one
frame per channel (L frame, R frame, ...), so a 16-sample block is 18 bytes -
``LoopInit`` seeks with ``(loop_start >> 4) * 18 + 32`` and ``data_size ==
sample_count // 16 * 18`` on every file.  Frame byte 0 is a header:
high nibble = shift, low nibble = index into the fixed 16-entry coefficient
table (``JAInter::StreamLib::filter_table``); the remaining 8 bytes are 16
signed nibbles, high nibble first.  Each sample is

    s = ((nib << shift) * 2048 + c1 * hist1 + c2 * hist2) >> 11, clamped to s16

with ``hist1``/``hist2`` the previous two output samples of that channel.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

HEADER_SIZE = 0x20
FRAME_BYTES = 9
FRAME_SAMPLES = 16
FORMAT_PCM16 = 2
FORMAT_ADPCM = 4

# JAInter::StreamLib::filter_table (JAIStreamMgr.cpp), as (c1, c2) pairs.
COEFS: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0000),
    (0x0800, 0x0000),
    (0x0000, 0x0800),
    (0x0400, 0x0400),
    (0x1000, -0x0800),
    (0x0E00, -0x0600),
    (0x0C00, -0x0400),
    (0x1200, -0x0A00),
    (0x1068, -0x08C8),
    (0x12C0, -0x08FC),
    (0x1400, -0x0C00),
    (0x0800, -0x0800),
    (0x0400, -0x0400),
    (-0x0400, 0x0400),
    (-0x0400, 0x0000),
    (-0x0800, 0x0000),
)

# JAInter::StreamLib::table4: nibble -> signed value.
_NIBBLE = tuple(n if n < 8 else n - 16 for n in range(16))


@dataclass(frozen=True)
class AfcHeader:
    data_size: int
    sample_count: int
    sample_rate: int
    format: int
    bit_depth: int
    unknown_0e: int
    loop_flag: int
    loop_start: int

    @property
    def channels(self) -> int:
        return 2

    @property
    def seconds(self) -> float:
        return self.sample_count / self.sample_rate if self.sample_rate else 0.0


def parse_header(data: bytes) -> AfcHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("AFC data shorter than its 0x20-byte header")
    f = struct.unpack(">IIHHHHII", data[:0x18])
    hdr = AfcHeader(*f)
    if hdr.format not in (FORMAT_PCM16, FORMAT_ADPCM):
        raise ValueError(f"unknown AFC format {hdr.format} (expected 2 or 4)")
    if not 4000 <= hdr.sample_rate <= 96000:
        raise ValueError(f"implausible AFC sample rate {hdr.sample_rate}")
    return hdr


def decode_frame(frame: bytes, hist1: int = 0, hist2: int = 0) -> tuple[list[int], int, int]:
    """Decode one 9-byte frame; returns (16 samples, new hist1, new hist2)."""
    out, h1, h2 = _decode_frames(frame, 1, hist1, hist2)
    return out, h1, h2


def _decode_frames(data: bytes, nframes: int, hist1: int, hist2: int) -> tuple[list[int], int, int]:
    out = [0] * (nframes * FRAME_SAMPLES)
    pos = 0
    o = 0
    coefs = COEFS
    nib = _NIBBLE
    for _ in range(nframes):
        head = data[pos]
        mul = 2048 << (head >> 4)
        c1, c2 = coefs[head & 0xF]
        for b in data[pos + 1 : pos + 9]:
            for n in (b >> 4, b & 0xF):
                s = (nib[n] * mul + c1 * hist1 + c2 * hist2) >> 11
                if s > 32767:
                    s = 32767
                elif s < -32768:
                    s = -32768
                out[o] = s
                o += 1
                hist2 = hist1
                hist1 = s
        pos += FRAME_BYTES
    return out, hist1, hist2


def decode(data: bytes) -> tuple[int, int, np.ndarray]:
    """Decode a whole .afc file -> (sample_rate, channels, int16 array [n, channels])."""
    hdr = parse_header(data)
    body = data[HEADER_SIZE : HEADER_SIZE + hdr.data_size]
    ch = hdr.channels
    if hdr.format == FORMAT_PCM16:
        n = len(body) // (2 * ch)
        pcm = np.frombuffer(body[: n * 2 * ch], dtype=">i2").astype(np.int16).reshape(n, ch)
        return hdr.sample_rate, ch, pcm[: hdr.sample_count]

    block = FRAME_BYTES * ch
    nblocks = len(body) // block
    # De-interleave the 9-byte frames per channel, then run each channel's
    # recursive filter in one pass.
    raw = np.frombuffer(body[: nblocks * block], dtype=np.uint8).reshape(nblocks, ch, FRAME_BYTES)
    pcm = np.empty((nblocks * FRAME_SAMPLES, ch), dtype=np.int16)
    for c in range(ch):
        samples, _, _ = _decode_frames(raw[:, c, :].tobytes(), nblocks, 0, 0)
        pcm[:, c] = samples
    return hdr.sample_rate, ch, pcm[: hdr.sample_count]


def write_wav(path, sample_rate: int, pcm: np.ndarray) -> None:
    """Write int16 PCM ([n] or [n, channels]) as a canonical RIFF WAVE file."""
    import wave

    pcm = np.asarray(pcm, dtype=np.int16)
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.astype("<i2").tobytes())
