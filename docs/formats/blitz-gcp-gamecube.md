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
