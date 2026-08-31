# Textures-only scenes wrote no textures

A plugin that finds images with no geometry attached builds a `Scene` carrying `textures` and
**no materials at all**, and marks it `extras["textures_only"] = True`.  Thirteen plugins do
this - every texture format in the tree that is not bound to a model:

    asb_tex  blitz_tex  bmp  dds_pack  frd_gct  gct  gvm
    png  res  tim2  toc_tim  tpl  tr_tex

The glTF exporter wrote only the textures that a **material named**:

    used = {m.texture for m in scene.materials if m.texture}

With no materials that set is empty, so every one of those scenes decoded its images correctly
and then **wrote none of them** - silently.  No warning, an empty `_tex` folder, a glTF with an
empty `images` array and a zero-length `.bin`.  It looks exactly like a successful rip.

`ripcore/gltf.py` now falls back to the whole texture dictionary when nothing references
anything, and keeps the narrower set when materials do name textures.

## How it was found, and why the tests did not

Every one of these plugins has tests, and they all pass: they assert that
`extract()` returns a scene whose `textures` dict holds the right images.  That is true and
always was.  The loss happens one layer further out, in the exporter, and **no test crossed
that boundary**.

It surfaced only from running the real `gcrip rip` chain end to end on one archive and looking
at the files on disk - the new `tim2` plugin fired correctly, produced
`afs02.afs/member0000.bin/0.gltf`, and that file had `"images":[]`.  Checking the decoder's
return value would have shown four perfect textures.

**The lesson generalises past this bug: a decoder returning the right object is not evidence
that anything reached the disk.**  Check the output files.
