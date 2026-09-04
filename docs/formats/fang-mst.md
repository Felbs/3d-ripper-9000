# Midway Fang `.mst` (Freaky Flyers)

Container read 2026-09-04 (`gcrip/formats/fang_mst.py`, `gcrip/plugins/fang_mst.py`, `tests/test_fang_mst.py`).

Freaky Flyers (two discs) is Midway San Diego's **Fang** engine (`pFang Game`, `CGfPlayerDef`,
`fgcoll_DoCollObjectSkinningFixup` in the DOL, which is otherwise stripped).  Each of the 34
`*_gc.mst` (5-146 MB) is an archive with a little-endian header:

    "FANG"  u8[4] version 0.7.1.24  u32 file size  u32 entries  u32 x4  u32 6, 6, 6
    0x6c:   48-byte entries  char[32] name, u32 offset, u32 packed, u32 timestamp, u32 unpacked + 32

Every member is one **LZO1X** stream - the first byte is the 17+ literal-run opcode, the
literals start with the object's class name - decoded by `gcrip.formats.lzo`; the table's
unpacked count is 32 bytes more than the stream produces, on 649 of 649 members.  The
members' contents are big-endian:

| ext | count in `OHTD_gc.mst` | what |
|---|---|---|
| `.gcp` | 303 | particle definitions (`xPSG`) |
| `.gtx` | 168 | **textures** - 0x59-byte header: `u32 header size` at +0x18, `u32 mips` at +0x1c, `u16 width, height` at +0x20, GX format at +0x2c; tiled pixels follow.  RGB5A3, CMPR, 128-512 px - decoded by the plugin |
| `.gob` | 82 | game objects (`CGfPlayerDef`, `CGfProjectileDef` ...) |
| `.gmo` | 70 | **models**: 24-byte name, `f32` radius, centre, bounds, then a memory image with absolute pointers (`0x0b1e....`) and **plain GX display lists** - `gxscan` reads 25 lists / 2,669 triangles from `mgs_camera.gmo` |
| `.gmw` / `.gcw` | 1 each | the level's mesh world / collision world - 71 lists / 18,823 triangles from `ohtd.gmw` |
| `.gst`, `.dta`, `.gfu`, `.db` | few | strings, data, fonts |

So the geometry comes through the fallback scanner today, untextured and per list; a `.gmo`
reader that resolves the pointer image would name the meshes and bind the `.gtx`.  Left for a
DOL session (the pointer base and the relocation table are what to find).
