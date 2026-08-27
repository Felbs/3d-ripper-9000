"""GD-ROM images in GDI form (Redump-style), as a .gdi + track files on disk or inside a .zip.

A GDI is a text table:

    3
    1      0 4 2352 "game (Track 1).bin" 0
    2    606 0 2352 "game (Track 2).bin" 0
    3  45000 4 2352 "game (Track 3).bin" 0

columns: track number, start LBA, type (4 = data, 0 = audio), sector size, file, offset.
Tracks 1-2 are the low-density CD area; the game lives in the high-density area from LBA
45000, usually one data track (3), sometimes two (3 and the last one, e.g. Shenmue's 6).
Data sectors are raw Mode 1 (2352 bytes: 12 sync + 4 header + 2048 data + 288 EDC/ECC) or
plain 2048. The filesystem is ISO 9660 whose LBAs are absolute (PVD at 45000 + 16).

Sector 0 of the first high-density data track is IP.BIN ("SEGA SEGAKATANA"), the boot
header with product number, version, date, company and title.

Zips are inflated into memory per data track (a GD-ROM data track is <= 1.2 GB; deflate
streams cannot be seeked, and random access is what the ISO walk needs).
"""

from __future__ import annotations

import io
import os
import re
import shlex
import zipfile
from dataclasses import dataclass
from pathlib import Path

HD_AREA_LBA = 45000


class UnsupportedImageError(Exception):
    pass


@dataclass
class Track:
    number: int
    lba: int
    kind: int  # 4 = data, 0 = audio
    sector_size: int
    filename: str
    offset: int = 0
    size: int = 0  # bytes

    @property
    def sectors(self) -> int:
        return self.size // self.sector_size if self.sector_size else 0

    @property
    def is_data(self) -> bool:
        return self.kind == 4


@dataclass
class IpBin:
    hardware: str
    maker: str
    device: str
    area: str
    peripherals: str
    product: str
    version: str
    date: str
    boot: str
    company: str
    title: str

    @property
    def region(self) -> str:
        codes = {"J": "JPN", "U": "USA", "E": "EUR"}
        return "/".join(codes.get(c, c) for c in self.area if c.strip()) or "?"


def parse_ip_bin(data: bytes) -> IpBin:
    def s(a: int, b: int) -> str:
        return data[a:b].decode("ascii", "replace").strip()

    if data[:16] != b"SEGA SEGAKATANA ":
        raise UnsupportedImageError("no IP.BIN (SEGA SEGAKATANA) at the start of the data track")
    return IpBin(
        hardware=s(0x00, 0x10),
        maker=s(0x10, 0x20),
        device=s(0x20, 0x30),
        area=s(0x30, 0x38),
        peripherals=s(0x38, 0x40),
        product=s(0x40, 0x4A),
        version=s(0x4A, 0x50),
        date=s(0x50, 0x60),
        boot=s(0x60, 0x70),
        company=s(0x70, 0x80),
        title=s(0x80, 0x100),
    )


def parse_gdi(text: str) -> list[Track]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise UnsupportedImageError("empty .gdi")
    tracks = []
    for ln in lines[1:]:
        parts = shlex.split(ln)
        if len(parts) < 5:
            continue
        tracks.append(
            Track(
                number=int(parts[0]),
                lba=int(parts[1]),
                kind=int(parts[2]),
                sector_size=int(parts[3]),
                filename=parts[4],
                offset=int(parts[5]) if len(parts) > 5 else 0,
            )
        )
    if not tracks:
        raise UnsupportedImageError("no tracks in .gdi")
    return tracks


class _TrackData:
    """Bytes of one track: in memory (zip) or a file handle (on disk)."""

    def __init__(self, blob: bytes | None = None, fh: io.BufferedReader | None = None):
        self._blob = blob
        self._fh = fh
        if blob is not None:
            self.size = len(blob)
        else:
            assert fh is not None
            self.size = fh.seek(0, os.SEEK_END)

    def read(self, off: int, n: int) -> bytes:
        if self._blob is not None:
            return self._blob[off : off + n]
        assert self._fh is not None
        self._fh.seek(off)
        return self._fh.read(n)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._blob = None


class GdImage:
    """Sector-level access to a GD-ROM's data tracks."""

    def __init__(self, path: str | os.PathLike, *, load_low_density: bool = False):
        self.path = Path(path)
        self._zip: zipfile.ZipFile | None = None
        self._data: dict[int, _TrackData] = {}
        self.tracks: list[Track] = []
        self.errors: list[str] = []
        if self.path.suffix.lower() == ".zip":
            self._open_zip(load_low_density)
        elif self.path.suffix.lower() == ".gdi":
            self._open_gdi(load_low_density)
        else:
            raise UnsupportedImageError(f"{self.path.name}: expected a .gdi or a .zip holding one")
        self.data_tracks = sorted(
            (t for t in self.tracks if t.is_data and t.number in self._data), key=lambda t: t.lba
        )
        if not self.data_tracks:
            raise UnsupportedImageError(f"{self.path.name}: no data track loaded")
        hd = [t for t in self.data_tracks if t.lba >= HD_AREA_LBA]
        self.first_data = hd[0] if hd else self.data_tracks[0]
        self.header = parse_ip_bin(self.read_sector(self.first_data.lba))

    # -- opening ------------------------------------------------------------------

    def _open_zip(self, load_low_density: bool) -> None:
        self._zip = zipfile.ZipFile(self.path)
        names = self._zip.namelist()
        gdis = [n for n in names if n.lower().endswith(".gdi")]
        if not gdis:
            raise UnsupportedImageError(f"{self.path.name}: zip has no .gdi")
        self.tracks = parse_gdi(self._zip.read(gdis[0]).decode("utf-8", "replace"))
        by_name = {os.path.basename(n): n for n in names}
        for t in self.tracks:
            if not t.is_data or (t.lba < HD_AREA_LBA and not load_low_density):
                continue
            member = by_name.get(t.filename) or by_name.get(os.path.basename(t.filename))
            if member is None:
                self.errors.append(f"track {t.number}: {t.filename} missing from zip")
                continue
            blob = self._zip.read(member)
            t.size = len(blob)
            self._data[t.number] = _TrackData(blob=blob)

    def _open_gdi(self, load_low_density: bool) -> None:
        self.tracks = parse_gdi(self.path.read_text(encoding="utf-8", errors="replace"))
        for t in self.tracks:
            if not t.is_data or (t.lba < HD_AREA_LBA and not load_low_density):
                continue
            f = self.path.parent / t.filename
            if not f.exists():
                self.errors.append(f"track {t.number}: {f.name} missing")
                continue
            fh = open(f, "rb")  # noqa: SIM115 - long-lived handle
            td = _TrackData(fh=fh)
            t.size = td.size
            self._data[t.number] = td

    def close(self) -> None:
        for td in self._data.values():
            td.close()
        self._data.clear()
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> GdImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- sectors ------------------------------------------------------------------

    def track_for(self, lba: int) -> Track | None:
        best = None
        for t in self.data_tracks:
            if t.lba <= lba < t.lba + t.sectors:
                best = t
        return best

    def read_sector(self, lba: int) -> bytes:
        t = self.track_for(lba)
        if t is None:
            raise ValueError(f"LBA {lba} is not inside a loaded data track")
        off = (lba - t.lba) * t.sector_size + t.offset
        if t.sector_size == 2352:
            off += 16
        return self._data[t.number].read(off, 2048)

    def read(self, lba: int, size: int) -> bytes:
        """`size` bytes starting at the beginning of sector `lba`."""
        out = bytearray()
        n = (size + 2047) // 2048
        t = self.track_for(lba)
        if t is not None and t.sector_size == 2048 and lba + n <= t.lba + t.sectors:
            return self._data[t.number].read((lba - t.lba) * 2048 + t.offset, size)
        for i in range(n):
            out += self.read_sector(lba + i)
        return bytes(out[:size])

    @property
    def size(self) -> int:
        return sum(t.size for t in self.tracks)


_TITLE_JUNK = re.compile(r"\s+")


def clean_title(t: str) -> str:
    return _TITLE_JUNK.sub(" ", t).strip()
