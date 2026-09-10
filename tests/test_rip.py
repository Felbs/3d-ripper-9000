"""The rip driver (gcrip.rip)."""

from gcrip import rip

def test_source_head_reads_big_top_level_files(tmp_path, monkeypatch):
    """A top-level file's head comes off the image directly, however big the file is.

    The detect site used to hand every plugin an EMPTY head for anything over 64 MB,
    because taking 64 bytes meant materialising the whole file.  Magic-based detection
    could therefore never fire on the big archives - which is exactly where the geometry
    lives (Cubix's 285 MB allpaks.gcp, NCAA 2K3's 1.3 GB game.dat)."""

    class FakeImage:
        def __init__(self):
            self.reads = []

        def read(self, off, size):
            self.reads.append((off, size))
            return b"BOLT" + bytes(size - 4)

    class FakeEntry:
        path = "files/huge.blt"
        size = 400 << 20
        container = None
        disc_offset = 4096

    class FakeManifest:
        files = [FakeEntry()]

    img = FakeImage()
    src = rip._Source(img, FakeManifest())
    head = src.head("files/huge.blt", 64)

    assert head[:4] == b"BOLT"
    assert len(head) == 64
    # the whole 400 MB was never read
    assert img.reads == [(4096, 64)]
