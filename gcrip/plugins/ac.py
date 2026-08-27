"""Animal Crossing (GAFE01): assessment only - no models are extracted yet.

The game is the N64 title (Doubutsu no Mori) running on a GameCube emulation layer, and its
art never left the N64 formats.  What the disc holds (sample tree of GAFE01):

* ``foresta.rel.szs`` (15.6 MB decompressed, REL id 1, 20 sections): the whole game outside
  the DOL.  Its 11.4 MB data section is where every model lives, as Fast3D **F3DEX2 display
  lists** with N64 vertex buffers: a scan of the 8-byte-aligned words finds ~57k ``G_VTX``,
  ~15k ``G_TRI1``, ~13k ``G_TRI2``, ~8k ``G_ENDDL``, ~24k ``G_SETCOMBINE``, ~20k ``G_SETTIMG``
  and ~2.5k ``G_MTX``/``G_SETTILE``/``G_LOADBLOCK`` words - i.e. thousands of display lists
  drawing from 16-byte N64 vertices (s16 xyz, flag, s16 st, rgba8) and N64-format textures
  (RGBA16 / CI8 / CI4 / IA8 ... with TLUTs), all addressed through REL relocations.
* ``forest_1st.arc`` / ``forest_2nd.arc`` (RARC): ``bin1/data/*.bin`` - mail, palette, face,
  item and save tables, no geometry.
* ``famicom.arc``: the NES games (``*.nes.szs``) and their GBA ports, plus a few ``.bti``.
* ``static.map`` / ``foresta.map``: symbol maps for the DOL and the REL (full function and
  data names - ``*_model``, ``*_shp`` symbols would let a ripper name every display list).
* ``audiorom.img``: the N64 audio ROM image used by the sound emulation.

What a ripper would need, in order:

1. Apply the REL relocations (``relOffset`` table, R_PPC_ADDR32 against the REL's own
   sections) so ``G_DL`` / ``G_VTX`` / ``G_SETTIMG`` segment addresses become file offsets.
2. Use ``foresta.map`` to enumerate the model symbols (the data section is keyed by name:
   actor ``*_model`` / ``*_shape`` display-list roots, ``*_v`` vertex arrays, ``*_txt``
   textures) - without the map, roots can be found by ``G_ENDDL`` back-tracking.
3. An F3DEX2 interpreter (``gcrip.formats`` has GX decoders, not RSP microcode): vertex
   cache of 32, ``G_TRI1``/``G_TRI2`` indices, ``G_MTX`` push/pop for the actor skeletons,
   ``G_SETCOMBINE``/``G_SETTILE``/``G_LOADBLOCK``/``G_SETTILESIZE`` for texture state.
4. N64 texture decoders (RGBA16, RGBA32, IA4/8/16, I4/8, CI4/CI8 + RGBA16/IA16 TLUTs) with
   the N64's 64-byte TMEM line swizzle (the GC port keeps the data byte-identical).
5. Animations are the N64 "keyframe" format in the same section (``*_anime`` symbols).

None of that shares code with the GX/J3D pipeline, so this stays an assessment; the plugin
defines no ``detect``/``extract`` and the loader skips it.
"""

from __future__ import annotations

NAME = "ac"
