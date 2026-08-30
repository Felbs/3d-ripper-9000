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
