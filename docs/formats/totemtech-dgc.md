# Kalisto TotemTech `.dgc` / `.ngc` (2026-09-02)

Kalisto's ``TotemTech`` engine: the ``.dgc`` data file and its ``.ngc`` index.

Spirits & Spells, Jimmy Neutron: Boy Genius and SpongeBob: Revenge of the Flying Dutchman - 383
files, 525 MB.  ``docs/OPEN.md`` recorded the blocker as *"the file has no directory at all -
nothing anywhere references the verified vertex data"*.

**There is a directory, and it is the sibling file.**  Every ``.dgc`` has a ``.ngc`` of the same
stem - 225 and 225 on Spirits & Spells, sharing all 225 stems - and the ``.ngc`` is plain text::

    -853289997 "WORLD"
    854756687 "DB:>LEVELS>LEVEL07A>MAP>LEVEL07A.TWORLD"
    596819425 "LEVEL07A"
    -1989570394 "DB:>LEVELS>LEVEL07A>MAP>3DNODEFAMILY>ROOT_LEVEL07A.T3DNODE"

A signed 32-bit hash and the object's typed path, one pair per line.  `LEVEL07A.ngc` holds
**3,519** of them, 3,519 of 3,520 lines parsing, and the type suffix says what each object is:

===============  =====
``T3DNODE``      1,473
``TSURFACE``       116
``TGA``            108
``T3DNODE_UDEF``    87
``TBITMAP``         77
``TBITMAP_MAT``     77
``TVOLUME``         56
``TMESH``           52
===============  =====

**And the hashes are in the `.dgc`, big-endian.**  Of the first 400 index entries, **400 are
found verbatim** as big-endian `u32`; as little-endian, **0** are.  They begin at byte 2,056 in
the same order the index lists them, mostly packed four bytes apart, so the data file is a
reference graph keyed by the hashes the sidecar names.

That is what the note was missing.  A `TMESH` hash appears twice - once as a reference and once
at its definition - and the bytes after the definition are float-dense: 74% plausible big-endian
`f32` in the 4 KB following `O_ECHAFAUDAGE_MESH.TMESH`.

This module reads the index.  Walking the graph from a hash to its geometry is the next step and
is not done here.

## Verified on the real files

`LEVEL07A.ngc` parses to **3,519 entries**, 3,519 of 3,520 non-blank lines, and **all 52
`TMESH` entries are located in the 5.3 MB `.dgc`** by their big-endian hash.  Both declared
identities hold.

## What is left

Walking from a mesh's hash to its geometry.  A `TMESH` hash appears twice - a reference and a
definition - and the definition is followed by float-dense data (74% plausible big-endian `f32`
in the 4 KB after `O_ECHAFAUDAGE_MESH.TMESH`).  The header between them is unread.
