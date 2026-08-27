"""dcrip: GDI/zip images, ISO 9660 walk, PRS and AFS - on synthetic data only."""

from __future__ import annotations

import struct
import zipfile

import pytest

from dcrip.disc.gdi import HD_AREA_LBA, GdImage, UnsupportedImageError, parse_gdi
from dcrip.disc.iso9660 import walk
from dcrip.formats import afs, prs

SECTOR = 2048


def _rec(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    body = struct.pack("<I", lba) + struct.pack(">I", lba)
    body += struct.pack("<I", size) + struct.pack(">I", size)
    body += bytes(7) + bytes([2 if is_dir else 0, 0, 0])
    body += struct.pack("<H", 1) + struct.pack(">H", 1)
    body += bytes([len(name)]) + name
    if len(name) % 2 == 0:
        body += b"\x00"
    length = 1 + 1 + len(body)
    return bytes([length, 0]) + body


def build_iso(files: dict[str, bytes], *, base_lba: int = HD_AREA_LBA) -> bytes:
    """A minimal ISO 9660 volume as 2048-byte sectors: IP.BIN at 0, PVD at 16, root dir at
    17 (one directory level 'DIR' at 18 for paths containing '/'), file data from 32."""
    top: dict[str, bytes] = {}
    sub: dict[str, bytes] = {}
    for path, data in files.items():
        (sub if "/" in path else top)[path.split("/")[-1]] = data
    sectors: dict[int, bytes] = {}
    ip = bytearray(SECTOR)
    ip[0:0x100] = (
        b"SEGA SEGAKATANA SEGA ENTERPRISES1234 GD-ROM1/1   U      0799A10 T-0001N   V1.000"
        b"20000101        1ST_READ.BIN    TEST COMPANY    TEST GAME"
    ).ljust(0x100)
    sectors[0] = bytes(ip)
    lba = 32
    placed: dict[str, tuple[int, int]] = {}
    for name, data in list(top.items()) + list(sub.items()):
        placed[name] = (base_lba + lba, len(data))
        for i in range(0, max(len(data), 1), SECTOR):
            sectors[lba] = data[i : i + SECTOR].ljust(SECTOR, b"\x00")
            lba += 1
    root_lba, dir_lba = base_lba + 17, base_lba + 18
    root = _rec(b"\x00", root_lba, SECTOR, True) + _rec(b"\x01", root_lba, SECTOR, True)
    for name in top:
        root += _rec(name.encode() + b";1", *placed[name], False)
    if sub:
        root += _rec(b"DIR", dir_lba, SECTOR, True)
    sectors[17] = root.ljust(SECTOR, b"\x00")
    d = _rec(b"\x00", dir_lba, SECTOR, True) + _rec(b"\x01", root_lba, SECTOR, True)
    for name in sub:
        d += _rec(name.encode() + b";1", *placed[name], False)
    sectors[18] = d.ljust(SECTOR, b"\x00")
    pvd = bytearray(SECTOR)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = b"TESTVOL".ljust(32)
    pvd[156:190] = _rec(b"\x00", root_lba, SECTOR, True).ljust(34, b"\x00")
    sectors[16] = bytes(pvd)
    n = max(sectors) + 1
    return b"".join(sectors.get(i, bytes(SECTOR)) for i in range(n))


def raw2352(data2048: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data2048), SECTOR):
        out += b"\x00" + b"\xff" * 10 + b"\x00" + b"\x00\x02\x00\x01"
        out += data2048[i : i + SECTOR] + bytes(288)
    return bytes(out)


FILES = {
    "1ST_READ.BIN": b"boot" * 700,
    "MODEL.NJ": b"NJCM" + bytes(60),
    "DIR/T.PVR": b"GBIX" + bytes(12),
}


@pytest.fixture
def gdi_dir(tmp_path):
    track3 = raw2352(build_iso(FILES))
    (tmp_path / "game (Track 3).bin").write_bytes(track3)
    (tmp_path / "game (Track 1).bin").write_bytes(raw2352(bytes(SECTOR * 2)))
    (tmp_path / "game (Track 2).bin").write_bytes(bytes(2352 * 2))
    gdi = (
        '3\n1 0 4 2352 "game (Track 1).bin" 0\n2 300 0 2352 "game (Track 2).bin" 0\n'
        '3 45000 4 2352 "game (Track 3).bin" 0\n'
    )
    (tmp_path / "game.gdi").write_text(gdi)
    return tmp_path


def test_parse_gdi():
    tracks = parse_gdi('2\n1 0 4 2352 "a b.bin" 0\n3 45000 4 2048 "c.bin" 0\n')
    assert [t.number for t in tracks] == [1, 3]
    assert tracks[0].filename == "a b.bin" and tracks[0].is_data
    assert tracks[1].sector_size == 2048
    with pytest.raises(UnsupportedImageError):
        parse_gdi("")


def test_walk_gdi_on_disk(gdi_dir):
    with GdImage(gdi_dir / "game.gdi") as img:
        assert img.header.title == "TEST GAME" and img.header.product == "T-0001N"
        assert img.header.region == "USA"
        assert [t.number for t in img.data_tracks] == [3]  # low-density track not loaded
        vol = walk(img)
        assert vol.label == "TESTVOL"
        paths = {e.path: e for e in vol.entries}
        assert set(paths) == {"1ST_READ.BIN", "MODEL.NJ", "DIR", "DIR/T.PVR"}
        assert paths["DIR"].is_dir
        assert img.read(paths["MODEL.NJ"].lba, 4) == b"NJCM"
        e = paths["1ST_READ.BIN"]
        assert img.read(e.lba, e.size) == FILES["1ST_READ.BIN"]  # spans two sectors


def test_walk_zip(gdi_dir, tmp_path):
    z = tmp_path / "game.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in gdi_dir.iterdir():
            if f.suffix in (".gdi", ".bin"):
                zf.write(f, f.name)
    with GdImage(z) as img:
        vol = walk(img)
        assert {e.name for e in vol.files} == {"1ST_READ.BIN", "MODEL.NJ", "T.PVR"}


def test_prs_decompress_hand_assembled():
    # flag bits are consumed LSB first: 1,1 = two literals; 0,0 then 0,1 = short copy of
    # length 3; 0,1 = long copy; a fresh flag byte 0,1 with a zero pair terminates.
    flags = 0b10100011
    v = ((-5 + 0x2000) << 3) | 2  # long copy: offset -5, length 2 + 2
    stream = bytes([flags, ord("a"), ord("b"), 0xFE, v & 0xFF, v >> 8, 0b10, 0, 0])
    assert prs.decompress(stream) == b"ab" + b"aba" + b"abab"
    with pytest.raises(ValueError):
        prs.decompress(bytes([0b00, 0x00]))  # copy before any output


def test_afs_parse():
    entries = [b"NJCM" + bytes(28), b"NMDM" + bytes(12)]
    header = b"AFS\x00" + struct.pack("<I", 2)
    off = 0x800
    table = b""
    blobs = b""
    for e in entries:
        table += struct.pack("<II", off + len(blobs), len(e))
        blobs += e.ljust(32, b"\x00")
    data = (header + table).ljust(off, b"\x00") + blobs
    parsed = afs.parse(data)
    assert [(e.offset, e.size) for e in parsed] == [(0x800, 32), (0x820, 16)]
    assert data[parsed[1].offset : parsed[1].offset + 4] == b"NMDM"
