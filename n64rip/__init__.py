"""n64rip - Nintendo 64 model extraction, sharing gcrip's scene model and glTF exporter.

Built for the Zelda ROMs that ship inside the GameCube Collector's Edition and Ocarina of
Time: Master Quest discs, which are N64 games run under an emulator rather than GameCube
titles.  The disc side of gcrip does not apply (a ROM is one file, not a filesystem), but
everything downstream of ``ripcore.scene.Scene`` does - the glTF exporter with joints,
skinning and clips, the library browser, the Blender add-on and the mocap retarget.

Layout mirrors gcrip: ``rom`` walks the container, ``formats`` decode, and the result is a
``Scene`` the shared exporter writes.
"""

from n64rip.rom import Rom, RomFile

__all__ = ["Rom", "RomFile"]
