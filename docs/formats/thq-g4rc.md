# THQ `g4rc` textures - Avatar: The Last Airbender, Jimmy Neutron: Attack of the Twonkies

`docs/OPEN.md` carried this: *"`thq_pack` now opens all nine of Avatar's archives (245 members,
699 of 700 MB) but every member is a `.rad` object (`rad0` + a section table) and nothing reads
them."*

The container was never the problem, and the `.rad` is not a section table.

Read by `gcrip/formats/thq_g4rc.py` + `gcrip/plugins/thq_g4rc.py`.

## Three layers, all of them ordinary

    bt_DATA.PAK        a THQ pack (gcrip.formats.thq_pack) holding one member
      data/boot.rad    another pack - same "pack" magic, version 1
        *.rcb          plain zlib streams

28 of the 32 leaves in `boot.rad` inflate, into three tags: **`g4rc`** (24 - every `tex_*` and
`tx8_*` file), `bats` (3) and `0lmg` (1).  So a `.rad` is a pack inside a pack, and its leaves
are compressed - nothing exotic, just three layers deep.

## The texture

Big-endian, 32-byte header:

    +0   char magic[4]   "g4rc"
    +4   u32 version     7
    +8   u32 hash
    +12  u32 payload bytes    (the object is 32 + this)
    +16  u32 packed size
    +20  u32 mip levels
    +24  u32 0
    +28  u32 pixel bytes
    +32  the pixels, GX CMPR, level 0 first

**The dimensions are packed into +16: `width - 1` in bits 0-7, `height - 1` in bits 10-17.**
Nothing states them plainly, and the three-bit gap between the fields is what hides the
packing - read as two plain bytes, a 16x16 image comes out **16 x 60**. There is a test on
exactly that.

The reading is checked rather than fitted: the CMPR mip chain for those dimensions has to equal
the pixel count at +28, and it does on **18 of the 24** `g4rc` objects in `boot.rad`:

    160 bytes = 16x16 over two levels     16,384 = 256x128     32,768 = 256x256

The six that miss are not textures - four are fonts and a string table carrying zero mip
levels, and two declare zero pixel bytes. They are declined.

Decoded against a shuffled copy of their own blocks the images score **3.5x to 10.9x** smoother,
which is where every texture genuinely cracked in this project sits.

## Results

**486 textures from Avatar's three smallest `.pak` alone** - 256x256 (142), 256x128 (122),
64x64 (122), 32x256 (60). The disc has nine archives and 699 MB, so the full figure is far
larger.

Jimmy Neutron: Attack of the Twonkies shares the `pack` magic and yields nothing from its three
smallest archives, so its members are laid out differently; that is recorded rather than
assumed away.

## Still open

* `bats` and `0lmg`, the other two tags inside a `.rad`;
* Jimmy Neutron: Attack of the Twonkies (23 archives, 1,013 MB), which opens as a pack but
  whose leaves are not `g4rc`.
