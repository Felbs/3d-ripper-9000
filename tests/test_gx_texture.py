

def test_absurd_dimensions_are_refused_not_allocated():
    """A header claiming 65536x65536 asked numpy for a (8192, 8, 8192, 8, 4) array - 16 GiB -
    and the rip died with MemoryError rather than rejecting one texture
    (`TempTextures#68.tpk` on the EA discs)."""
    import pytest

    from gcrip.formats import gx_texture as gx

    for w, h in ((65536, 65536), (0, 64), (64, 0), (-8, 64), (8192, 8192)):
        with pytest.raises(ValueError):
            gx.decode(1, w, h, b"")


def test_a_real_texture_is_still_accepted():
    """The caps must never refuse anything a GameCube could draw - the hardware tops at 1024."""
    from gcrip.formats import gx_texture as gx

    for w, h in ((8, 8), (64, 64), (1024, 1024), (1024, 512)):
        out = gx.decode(1, w, h, bytes(gx.encoded_size(1, w, h)))
        assert out.shape == (h, w, 4)
