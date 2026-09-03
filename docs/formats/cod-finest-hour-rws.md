# Call of Duty: Finest Hour `.rws` (2026-09-03)

Call of Duty: Finest Hour's ``.rws`` - RenderWare sections behind an 8-byte header each.

The disc reports **21 models** and holds 231 ``.rws`` totalling 582 MB.  Two different files
share the extension:

* the big ones - ``NGC_2s1.rws`` is 299 MB - open ``0x080D`` and are the streamed audio that
  ``docs/formats/rws-is-audio.md`` describes.  Nothing to rip.
* the ``s_*.rws`` are **level geometry**, and they are ordinary RenderWare behind a header so
  small it is easy to miss::

      u32 kind      0, 1, 2 ... for the WORLDs, 4 for the texture dictionary
      u32 size      of the RenderWare chunk that follows, header included
      ... a stock RenderWare chunk: TEXDICT (0x16) or WORLD (0x0B) ...

  repeated to the end of the file.

`plugins/renderware.py` declines the file because byte 0 is not a chunk id, and reads every
section happily once it is handed one.  On ``s_1.rws`` - 509,974 bytes - the walk finds **four
sections and lands on 509,970**, the last four bytes being padding, and the three WORLDs give
**14,957 triangles**.

The identity is the walk: `at += 8 + size` from byte 0 has to reach the end of the file, within
a padding word, and every section has to open on a RenderWare chunk carrying a 3.x version
stamp.  The audio files fail it at the first section - `0x080D`'s size is larger than the file -
so the two kinds cannot be confused.

## Measured

| file | bytes | sections | triangles |
|---|---|---|---|
| `s_1.rws` | 509,974 | 4 (1 TEXDICT, 3 WORLD), walk ends 509,970 | **14,957** |
| `s_6.rws` | 52 | 1 TEXDICT | 0 |
| `NGC_2s1.rws` | 298,950,656 | declined - streamed audio | - |

The three WORLDs read straight through `plugins/renderware.py`: 11,839, 265 and 2,853 triangles.

Sampling twelve files across the size range - 6.4 MB in total - gives **193,875 triangles**:

| file | bytes | sections | triangles |
|---|---|---|---|
| `s_2.rws` | 198,184 | 4 | 8,023 |
| `s_8.rws` | 340,614 | 4 | 12,857 |
| `s_13.rws` | 460,120 | 4 | 19,001 |
| `s_4.rws` | 509,820 | 4 | 20,560 |
| `s_9.rws` | 548,662 | 4 | 23,812 |
| `s_1.rws` | 633,192 | 4 | 26,023 |
| `s_5.rws` | 740,268 | 4 | 25,340 |

**228 of the disc's 231 `.rws` are under 6 MB**, and the disc reports 21 models today.

Two files in the sample yield nothing and are worth naming: `s_6.rws` at 52 bytes is a lone
texture dictionary, and `level.rws` at 1.5 MB is claimed by `is_container` - 64 bytes cannot
show otherwise - but `sections()` refuses it, so `expand` returns nothing.  That is safe:
`rip.py` already treats a container that claims and yields nothing as not having claimed at
all, so the file falls through to whatever reads it next.

## The correction this makes

`docs/formats/rws-is-audio.md` concluded that "on the three discs whose `.rws` are not opened at
all, every one of them is streamed audio, and there is no geometry in them to find".  That was
measured on **Asterix, Madagascar and Piglet**, and it holds there.  It does not extend to Call
of Duty: Finest Hour, whose `.rws` are two different things under one extension - the big ones
are that audio, and the `s_*` are levels.
