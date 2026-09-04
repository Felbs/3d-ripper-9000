# Crystal Dynamics `bigfile.dat` - Tomb Raider: Legend

The whole game in one file, **1,353,598,976 bytes** beside only `bi2.bin` and `fst.bin`, and
the biggest single unclaimed file in the library.  `gcrip/formats/cd_bigfile.py` +
`gcrip/plugins/cd_bigfile.py`.  Big-endian:

    +0              u32 count                     4,314
    +4              u32 hash[count]               sorted, for binary search
    +4 + count*4    record[count], 16 bytes:
                        u32 unpacked size
                        u32 offset, in 2048-byte sectors
                        u32 0xffffffff
                        u32

There are **no names anywhere** - only hashes - so members come out named by their hash.

## Three pieces of arithmetic identify it, and none needs a name

* The hash array is **strictly ascending across all 4,314 entries**, spanning 767,790 to
  4,292,209,041.  That is what a sorted 32-bit hash table looks like and what nothing else in
  a header does; it is also enough to detect the format inside the 64 bytes `classify` sniffs,
  because the count and the first twelve hashes fit there.
* **Every record's third word is `0xffffffff`** - all 4,314 of them, exactly 16 bytes apart.
  That is what fixes the stride, and it is why the record array reads as noise until you find
  it: the sentinel sits in the middle of the record, not at its start.
* **The offset field is the only one that fits.**  Times 2048 its maximum is 1,353,596,928
  against a file of 1,353,598,976 - the last member ends on the archive's final sector.  Read
  as plain bytes, or with either of the other two fields standing in as the offset, nothing
  reaches even halfway.

## The check that confirms the whole reading

A member is a zlib stream when it starts `78 9c` and stored otherwise, and **the record's
unpacked size has to match what comes out**.  It does: of the first 120 records, 42 carry zlib
and all 42 inflate to exactly the declared size.  Over a wider sample of **617 members, all 617
read exactly and none was refused** - 227 MB of payload.

A member that comes out the wrong size returns `None` rather than being passed on short.

## What is inside - all four families identified (2026-09-04)

Sampling 91 members across the archive gives four families, and every one is now read:

* **`00 00 7c xx` / `00 00 7d xx`** - 48 of the 91, the bulk - are **sounds**, not geometry.
  The word that "always sits near 32,000" is the **sample rate** (31,911..32,062 Hz -
  pitch-adjusted per sound), the size-like word at +8 is the **sample count**, +12 is the
  **channel count** (1 or 2), and the f32 pair is **duration in 30 fps frames** and 1.0:
  `samples / rate == frames / 30` holds exactly on every member checked.  The `00 00 6d xx`
  family is the same header at ~28,000 Hz.
* **`4d 75 73 21`** is ASCII **`Mus!`** - music.
* **`00 00 00 0e`** - the DRM unit container, fully cracked below.  **Everything that is not
  audio travels in these**: textures, animations, VO metadata, and the models.

### `00 00 00 0e` - Crystal Dynamics DRM units, cracked

`gcrip/formats/tr_legend.py` + `gcrip/plugins/tr_legend.py`.  Version 14 is the same DRM
version Legend uses on other platforms; the GC layout, big-endian:

    +0   u32 version = 14
    +4   u32 count                    section records PLUS ONE
    +8   u32 unit_header_size
    +12  u32 0
    +16  u32 0x800                    map granularity, constant on every unit
    +20  u32 0
    +24  record[count-1], 20 bytes:
             u32 0xffffffff           pointer slot, patched at load
             u32 size                 payload bytes
             u32 type<<24 | sub       0 data, 2 animation, 5 texture, 6 wave, 7 material
             u32 relocs<<8
             u32 id
         u32 0xffffffff               the phantom "last record" is only this sentinel;
                                      the unit's relocation pairs start right after it
         pair[]  {u32 value, u32 offset}   offsets ascend and stay < unit_header_size,
                                           which is how the list's end is found
         unit header (unit_header_size bytes: LOD distances, object metadata)
    per section, in record order:
         pair[relocs] then the payload (size bytes)

**The tiling is byte-exact on 16 of 16 units**: header + records + sentinel + unit pairs +
unit header + per-section `relocs*8 + size` equals the member length.  The earlier "60 of 60
members have count 20-byte sentinel records" observation counted the phantom record as real -
the sentinel run passes either way, the end-of-file identity does not.

**Relocations** are `{u32 value, u32 offset}`: value's high u16 is `(target_section + 1) * 8`,
its **low u16 is uninitialised garbage** - fragments of a build-machine path (`:\`, `re`,
`.d`) survive in it - and offset is the patch site.  The u32 stored at the patch site is an
offset within the target section.

**Type 5 = textures**: 16-byte header `{u32 subtype, u32 w<<16|h, u32 data_size = size-16,
u32 format}` then GC texel data (CMPR blocks are visible in the bytes); subtype 0x12/0x09/0x05
distinguishes layouts.  Decoding these is still open.
**Type 2 = animations** (f32 pairs), **type 6 = waves** (sample-rate header like the 7c/7d
family), **type 7 = material stubs**.

### The models - GX-shaped display lists, and the reader ships

A type-0 section beginning `04 c2 04 52` is a **model header**: +0x10 f32 scale vec3, +0x20
vertex count, and four relocated pointers at +0x64/+0x68/+0x6c/+0x70 giving position / normal
/ color / uv array offsets - all into ONE geometry section.  That geometry section is a naked
GX display list from its start up to the first array: ops `0x99` strip / `0x81` quads /
`0x91` triangles (VAT 1), `0x00` NOP padding to 32-byte boundaries, and **9-byte vertices**:

    u8  matrix index (skinning; 0 on static models)
    u16 position index    -> s16 x,y,z * scale
    u16 normal index      -> s8 x,y,z / 127
    u16 color index       -> RGBA u8
    u16 uv index          -> u8 u,v   (quantisation unverified; /255 for now)

`gxscan` missed these because the lists carry no CP/VAT setup at all - arrays and formats are
bound by the engine from the model header, so the scanner had nothing to anchor on.  The one
place it fired (206 triangles) is one of these sections.

**Proof by render**: 43 models out of 16 sampled units, zero out-of-range indices, 9,011
clean triangles - and the wireframes are unambiguous: a perched bird, a spyglass, a crane,
and a leopard head **with whiskers** in the unit whose VO strings read
`VO\Animals\LEO_see_04`.  Median-edge/extent sits at 2-6% on organic models.

Still open: texture decoding (type 5 subtype -> GC format mapping), skinned assembly (the
matrix index and the per-segment pivot list at +0xf0 of the model header), the exact UV
quantisation, and `!WAR`.
