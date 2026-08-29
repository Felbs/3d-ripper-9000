"""Read a file straight from the disk, bypassing the OS page cache (Windows
FILE_FLAG_NO_BUFFERING). A verification read that comes back from RAM proves nothing about
the platter; this makes `gcrip verify` / `gcrip dump --verify` a real second read.

On non-Windows platforms (or if the flag is refused) it falls back to normal buffered reads.
"""

from __future__ import annotations

import ctypes
import mmap
import os
import sys
from collections.abc import Iterator
from pathlib import Path

SECTOR = 4096
CHUNK = 8 << 20


def _win_chunks(path: Path, chunk: int) -> Iterator[bytes]:
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x1
    OPEN_EXISTING = 3
    FILE_FLAG_NO_BUFFERING = 0x20000000
    FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    INVALID = ctypes.c_void_p(-1).value
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    h = k32.CreateFileW(
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_FLAG_NO_BUFFERING | FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    if h == INVALID or h is None:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    size = path.stat().st_size
    buf = mmap.mmap(-1, chunk)  # page-aligned, as NO_BUFFERING requires
    addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
    try:
        done = 0
        while done < size:
            want = min(chunk, ((size - done) + SECTOR - 1) // SECTOR * SECTOR)
            got = wintypes.DWORD(0)
            if not k32.ReadFile(h, addr, want, ctypes.byref(got), None):
                raise OSError(ctypes.get_last_error(), "ReadFile failed")
            n = min(got.value, size - done)
            if n == 0:
                break
            yield buf[:n]
            done += n
    finally:
        k32.CloseHandle(h)
        buf.close()


def read_chunks(path: str | os.PathLike, chunk: int = CHUNK) -> Iterator[bytes]:
    """Yield the file's bytes in order, from the disk if the platform lets us insist."""
    path = Path(path)
    if sys.platform == "win32":
        try:
            yield from _win_chunks(path, chunk)
            return
        except OSError:
            pass
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                return
            yield data
