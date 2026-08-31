# Cluster 9 survey: `.dgc` is three engines, `.adb` is two different things

## `.dgc` - 958 files over 5 discs, and **three unrelated engines**

Sized as one cluster it looks like a single 1.1 GB target.  Reading the first bytes of each
disc's largest file splits it three ways:

| engine | discs | files | size |
|---|---|---|---|
| Kalisto **TotemTech** (`TotemTech Data v1.73` / `v1.75 (c) 1999-2002 Kalisto Entertainment`) | Jimmy Neutron: Boy Genius, SpongeBob SquarePants ROTFD, Spirits and Spells | 383 | 525 MB |
| **Asobo Studio** (`v1.06.63.01 - Asobo Studio - Internal Cross Tech`) | Ratatouille | 320 | 340 MB |
| `MDGC0200` | Superman: Shadow of Apokolips | 255 | 234 MB |

This is the same mistake the `.hog` cluster made - **an extension is not a format** - and it is
worth writing down twice, because sizing by extension is what decides which cluster gets
worked first.

### What TotemTech looks like

A 79-byte ASCII banner, then the file proper.  There is **no name table anywhere**: a scan for
runs of six or more printable characters over the whole file returns 7,861 hits and every one
is coincidence.  Entropy by eighths runs 3.98, 5.14, 7.26, 7.81, 7.85, 7.44, 6.80, 6.50 - a
structured head and a compressed body.  A block at 2,048 reads as plausible fields
(`u32 1`, then 640 and 512, which look like dimensions) followed by repeating three-byte
patterns, and near the end sit smoothly varying byte triples that look like raw RGB.

So it is container **and** codec, a two-stage dive, and it is left here rather than started.

## `.adb` - 425 files over 11 discs, and low value either way

The two halves have nothing to do with each other, and gcrip's own classifier calls all 425
`unknown`:

* **14 large `Sounds.adb` / `SOUNDS.ADB`** on the Acclaim discs (All-Star Baseball 2002/2003/
  2004, NFL Quarterback Club 2002, Legends of Wrestling 2) - 200 to 660 MB each, opening with
  an ascending `u32` offset table.  The name is the only evidence of what they hold; the first
  member carries no magic this tree recognises.  Those discs' models and textures come from
  the Acclaim formats already shipped (`asb_tex`), so nothing here is blocking them.
* **411 tiny ones** elsewhere - Shadow the Hedgehog alone has 364 totalling **0.1 MB**, about
  300 bytes each, named `stg0503tn100.adb`, `s0503_dn008.adb`; EA's discs carry `meta.adb`.
  Far too small to hold geometry.

**Do not size this cluster by its file count.**  425 files sounds like the `.hog` cluster and
is worth a fraction of it.
