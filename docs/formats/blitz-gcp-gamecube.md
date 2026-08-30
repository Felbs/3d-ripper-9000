# Blitz Games .gcp packs (2026-08-29, container only)

Discs: Pac-Man World 3, Bratz Rock Angelz / Forever Diamondz, Bad Boys Miami Takedown, Cubix
Showdown, Fairly OddParents Shadow Showdown, Frogger Ancient Shadow, Chicken Little (+more) -
9 library discs on Blitz's engine (BlitzTech). Implemented: `gcrip/plugins/blitz.py` (container).

- `AllPaks.gcp` (335 MB on PMW3) = header (`u32 hash, u32 0x800 data start, u32 0, u32 count
  0x152, ...`) then ~90 uncompressed packages at 0x800-aligned offsets (entropy 3-5.5).
  `Music/*.gcp` share the header shape (`hash, 0x20, 0, count, 16-byte entries`) and hold
  compressed audio (entropy 7.4+), no packages.
- Package = `01 69 07` + build stamp string (`20/09/2005 at 15:32:48 by AJohnson`) then a
  type-tagged object stream: entity classes (`compoundfunctions`, `sectorpackages`, `sector`,
  `WorldSector`, `dynamic_light`, `refpoint`, `PropAttachment`, `<noentclass>`), tags 01/03/07,
  length-prefixed strings. Geometry lives inside "sector" packages as raw GX display lists:
  gxscan on a 9.4 MB sector package found 15 meshes / 13.7k tris (some garbage, bbox +-32768)
  in 171 s. Real serialisation format not decoded - the container split lets the gx fallback
  scan each package within budget; a proper parser is the next step for this family.

## Dig 2026-08-29 evening (what the pack really is)

`AllPaks.gcp` is an ARCHIVE of the per-level `.gcp` packs, not a flat pack: the header numbers
are 0x800-sector units, and `word[10] * 0x800` lands exactly on the name table (PMW3:
`0x27f86 * 0x800 = 0x13fc3000`, 338 NUL-terminated names such as `spectral_realm_3_sector01.gcp`,
`2dmazelevel_world.gcp`).  A 32-byte entry table follows at `word[4] * 0x800 = 0x13fc5000`:
`u32 hash | u32 hash2 | u32 size (0x800-aligned) | u32 sector | 16 zero bytes`.  Neither
`sector * 0x800` nor `size` as an offset lands on a package stamp, so one field is still
misread (maybe the sector is relative to a data base, or the pair is (offset, size) in a
different unit) - that is the next thing to settle for this family.

The object stream itself tokenises cleanly: `0x00` end, `0x01` u8, `0x03` u16, `0x05` u32,
`0x06` f32 (LITTLE-endian), `0x07` NUL-terminated string; a 9.4 MB package walks to 43k u8,
25k f32, 10k u32 and 5.4k strings.  It is the world / entity tree (placements, `simulation_object`,
`cpropblinker`, `refpoint`, mesh NAMES like `m_srx_oct_blinkplat`), not geometry: searching the
packages for GX signatures finds only false positives in high-entropy regions, so the meshes
live in the member `.gcp` files that the entry table addresses.  Entropy across a package
alternates 4-5 (token stream) and 7.2-7.7 (textures / compressed blobs).
