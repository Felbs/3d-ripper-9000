# Mega Man X: Command Mission `.arc` - a TPL in a wrapper

1,467 `.arc` files, disc reported zero models and zero textures.

Each one is a **32-byte header followed by a stock Nintendo TPL**:

    +0   u32            0x35 on the file measured
    +4   char name[4]   e.g. "80go"
    +8   u32 0
    +12  u32 payload size   (file size - 32)
    ...
    +32  the TPL

The arithmetic closes exactly, which is what identifies it: `OG085.arc` is 143,456 bytes, its
image header reads 640x448 `CMPR` with a data offset of 0x40, and
`0x20 + 0x40 + 143,360 = 143,456`.

A TPL's internal offsets are relative to its own header, so the fix was to resolve every one of
them against the base - `gcrip.formats.tpl.parse(data, base)` now offsets the image table, the
image headers, the palette header, the palette data *and* the pixel data.  A first attempt
offset only the header read and produced dimensions like 65,535 x 65,535, which is what a
partly-rebased parse looks like.

**117 of 117 TPLs decode with no failures** over a 150-file sample: 128x128 `C8` (25), 640x448
`CMPR` (12), 256x256 `CMPR` (10), and so on.  Through the plugin chain, 98 of 120 sampled `.arc`
are claimed and yield a texture each - the rest carry no TPL.  With 1,467 files on the disc that
is on the order of **1,200 textures** from a disc that reported none.

## Not the other `.arc` discs

Checked and ruled out: Mega Man X Collection, Evolution Snowboarding, Over the Hedge and
Cabela's carry no TPL at the head of their `.arc`.  Those are different formats and stay in the
cluster-2 backlog; only Command Mission uses this wrapper.
