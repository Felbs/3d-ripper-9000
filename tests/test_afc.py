import struct
import wave

import numpy as np
import pytest

from gcrip.formats import afc


def _header(data_size, samples, rate=32000, fmt=4, loop=0, loop_start=0):
    return struct.pack(">IIHHHHIIII", data_size, samples, rate, fmt, 16, 30, loop, loop_start, 0, 0)


def _encode_frame(shift, coef_index, nibbles):
    assert len(nibbles) == 16
    head = (shift << 4) | coef_index
    body = bytes(((nibbles[i] & 0xF) << 4) | (nibbles[i + 1] & 0xF) for i in range(0, 16, 2))
    return bytes([head]) + body


def test_header_layout():
    hdr = afc.parse_header(_header(18, 16, rate=44100, loop=1, loop_start=8) + b"\0" * 18)
    assert (hdr.data_size, hdr.sample_count, hdr.sample_rate) == (18, 16, 44100)
    assert hdr.format == afc.FORMAT_ADPCM
    assert hdr.bit_depth == 16 and hdr.unknown_0e == 30
    assert (hdr.loop_flag, hdr.loop_start) == (1, 8)
    assert hdr.channels == 2
    assert hdr.seconds == pytest.approx(16 / 44100)


def test_header_rejects_garbage():
    with pytest.raises(ValueError):
        afc.parse_header(_header(0, 0, fmt=7) + b"\0" * 8)
    with pytest.raises(ValueError):
        afc.parse_header(b"\0" * 8)


def test_frame_coef0_is_plain_scaled_nibbles():
    # coef index 0 -> (0, 0): output is just nibble << shift, no prediction.
    nibs = [0, 1, 2, 3, 4, 5, 6, 7, -8, -7, -6, -5, -4, -3, -2, -1]
    out, h1, h2 = afc.decode_frame(_encode_frame(5, 0, nibs))
    assert out == [n << 5 for n in nibs]
    assert (h1, h2) == (-1 << 5, -2 << 5)


def test_frame_prediction_and_history():
    # coef index 1 -> c1 = 2048 (exactly 1.0): s[n] = nib + s[n-1].
    nibs = [1] * 16
    out, h1, h2 = afc.decode_frame(_encode_frame(0, 1, nibs), hist1=100, hist2=0)
    assert out == list(range(101, 117))
    # coef index 2 -> c2 = 2048: s[n] = nib + s[n-2].
    out, _, _ = afc.decode_frame(_encode_frame(0, 2, [0] * 16), hist1=7, hist2=3)
    assert out == [3, 7] * 8
    # hand-check one step of the fractional predictor, index 4 = (4096, -2048):
    # s = ((nib << shift) * 2048 + 2*2048*h1 - 2048*h2) >> 11 = nib<<shift + 2*h1 - h2
    out, _, _ = afc.decode_frame(_encode_frame(3, 4, [1] + [0] * 15), hist1=10, hist2=4)
    assert out[0] == (1 << 3) + 2 * 10 - 4
    assert out[1] == 2 * out[0] - 10


def test_frame_clamps():
    out, _, _ = afc.decode_frame(_encode_frame(15, 0, [7] * 8 + [-8] * 8))
    assert out[0] == 32767 and out[-1] == -32768


def test_decode_stereo_interleave_and_wav(tmp_path):
    left = _encode_frame(4, 0, list(range(0, 8)) + [-8 + i for i in range(8)])
    right = _encode_frame(1, 0, [1] * 16)
    left2 = _encode_frame(0, 1, [1] * 16)  # continues left history (last sample -16)
    right2 = _encode_frame(0, 0, [0] * 16)
    body = left + right + left2 + right2
    data = _header(len(body), 30) + body  # sample_count trims the padded tail
    rate, ch, pcm = afc.decode(data)
    assert (rate, ch, pcm.shape, pcm.dtype) == (32000, 2, (30, 2), np.int16)
    assert pcm[:8, 0].tolist() == [i << 4 for i in range(8)]
    assert pcm[8:16, 0].tolist() == [(-8 + i) << 4 for i in range(8)]
    assert pcm[16:30, 0].tolist() == [-16 + 1 + i for i in range(14)]
    assert pcm[:16, 1].tolist() == [2] * 16
    assert pcm[16:, 1].tolist() == [0] * 14

    out = tmp_path / "x.wav"
    afc.write_wav(out, rate, pcm)
    with wave.open(str(out)) as w:
        params = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        assert params == (2, 2, 32000, 30)
        back = np.frombuffer(w.readframes(30), dtype="<i2").reshape(30, 2)
    assert np.array_equal(back, pcm)


def test_decode_pcm16_format():
    pcm = np.arange(-6, 6, dtype=np.int16).reshape(6, 2)
    data = _header(24, 5, fmt=2) + pcm.astype(">i2").tobytes()
    rate, ch, out = afc.decode(data)
    assert out.shape == (5, 2) and out.tolist() == pcm[:5].tolist()
