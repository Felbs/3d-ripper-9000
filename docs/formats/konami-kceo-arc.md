# Konami `KCEO ARCDT` archives (Evolution Snowboarding)

29 `.arc`, disc reported zero models and zero textures.  The file names itself in the first
sixteen bytes: `KCEO ARCDT 1.0B`.

    +0   char magic[16]   "KCEO ARCDT 1.0B\0"
    +16  u32 member count
    +20  u32 table offset  (0x800)
    +24  u32
    +28  '-' filler up to the table

    table, 36 bytes a record, all big-endian:
        char name[20]     NUL-padded: "FL_STG21_00.BPX"
        u32               0
        u32 sector        member position, in 0x800 sectors
        u32 size
        u32               0

**The members tile**, which is the check: record 0 sits at sector 2 and is 172,416 bytes, ending
inside sector 86, and record 1 starts at sector 87; record 1 is 178,176 bytes and record 2
starts where that lands.

Shipped as `gcrip/formats/kceo.py` + `gcrip/plugins/kceo.py`: **all 29 archives expand, 2,323
members** under their real names.

## What is inside

| extension | n | magic |
|---|---|---|
| `.SUR` | 1,250 | `CUBE` |
| `.BPX` | 940 | `BPXB` |
| `.BIN` | 131 | mixed |

`CUBE` and `BPXB` are Konami's own GameCube formats and are the next step for this disc - the
archive split hands them to the pipeline named, which is what the structure scanner needs.
