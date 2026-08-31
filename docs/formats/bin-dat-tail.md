# Cluster 10: the `bin`/`dat` tail, surveyed

Never opened before.  The headline number is blunt: **431 of 629 dumped discs produced no
triangle-bearing model at all**, and every one of them is `bin`/`dat`-dominated.

## The tail is inner-format-bound, not container-bound

Of 158 large (>4 MB) `bin`/`dat` files on those discs, with audio and video excluded by the
manifest's own `kind`, **114 are claimed by no specific container plugin** - they fall through
to the `generic` fallback.  But the magics do not cluster: the commonest is eight files of
plain zeros, then six sharing one magic, then four, then a long tail of ones and twos.

**There is no single format here worth attacking.**  What there is:

## Two dead ends, closed

* **`SCHl`** is EA's audio chunk format - Knockout Kings 2003's `PRIMDAT.BIN` and
  `PRIMSLUGDAT.BIN`, Quidditch World Cup's two `dat.dat`.  **516 MB over two discs, audio.**
* **`FJF\0`** on Sonic Mega Collection is `testadx.bin` and `history_adx.bin` - ADX audio, as
  the names say.

## One new cluster: the `Kashmir` engine, three discs

Magic `a4 0d 6d 71`, and the header carries the toolchain in plain text:

    +0   a4 0d 6d 71     magic
    +4   u32 2           version
    +12  u32 1000
    +20  u32 47 / 46 / 48
    +24  two u32 that track each other a few thousand apart
    +32  char[] author, NUL terminated - "rapati2", "bbratu", "chriscu2"
    ...  char[] "Created/Modified using Kashmir"

on **City Racer** (52 `.dat`), **Speed Challenge: Jacques Villeneuve Racing** (33) and
**Taxi 3** (10) - track files of 5 to 6 MB each.  Three discs sharing an engine, a version
word and a named toolchain.

### What is inside

It is a **property-driven scene graph**, not a plain archive.  Entities appear as an **8-byte
type id followed by a NUL-terminated name**, and the same id turns up earlier on its own - a
type table first, then the instances that use it.  City Racer's are `GhostPoint` and
`StartPoint00`; Taxi 3 exposes the property names too, which is what gives the format away:

    AnimatedObject_SoundSource   WaveName   MinDistance   MaxDistance   Volume
    UseDoppler   StartMode   Random_WaitingTime   Random_Value   Draw_Sphere   AOcean

Taxi 3 alone shows 125 distinct names in its first 400 KB against City Racer's 19, so the
naming is a build option rather than a format difference.

**The geometry is not reachable yet.**  Entropy by sixths runs 7.23, 1.59, 7.45, 6.81, 6.19,
7.25 on City Racer and 7.05 to 7.43 on Taxi 3 - dense or packed throughout - and `gxscan`
finds nothing at all in City Racer and two meshes in Taxi 3.  So this is container **and**
payload, the same two-stage shape as TotemTech, and it is left here with the entity grammar
written down.

## The biggest single unclaimed file

**Tomb Raider: Legend's `bigfile.dat`, 1,290.9 MB** - the whole game in one file, with only
`bi2.bin` and `fst.bin` beside it.  It opens with an ascending big-endian `u32` table
(4,314 then 767,790, 810,686, 1,701,595, 2,315,698 ...) which is neither sector offsets - the
values run past the file - nor plainly 32-bit hashes, since they all sit under 17 million.

## What this changes

The tail was the last cluster on the list on the assumption that it might hide a common
format.  It does not.  Future effort is better spent on the named clusters and on the three
`Kashmir` discs than on the tail as a whole, and the two audio families above never need
looking at again.
