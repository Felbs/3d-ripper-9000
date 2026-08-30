# gcrip plugin trap: container detection only ever sees 64 bytes

Found 2026-08-30 while verifying the Terminal Reality chain end to end, and it had silently
broken that whole night's work.

`gcrip.classify.SNIFF_BYTES` is **64**, and both call sites that ask a plugin whether a file is
an archive pass exactly that much:

* `gcrip/manifest.py` - `mod.is_container(name, data[:SNIFF_BYTES])` when walking the disc;
* `gcrip/rip.py` - `mod.is_container(name, payload[:64])` when expanding at rip time.

`detect(path, head, size)` is the same: `rip.py` reads `src.get(e.path)[:64]`.

So a check that reads any field past byte 64 **never fires, and fails silently** - no error, the
file is simply never treated as an archive.  Two plugins written that night did exactly this:

* `gcrip/formats/pod.py` required 0x60 bytes and read the POD3 index offset at **0x108**;
* `gcrip/formats/tr_pkg.py` required its full 76-byte chunk header.

Both returned False for every real file.  The POD archives would never have been expanded, so
the `.PKG` packages, the `_smf` meshes and the `.TEX` textures behind them would all have
produced nothing on the next pass, with no error to show for it.

## The rule

**Detect on the magic; validate in `expand`.**  `expand` (and `extract`) are handed the whole
file, so that is where the directory, counts and offsets get checked.  `is_container` should do
no more than confirm the magic and, where it helps, the extension.

## How to catch it

A unit test that feeds the plugin exactly `SNIFF_BYTES`:

```python
def test_detected_from_the_64_byte_sniff():
    from gcrip.classify import SNIFF_BYTES
    assert plugin.is_container("LANGUAGE.POD", build()[:SNIFF_BYTES])
```

An audit of every container plugin for `len(head) >= N` with N > 64 found only one other hit,
`bml`, and that one is safe: it explicitly falls back when the head is short.

The end-to-end check worth repeating after any container work is to walk the real chain with
64-byte sniffs at every level - POD -> PKG -> members.  For the two sample packages that gives
232 scenes, 4,128 triangles and 201 textures; before the fix it gave zero.

## The audit found a third victim: Billy Hatcher terrain

Auditing all 50 `detect()` plugins the same way turned up one more, and this one was NOT from
that night's work - it had been dormant:

`gcrip/formats/billy_lnd.py`'s `is_lnd` opened with `len(head) < 0x60`, i.e. it wanted 96
bytes, because the texlist pointer pair it validates usually sits past byte 64.  Billy Hatcher
and the Giant Egg ships **79 `.lnd` terrain files** and not one was ever detected.  The disc
reports 896 models and **0 textures**.

The unit test hid it perfectly: `tests/test_billy.py` fed `data[:0x60]` - more than the ripper
ever has.  A test is only as good as the width of the slice it passes.

`is_lnd` now validates what a 64-byte head actually contains - the `0100` version stamp at 0x14
and the total length at 0 that must equal the file size exactly, which together are decisive -
and still checks the texlist whenever the caller passes enough bytes.  Verified on
`k_battle_blue.prd/stg_blue_battle.lnd`: **1,726 triangles, 23 textures, 34 primitives**, from a
file that previously produced nothing.

`bml` was the only other plugin reading past byte 64, and it already falls back safely.
