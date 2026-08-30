# `JAM2` archives - Charlie and the Chocolate Factory

The disc reported zero models and zero textures.  It holds 38 `.jam` archives, 245 MB, and they
are `JAM2` - **a different format from High Voltage's `LJAM`** ([high-voltage-ljam.md](high-voltage-ljam.md))
despite the shared extension.

## Layout - CRACKED

`gcrip/formats/jam2.py` + `gcrip/plugins/jam2.py`.  Little-endian.

    +0   char magic[4]   "JAM2"
    +4   f32
    +8   u32 directory size, measured from +32
    +12  char[8]         a compression name - "none" or "safe"
    +28  u16 name count | u16 extension count
    +32  char name[8] * name count        "FESPLASH", "DFE000AB", "LWRIGLE", "WONKAA"
    ...  char ext[4]  * extension count    "AGM", "GFF", "GMS", "TPL"
    ...  u32
    ...  records: u16 name index, u16 extension index, u32 member offset

A member's size is not in the record.  It is **at the member, written twice**:

    u32 size, u32 size again, 24 more bytes, then the payload

## The two things that had to be right

**The record table starts four bytes after the extension table.**  Counting those four bytes as
part of a record leaves everything half a record out - and it still parses.  The offsets still
validate, the members still tile, only the *names* are shifted, and the single visible symptom
is that 37 of the 38 records labelled `TPL` land on the `TPL` magic instead of 38.  With the
right start it is 38 of 38.  A format that keeps working when it is read wrong is worth a
deliberate check; the one used here is a magic that the extension table itself predicts.

**The 24 bytes after the two sizes are not always zero.**  They are on the archives tagged
`safe` and carry flags (`ff 00 00 00 ...`) on the ones tagged `none`.  Requiring them to be
zero parses the small front-end archives and rejects every member of the big level archives -
**234 of the disc's 245 MB**, silently, because a rejected record just looks like a junk record.

The two equal size words are check enough on their own: a record pointing at the wrong place
almost never lands on two identical `u32`, so junk records fall out and the real ones tile.

## Result

**37 of 38 archives parse to 24,897 members covering 243 of 245 MB.**  The 38th is a 48-byte
stub with no members at all.

    TPL 2,768   ASD 1,517   ASN 1,517   AGD 1,512   AGM 1,456   ANL 1,416
    AGT 1,375   GGG 1,204   AKC 1,121   GKA 1,115   AOD 1,114   AOB 1,097
    AOS 1,097   GMS 1,097   AGS   753   GSL   701   SSM   701   VFX   657

So the disc goes from zero textures to **2,768 `TPL`**.

## What this says about the open High Voltage formats

Charlie is a High Voltage game, and its archives hold **1,097 `GMS`, 1,115 `GKA` and 1,204
`GGG`** - the three formats still open on Billy & Mandy and Codename: Kids Next Door
([jam-fsta-hvs.md](jam-fsta-hvs.md)).  That takes `GMS` from two discs to three and gives a
third, independent corpus to work the codec against.

Only two `AGG` text meshes are on this disc (both parse), so Charlie's geometry is in `GMS`,
behind the compression - which is now the single thing standing between three discs and their
models.
