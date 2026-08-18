# Compatibility

Results of `gcrip survey` + `gcrip batch` over a 638-disc GameCube library (USA set), 2026-08-18.
No game data is stored here - only counts.

## J3D games (rip works end to end)

| game | ID | models exported | dups skipped | failed | clips | animated models | expression models | Mixamo rigs | textured % | s | notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| DONKEY KONG JUNGLE BEAT | GYBE01 | 486 | 6 | 0 | 2,110 | 207 | 22 | 18 | 95.3 | 141 |  |
| LUIGI'S MANSION | GLME01 | 73 | 37 | 0 | 119 | 56 | 0 | 0 | 100.0 | 30 | few BMDs; rooms/characters use Luigi's Mansion's own `.mdl` + `.bin` formats (718 .mdl) - future module |
| Mario Kart Double Dash! | GM4E01 | 387 | 335 | 0 | 378 | 116 | 35 | 2 | 95.1 | 55 |  |
| PAC-MAN vs. | PRJE01 | 20 | 0 | 0 | 5 | 3 | 1 | 0 | 100.0 | 10 |  |
| PIKMIN2 for GAMECUBE | GPVE01 | 683 | 438 | 0 | 743 | 299 | 0 | 1 | 97.4 | 156 |  |
| POKeMON BOX RUBY&SAPPHIRE | GPXE01 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 100.0 | 4 | 8 Pokémon storage models |
| Super Mario Sunshine | GMSE01 | 712 | 8,072 | 0 | 10,039 | 633 | 32 | 4 | 90.7 | 469 | 8,072 byte-identical duplicates skipped (every level .szs repeats the NPC set) |
| THE LEGEND OF ZELDA The Wind Waker for USA | GZLE01 | 1,856 | 902 | 0 | 4,406 | 432 | 117 | 76 | 95.6 | 284 |  |
| The Legend of Zelda Twilight Princess | GZ2E01 | 2,489 | 1,137 | 0 | 14,362 | 747 | 213 | 257 | 97.5 | 639 |  |
| The Legend of Zelda: Collector's Edition | PZLE01 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 12 | games are nested `.tgc` disc images (OoT/MM/WW demo) - TGC unpacking not implemented yet |
| The Legend of Zelda: Four Swords FOR NINTENDO GAMECUBE | G4SE01 | 63 | 50 | 0 | 0 | 0 | 0 | 0 | 100.0 | 24 | GBA-era assets; 63 small BMDs |

**Total: 11 games, 6,777 unique models, 32,162 animation clips, 0 model failures.**

## The rest of the library (survey engine guesses)

The survey samples file magics on each disc and peeks inside archives for J3D data (~2 s per disc).
Everything below needs a new parser module (documented formats) or the Dolphin capture fork.

| engine / publisher guess | discs |
|---|---:|
| EA (BIG/VIV) | 51 |
| EA | 51 |
| THQ | 47 |
| Activision | 44 |
| Ubisoft | 35 |
| Capcom | 24 |
| custom (.bin) | 23 |
| custom (.tpl) | 22 |
| custom (.dsp) | 21 |
| custom (.dat) | 17 |
| custom (.adp) | 14 |
| custom (.thp) | 13 |
| custom (.(none)) | 12 |
| custom (.h4m) | 11 |
| J3D | 11 |
| Nintendo (DAT) | 9 |
| custom (.bik) | 7 |
| custom (.pak) | 6 |
| custom (.rel) | 6 |
| custom (.str) | 6 |
| custom (.fpk) | 6 |
| custom (.afs) | 6 |
| custom (.hps) | 6 |
| custom (.tex) | 4 |
| Nintendo (RARC/U8, non-J3D) | 4 |
| custom (.gcp) | 4 |
| custom (.sfd) | 4 |
| custom (.spd) | 4 |
| custom (.txt) | 4 |
| custom (.bnr) | 4 |
| custom (.avi) | 4 |
| custom (.ngc) | 3 |
| custom (.pc) | 3 |
| custom (.rcf) | 3 |
| custom (.loc) | 3 |
| custom (.dol) | 3 |
| custom (.wad) | 3 |
| Sega (PRS) | 3 |
| custom (.pod) | 2 |
| custom (.zit) | 2 |
| custom (.rws) | 2 |
| custom (.lmp) | 2 |
| custom (.gct) | 2 |
| custom (.rar) | 2 |
| custom (.res) | 2 |
| custom (.vo) | 2 |
| custom (.bdg) | 2 |
| custom (.rom) | 2 |
| custom (.mid) | 2 |
| custom (.adx) | 2 |
| custom (.bmp) | 2 |
| custom (.png) | 2 |
| custom (.arc) | 2 |
| custom (.mss) | 2 |
| custom (.wav) | 2 |
| custom (.hdr) | 2 |
| Retro (PAK/CMDL) | 2 |
| custom (.dff) | 2 |
| custom (.ssf) | 2 |
| custom (.blt) | 2 |
| custom (.fsys) | 2 |
| custom (.gmf) | 2 |
| custom (.dgc) | 2 |
| custom (.all) | 1 |
| custom (.wgs) | 1 |
| custom (.pik) | 1 |
| custom (.obj) | 1 |
| custom (.lfb) | 1 |
| custom (.mds) | 1 |
| custom (.prd) | 1 |
| custom (.cc2) | 1 |
| custom (.rep) | 1 |
| custom (.zal) | 1 |
| custom (.sgd) | 1 |
| custom (.bgd) | 1 |
| custom (.pal) | 1 |
| custom (.tpf) | 1 |
| custom (.aob) | 1 |
| custom (.cct) | 1 |
| custom (.ani) | 1 |
| custom (.atx) | 1 |
| custom (.dtk) | 1 |
| custom (.dsq) | 1 |
| custom (.w2d) | 1 |
| custom (.chk) | 1 |
| custom (.irx) | 1 |
| custom (.cha) | 1 |
| custom (.ga) | 1 |
| custom (.ggf) | 1 |
| custom (.ast) | 1 |
| custom (.hfs) | 1 |
| custom (.song) | 1 |
| custom (.jam) | 1 |
| custom (.coc) | 1 |
| custom (.aka) | 1 |
| custom (.psc) | 1 |
| custom (.gvr) | 1 |
| custom (.rez) | 1 |
| custom (.asr) | 1 |
| custom (.xmd) | 1 |
| custom (.bgg) | 1 |
| custom (.scp) | 1 |
| custom (.can) | 1 |
| custom (.iff) | 1 |
| custom (.cat) | 1 |
| custom (.lgc) | 1 |
| custom (.wvs) | 1 |
| custom (.ste) | 1 |
| custom (.cgs) | 1 |
| custom (.cam) | 1 |
| custom (.spch) | 1 |
| custom (.blo) | 1 |
| custom (.pvr) | 1 |
| custom (.fbc) | 1 |
| custom (.sph) | 1 |
| custom (.xgc) | 1 |
| custom (.bti) | 1 |
| custom (.gcx) | 1 |
| custom (.bsf) | 1 |
| custom (.d4) | 1 |
| custom (.gtd) | 1 |
| custom (.msf) | 1 |
| custom (.adpcm) | 1 |
| custom (.gcg) | 1 |
| custom (.ssw) | 1 |
| custom (.one) | 1 |
| custom (.har) | 1 |
| custom (.p3d) | 1 |
| custom (.mld) | 1 |
| custom (.pdm) | 1 |
| custom (.bog) | 1 |
| custom (.pcm) | 1 |
| custom (.ilg) | 1 |
| custom (.movie) | 1 |
| custom (.vsp) | 1 |
| custom (.fuc) | 1 |
| custom (.be) | 1 |
| custom (.idsp) | 1 |
| custom (.lz) | 1 |
| custom (.an2) | 1 |
| custom (.slz) | 1 |
| custom (.pck) | 1 |
| custom (.x3g) | 1 |
| custom (.stm) | 1 |
| custom (.bnk) | 1 |
| custom (.gmb) | 1 |
| custom (.h) | 1 |
| custom (.rbb) | 1 |
| custom (.mrg) | 1 |
| custom (.igb) | 1 |

Notable non-J3D Nintendo titles: Super Smash Bros. Melee, Kirby Air Ride, Mario Superstar Baseball (HAL DAT);
Metroid Prime 1/2 (Retro PAK/CMDL); F-Zero GX, Super Monkey Ball 1/2 (Amusement Vision GMA/TPL);
Star Fox Adventures (Rare); Star Fox Assault, Mario Party 4-7 (Hudson); Pikmin 1 (.mod), Luigi's Mansion (.mdl/.bin),
Chibi-Robo (qp.bin), Animal Crossing, Battalion Wars, Fire Emblem, Paper Mario TTYD, Pokémon Colosseum/XD (.fsys), Wario World, Wave Race.
