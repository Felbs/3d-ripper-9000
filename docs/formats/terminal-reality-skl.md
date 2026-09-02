# Terminal Reality `.SKL` skeletons (2026-09-02)

Terminal Reality ``.SKL`` skeletons - BloodRayne, Blowout, RoadKill.

Cluster 6's blocker.  ``docs/OPEN.md`` recorded that *"`HERO.SKL`'s bone records are not
fixed-layout (the numeric fields do not line up beneath the names), so that has to be settled
first"*.  **They are fixed-layout.**  What hides it is that the padding after each name is not
zeroes but ``BAADF00D`` repeated - the debug fill - so a name shorter than the field is followed
by ``0d f0 ad ba 0d f0 ad ba ...`` and the numbers appear to sit at a different place in every
record.

Little-endian::

    +0    u32   version    2 on every sample
    +4    u32   bone count
    +8    count x { char name[32]; s32 parent }

The stride is **36 bytes**, and the name field is a fixed 32 whatever the name's length.

Four checks agree on the whole table, on two skeletons of different sizes - 82 bones in
``SOLDIER_DEFAULT.SKL`` and 68 in ``MENTOR.SKL``:

* **every name decodes**, 82 of 82 and 68 of 68, as printable ASCII;
* **every parent is in range**, and there is **exactly one root** - index 0, ``Bip01 Pelvis``,
  with parent ``-1``;
* **no parent points forward.**  Every parent index is smaller than its child's, so the table is
  already in topological order and can be walked in one pass.  A wrong stride would scatter that
  immediately;
* the tree is anatomically right where it can be read - ``Bip01 R Calf`` hangs off
  ``Bip01 R Thigh``, ``Bip01 Neck`` off ``Bip01 Spine2``, ``bip01 apron2`` off ``bip01 apron1``.

The table is small: 82 bones end at byte 2,960 of a 2,954,178-byte file.  **The rest is
animation**, which matches the earlier finding that `.SKL` is 99% clips.

**There are no bind transforms here** - a record is a name and a parent, nothing more.  So this
reads the hierarchy and does not by itself settle the ``_dfm`` vertex layout, which needs the
bind pose.  What it does remove is the reason that work was blocked.

The count cross-checks against the mesh: ``soldier.dfm``'s fourth word is 82 and
``mentor.dfm``'s is 68, each matching its skeleton's bone count exactly.

## Where it sits

`gcrip/formats/tr_skl.py`, reached through `plugins/tr_pkg.py`: `gcpkg.pod` holds 43 `.PKG`
packages and a package holds the assets - `GC_AR_DE_SUBBAY.PKG` alone has 146 members
including two `.SKL` and two `.dfm`.  BloodRayne has 133 `.SKL` and 228 `.DFM` in total.
