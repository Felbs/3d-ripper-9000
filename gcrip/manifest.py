"""Build the disc manifest: every file on the disc (and inside archives), with
path, offset, size, content hash, and classification.

Path conventions (mirroring Dolphin's own extraction layout):
  sys/boot.bin, sys/bi2.bin, sys/apploader.img, sys/main.dol, sys/fst.bin
  files/<FST path>
  files/<FST path to archive>/<archive root name>/<inner path>   for nested files

For nested files, `offset` is relative to the decompressed container and
`disc_offset` is only set when the whole chain is uncompressed (so the bytes
literally exist at that disc offset). That is what phase 2's DVD-read tracking
needs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from gcrip import __version__
from gcrip.classify import SNIFF_BYTES, Classification, classify
from gcrip.disc import tgc
from gcrip.disc.fst import (
    APPLOADER_OFFSET,
    BI2_OFFSET,
    BI2_SIZE,
    HEADER_SIZE,
    DiscHeader,
    FstEntry,
    apploader_size,
    dol_size,
    parse_fst,
    parse_header,
)
from gcrip.disc.image import DiscImage
from gcrip.formats import rarc, yay0, yaz0

MAX_NESTING = 8
STREAM_THRESHOLD = 32 << 20  # read files bigger than this in chunks unless we must decompress


@dataclass
class ManifestEntry:
    path: str
    size: int
    kind: str
    fmt: str
    classified_by: str
    sha1: str | None = None
    disc_offset: int | None = None
    container: str | None = None
    offset: int | None = None  # offset within container (or == disc_offset at top level)
    compression: str | None = None  # "Yaz0" / "Yay0" if the bytes at `offset` are compressed
    decompressed_size: int | None = None
    sha1_decompressed: str | None = None
    depth: int = 0  # nesting depth (0 = directly on disc)


@dataclass
class Manifest:
    game: dict[str, Any]
    image: dict[str, Any]
    files: list[ManifestEntry] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        stats: dict[str, dict[str, int]] = {"by_kind": {}, "by_fmt": {}}
        for f in self.files:
            stats["by_kind"][f.kind] = stats["by_kind"].get(f.kind, 0) + 1
            key = f.fmt or "?"
            stats["by_fmt"][key] = stats["by_fmt"].get(key, 0) + 1
        return {
            "gcrip_version": __version__,
            "game": self.game,
            "image": self.image,
            "stats": {
                "file_count": len(self.files),
                "top_level_file_count": sum(1 for f in self.files if f.depth == 0),
                **stats,
            },
            "dirs": self.dirs,
            "files": [{k: v for k, v in asdict(f).items() if v is not None} for f in self.files],
            "errors": self.errors,
        }


ProgressFn = Callable[[str, int, int], None]


class ManifestBuilder:
    def __init__(
        self,
        image: DiscImage,
        *,
        recurse: bool = True,
        hash_files: bool = True,
        progress: ProgressFn | None = None,
    ):
        self.image = image
        self.recurse = recurse
        self.hash_files = hash_files
        self.progress = progress
        head = image.read(0, APPLOADER_OFFSET + 0x20)
        self.header: DiscHeader = parse_header(head)
        fst_raw = image.read(self.header.fst_offset, self.header.fst_size)
        self.fst: list[FstEntry] = parse_fst(fst_raw)
        self._fst_raw = fst_raw
        self.manifest = Manifest(
            game={
                "id": self.header.game_id,
                "title": self.header.title,
                "maker": self.header.maker_code,
                "region": self.header.region,
                "disc_number": self.header.disc_number,
                "revision": self.header.revision,
                "apploader_date": self.header.apploader_date,
            },
            image={"filename": image.path.name, "size": image.size},
        )

    # -- helpers -----------------------------------------------------------

    def _sha1_range(self, offset: int, size: int) -> str:
        h = hashlib.sha1()
        for chunk in self.image.read_chunks(offset, size):
            h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _sha1(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()

    def _report(self, path: str, i: int, n: int) -> None:
        if self.progress:
            self.progress(path, i, n)

    # -- system files -----------------------------------------------------

    def _add_system_files(self) -> None:
        img = self.image
        hdr = self.header
        sys_files: list[tuple[str, int, int, Classification]] = [
            ("sys/boot.bin", 0, HEADER_SIZE, Classification("system", "BOOT", "fixed")),
            ("sys/bi2.bin", BI2_OFFSET, BI2_SIZE, Classification("system", "BI2", "fixed")),
        ]
        try:
            apl_size = apploader_size(img.read(APPLOADER_OFFSET, 0x20))
            sys_files.append(
                (
                    "sys/apploader.img",
                    APPLOADER_OFFSET,
                    apl_size,
                    Classification("system", "APPLOADER", "fixed"),
                )
            )
        except Exception as e:  # noqa: BLE001
            self.manifest.errors.append(f"apploader: {e}")
        if hdr.dol_offset:
            try:
                dsize = dol_size(img.read(hdr.dol_offset, 0x100))
                sys_files.append(
                    (
                        "sys/main.dol",
                        hdr.dol_offset,
                        dsize,
                        Classification("executable", "DOL", "fixed"),
                    )
                )
            except Exception as e:  # noqa: BLE001
                self.manifest.errors.append(f"main.dol: {e}")
        sys_files.append(
            (
                "sys/fst.bin",
                hdr.fst_offset,
                hdr.fst_size,
                Classification("system", "FST", "fixed"),
            )
        )
        self.manifest.dirs.append("sys")
        for path, off, size, cls in sys_files:
            self.manifest.files.append(
                ManifestEntry(
                    path=path,
                    size=size,
                    kind=cls.kind,
                    fmt=cls.fmt,
                    classified_by=cls.by,
                    sha1=self._sha1_range(off, size) if self.hash_files else None,
                    disc_offset=off,
                    offset=off,
                )
            )

    # -- content walking ---------------------------------------------------

    def _walk_blob(
        self,
        path: str,
        name: str,
        data: bytes,
        *,
        disc_offset: int | None,
        container: str | None,
        offset: int,
        depth: int,
    ) -> None:
        """Classify `data`, add an entry, and recurse into it if it is a
        compressed blob or an archive."""
        cls = classify(name, data[:SNIFF_BYTES], len(data))
        entry = ManifestEntry(
            path=path,
            size=len(data),
            kind=cls.kind,
            fmt=cls.fmt,
            classified_by=cls.by,
            sha1=self._sha1(data) if self.hash_files else None,
            disc_offset=disc_offset,
            container=container,
            offset=offset,
            depth=depth,
        )
        self.manifest.files.append(entry)

        payload = data
        payload_disc_offset = disc_offset
        if cls.kind == "compressed" and cls.fmt in ("Yaz0", "Yay0"):
            try:
                payload = yaz0.decompress(data) if cls.fmt == "Yaz0" else yay0.decompress(data)
            except Exception as e:  # noqa: BLE001
                self.manifest.errors.append(f"{path}: {cls.fmt} decompress failed: {e}")
                return
            entry.compression = cls.fmt
            entry.decompressed_size = len(payload)
            entry.sha1_decompressed = self._sha1(payload) if self.hash_files else None
            payload_disc_offset = None
            inner = classify(name, payload[:SNIFF_BYTES], len(payload))
            # The entry describes the payload; `compression` says how it's stored.
            entry.kind, entry.fmt, entry.classified_by = inner.kind, inner.fmt, inner.by
            if inner.kind == "unknown":
                entry.kind = "compressed"
                entry.fmt = cls.fmt

        if not self.recurse or depth >= MAX_NESTING:
            return
        if rarc.is_rarc(payload):
            self._walk_rarc(path, payload, disc_offset=payload_disc_offset, depth=depth + 1)
        elif tgc.is_tgc(payload):
            self._walk_tgc(path, payload, disc_offset=payload_disc_offset, depth=depth + 1)

    def _walk_tgc(self, path: str, data: bytes, *, disc_offset: int | None, depth: int) -> None:
        """An embedded mini-disc: its files become nested entries under <path>/files/...
        (the same layout as the outer disc), its boot.bin/main.dol under <path>/sys/."""
        try:
            t = tgc.parse(data)
        except Exception as e:  # noqa: BLE001
            self.manifest.errors.append(f"{path}: TGC parse failed: {e}")
            return
        self.manifest.dirs.append(f"{path}/sys")
        self.manifest.dirs.append(f"{path}/files")
        for d in t.dirs:
            self.manifest.dirs.append(f"{path}/files/{d}")
        sys_files = [
            ("sys/boot.bin", t.header_size, HEADER_SIZE, Classification("system", "BOOT", "fixed")),
            ("sys/fst.bin", t.fst_offset, t.fst_size, Classification("system", "FST", "fixed")),
        ]
        if t.dol_offset and t.dol_size:
            dol_cls = Classification("executable", "DOL", "fixed")
            sys_files.append(("sys/main.dol", t.dol_offset, t.dol_size, dol_cls))
        for sub, off, size, cls in sys_files:
            if off + size > len(data):
                continue
            self.manifest.files.append(
                ManifestEntry(
                    path=f"{path}/{sub}",
                    size=size,
                    kind=cls.kind,
                    fmt=cls.fmt,
                    classified_by=cls.by,
                    sha1=self._sha1(data[off : off + size]) if self.hash_files else None,
                    disc_offset=(disc_offset + off) if disc_offset is not None else None,
                    container=path,
                    offset=off,
                    depth=depth,
                )
            )
        for f in t.files:
            self._walk_blob(
                f"{path}/files/{f.path}",
                f.name,
                data[f.offset : f.offset + f.size],
                disc_offset=(disc_offset + f.offset) if disc_offset is not None else None,
                container=path,
                offset=f.offset,
                depth=depth,
            )

    def _walk_rarc(self, path: str, data: bytes, *, disc_offset: int | None, depth: int) -> None:
        try:
            arc = rarc.parse(data)
        except Exception as e:  # noqa: BLE001
            self.manifest.errors.append(f"{path}: RARC parse failed: {e}")
            return
        for d in arc.dirs:
            self.manifest.dirs.append(f"{path}/{d.path}")
        for f in arc.files:
            if f.offset + f.size > len(data):
                self.manifest.errors.append(f"{path}/{f.path}: entry extends past archive end")
                continue
            self._walk_blob(
                f"{path}/{f.path}",
                f.name,
                data[f.offset : f.offset + f.size],
                disc_offset=(disc_offset + f.offset) if disc_offset is not None else None,
                container=path,
                offset=f.offset,
                depth=depth,
            )

    # -- top level ---------------------------------------------------------

    def build(self) -> Manifest:
        self._add_system_files()
        self.manifest.dirs.append("files")
        files = [e for e in self.fst if not e.is_dir]
        for e in self.fst:
            if e.is_dir:
                self.manifest.dirs.append(f"files/{e.path}")
        n = len(files)
        for i, e in enumerate(files):
            path = f"files/{e.path}"
            self._report(path, i, n)
            if e.offset + e.size > self.image.size:
                self.manifest.errors.append(f"{path}: extends past end of image (truncated dump?)")
            head = self.image.read(e.offset, min(SNIFF_BYTES, e.size))
            cls = classify(e.name, head, e.size)
            needs_whole = self.recurse and cls.kind in ("compressed", "archive")
            if needs_whole or e.size <= STREAM_THRESHOLD:
                data = self.image.read(e.offset, e.size)
                self._walk_blob(
                    path,
                    e.name,
                    data,
                    disc_offset=e.offset,
                    container=None,
                    offset=e.offset,
                    depth=0,
                )
            else:
                self.manifest.files.append(
                    ManifestEntry(
                        path=path,
                        size=e.size,
                        kind=cls.kind,
                        fmt=cls.fmt,
                        classified_by=cls.by,
                        sha1=self._sha1_range(e.offset, e.size) if self.hash_files else None,
                        disc_offset=e.offset,
                        offset=e.offset,
                    )
                )
        return self.manifest


def build_manifest(
    image: DiscImage,
    *,
    recurse: bool = True,
    hash_files: bool = True,
    progress: ProgressFn | None = None,
) -> Manifest:
    return ManifestBuilder(image, recurse=recurse, hash_files=hash_files, progress=progress).build()
