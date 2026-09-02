

def test_hand_assembled_stream():
    """Carried over from the deleted Dreamcast suite when its duplicate PRS decoder was
    removed.  The two implementations were byte-identical on 40 random inputs and on this
    hand-built stream, so only one is kept - but the coverage should not vanish with it.

    Flags are consumed LSB first: 1,1 = two literals; 0,0 then 0,1 = a short copy of length 3;
    0,1 = a long copy; a fresh flag byte 0,1 with a zero pair terminates.
    """
    import pytest

    from gcrip.formats import prs

    flags = 0b10100011
    v = ((-5 + 0x2000) << 3) | 2  # long copy: offset -5, length 2 + 2
    stream = bytes([flags, ord("a"), ord("b"), 0xFE, v & 0xFF, v >> 8, 0b10, 0, 0])
    assert prs.decompress(stream) == b"ab" + b"aba" + b"abab"
    with pytest.raises(ValueError):
        prs.decompress(bytes([0b00, 0x00]))  # a copy before any output exists
