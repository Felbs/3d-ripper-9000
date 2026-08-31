# Auditing for plugins that never fire

Four times in one session a decoder that worked in isolation turned out to be **dead in the
pipeline** - and every one produced a disc that rebuilt with zero output and no error.  So the
audit was made systematic instead of accidental: take every disc that produced **no models and
no textures**, read the first 64 bytes of its largest few non-audio files, and ask whether any
non-fallback plugin claims them.  A claim plus no output is the dead-plugin signature.

Of 301 such discs, ignoring the `gx` and `generic` fallbacks (which legitimately claim
everything and find nothing on many discs), these plugins claim files on discs that produced
nothing:

| plugin | discs | example |
|---|---|---|
| `ea` | 9 | Harry Potter: POA `PACKAGES.BIG`, 582 MB |
| `afs` | 9 | Gundam vs Z Gundam `afs_data.afs`, 365 MB |
| `tim2` | 11 | The Sims 2 `audiostr.arc` - **false claims**, see below |
| `cd_bigfile` | 8 | Beyblade `add00dat.bin` |
| `blitz` | 3 | Cubix Showdown `music.gcp`, 177 MB |
| `vc_dat` | 3 | NFL2K3 `game.dat`, 1.28 GB (payload known open) |
| `rkv` | 2 | Blood Omen 2 `gamecube.rkv`, 442 MB |
| `melee` | 1 | TMNT: Mutant Melee `archive.dat`, 220 MB |
| `toc_wad` | 1 | Smashing Drive `common.wad` - **a real new disc**, see below |
| `climax_bad` | 2 | SX Superstar `superc.bad`, 178 MB |

## What the audit turned up

**Smashing Drive is a third disc for `toc_wad` / `toc_tim`.**  Its `.wad` open with a name
(`_ABC28`) and the type tag `TIM` at +16 - the magic-less inline variant.  18 of 20 archives
parse to **8,672 members**, and **2,655 of 2,655 `TIM` decode**.  The disc was producing
nothing at all.

**TMNT: Mutant Melee's dump is stale, not broken.**  Its `archive.dat` sits in the manifest as
`kind=unknown` with no members, and the disc rebuilt in 9 seconds with zero output.  But the
plugin is fine - `expand_with` yields **8,367 members** against the real disc - and the gate
that decides whether to read a 230 MB file whole (`needs_whole`, which is what keeps files over
the 32 MB `STREAM_THRESHOLD` from being expanded) returns **True** for it today.  So the code
as it stands would expand it; the dump predates that and the disc needs re-ripping, nothing
more.

**SX Superstar is a Climax relative, not a fourth `.bad` disc.**  It opens
`u32 0 | u32 0xa2d4 | "BAC 1.02"` where ATV has `... | 0xff "CUBAN 1.02"`.  The `0xff` that
starts every known stream is absent, so `stream_start` declines and `expand` yields nothing -
correctly.  Whether its payload is stored or begins further in is unanswered.

**`tim2` and `cd_bigfile` are claiming too widely.**  `tim2`'s offset-table shape matches
`audiostr.arc` and `movies.arc` on the Sims 2 discs; `cd_bigfile`'s ascending-hash test matches
Beyblade's `add00dat.bin`.  Both `expand` to nothing, so they are harmless - a wrong claim
costs one in-memory parse - but they are noise in this audit and should be read as such.

## Following the audit's other leads

Calling each claiming plugin's `expand` directly on the disc separates a dead plugin from an
archive that is genuinely empty:

| disc | archive | expands to | verdict |
|---|---|---|---|
| Disney's The Haunted Mansion | `mansion.jam` 409 MB | **16,252 members, 2,945 `.tpl`** | stale dump |
| Jimmy Neutron: Jet Fusion | `Data_GC.rkv` 494 MB | 12,646 members | worth a re-rip |
| Harry Potter: POA | `PACKAGES.BIG` 583 MB | 2,151 `.pkg` / `.pkga` | expanded, inner open |
| Gundam vs Z Gundam | `afs_data.afs` 365 MB | 2,572 `.bin` | expanded, inner open |
| Cubix Showdown | `music.gcp` 177 MB | 44 `.str` / `.wav` | audio, correctly nothing |
| Blood Omen 2 | `gamecube.rkv` 442 MB | **0** | false claim |

**Haunted Mansion is the clearest case.**  Only `jam2` claims `mansion.jam`, and it yields
16,252 members of which **2,945 are `.tpl` - all 60 sampled parse as real TPL**.  The disc's
manifest holds 2,590 entries and not one `.tpl`, and the disc rebuilt with zero models and
zero textures.  The plugin is right, the dump predates it.

That is the same shape as TMNT: Mutant Melee, and it is worth naming as a category of its own:
**a stale dump looks exactly like a dead plugin from the outside.**  The way to tell them apart
is to run the plugin against the disc by hand - if it works today, the dump is old; if it does
not, the plugin is broken.

## How common is a stale dump?

Sweeping every disc with a large top-level archive: of 228 checked, **80 have the archive
expanded in the manifest and 27 are claimed by a plugin with no nested entries at all**.  Most
of the 27 are explained without any bug:

* **audio, by name** - `SH_VOICE_E.afs`, `PRS_VOICE_E.afs`, `V_CHAO_E.AFS`, `oga_bgm.afs`,
  `event_adx.afs`, `soundgc.big`, `sound.zip`, `music.rcf`, `Sounds.adb`, `sndgc.bin`;
* **false claims that expand to nothing** - `skye_pak` on Shrek Smash N Crash's 377 MB
  `Packfile.dat`, `shoc` on Freekstyle's `freekDat.ngc`, `zip` on NFL Blitz's `stadium.zip`,
  `cd_bigfile` on Beyblade's `add00dat.bin`.  Harmless, and now recorded so the next audit does
  not chase them.

What is left is small and real: **Haunted Mansion** (2,945 valid TPL), **TMNT: Mutant Melee**
(8,367 members), **Jimmy Neutron: Jet Fusion** (12,646), **Smashing Drive** (2,655 TIM), and
**Chibi-Robo** whose `qp.bin` gives 1,153 members but only 5 TPL and 1,132 the classifier
cannot name - not worth a disc rip on its own.

## Run this after any rip

A disc that produces 0 where a decoder measured thousands is a dead plugin, not a hard format.
The check costs 64 bytes a file.
