# Compatibility

`gcrip survey` + `gcrip dump` over a 638-disc GameCube library (USA set), 2026-08-26. 638 discs processed, 0 errored. No game data is stored here - only counts.

## Games that rip (J3D models -> glTF)

| game | ID | models | dups | failed | clips | animated | expressions | Mixamo rigs | textured % | textures | extras | s | notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| The Legend of Zelda Twilight Princess | GZ2E01 | 2,489 | 1,137 | 0 | 13,822 | 755 | 213 | 257 | 97.5 | 1,704 |  | 658 |  |
| THE LEGEND OF ZELDA The Wind Waker for USA | GZLE01 | 1,856 | 902 | 0 | 4,175 | 432 | 117 | 76 | 95.6 | 1,867 | stages 156, text, streams 76, music 93, cutscenes 48 | 590 |  |
| The Legend of Zelda: Collector's Edition | PZLE01 | 1,710 | 624 | 0 | 4,175 | 432 | 117 | 76 | 95.3 | 1,784 |  | 282 | the Wind Waker demo inside `ZL_WindWakerUSASHOP_*.tgc`; OoT/MM are N64 ROMs (not J3D) |
| Super Mario Sunshine | GMSE01 | 712 | 8,072 | 0 | 10,039 | 633 | 32 | 4 | 90.7 | 754 |  | 483 | byte-identical duplicates skipped (every level .szs repeats the NPC set) |
| PIKMIN2 for GAMECUBE | GPVE01 | 683 | 438 | 0 | 372 | 299 | 0 | 1 | 97.4 | 17,232 |  | 167 |  |
| DONKEY KONG JUNGLE BEAT | GYBE01 | 486 | 6 | 0 | 1,947 | 207 | 22 | 18 | 95.3 | 240 |  | 138 |  |
| Mario Kart Double Dash! | GM4E01 | 387 | 335 | 0 | 199 | 116 | 35 | 2 | 95.1 | 1,090 |  | 53 |  |
| LUIGI'S MANSION | GLME01 | 73 | 37 | 0 | 98 | 56 | 0 | 0 | 100.0 | 1,393 | streams 2 | 31 | few BMDs; rooms/characters use Luigi's Mansion's own `.mdl` + `.bin` formats - future module |
| The Legend of Zelda: Four Swords FOR NINTENDO GAMECUBE | G4SE01 | 63 | 50 | 0 | 0 | 0 | 0 | 0 | 100.0 | 2,593 |  | 24 | GBA-era assets; small BMDs |
| PAC-MAN vs. | PRJE01 | 20 | 0 | 0 | 5 | 3 | 1 | 0 | 100.0 | 189 |  | 9 |  |
| POKeMON BOX RUBY&SAPPHIRE | GPXE01 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 100.0 | 2,017 |  | 4 | 8 Pokémon storage models |
| ZELDA OCARINA MULTI PACK | D43E01 | 6 | 0 | 0 | 4 | 2 | 0 | 0 | 66.7 | 267 |  | 13 |  |

**Total: 12 games, 8,493 unique models, 34,836 animation clips, 0 model failures.**

## Games where only standalone textures come out (TPL/BTI, no J3D models)

Every one of these ran through the full pipeline without error; their models are in
formats gcrip does not parse yet (see the engine guesses below).

| game | ID | textures | engine guess |
|---|---|---:|---|
| World Racing | GWDP6S | 4,038 | custom (.tpl) |
| International Superstar Soccer 3 | GJ3PA4 | 2,544 | custom (.tpl) |
| Zatch Bell!: Mamodo Fury | GABEAF | 2,367 | custom (.tpl) |
| Doshin the Giant | GKDP01 | 1,777 | custom (.tpl) |
| Army Men : RTS | GARE5H | 1,608 | custom (.tpl) |
| GC Dragon Drive | GD5JB2 | 1,419 | custom (.tpl) |
| Midway Arcade Treasures 3 | GE3E5D | 1,409 | custom (.(none)) |
| Paper Mario | G8ME01 | 1,263 | custom (.(none)) |
| Lotus Challenge | GLUE7U | 1,262 | custom (.wav) |
| FIRE EMBLEM GC US | GFEE01 | 1,187 | custom (.ga) |
| Dragon's Lair 3D | GDGE7H | 1,173 | custom (.tpl) |
| WS2002 GAME DISK | GJ2PA4 | 1,082 | custom (.tpl) |
| Pikmin | GPIE01 | 1,002 | custom (.bti) |
| Zoids: Battle Legends | GZSE70 | 846 | custom (.dat) |
| ZOIDS VS.3 | GZVJDA | 832 | custom (.txt) |
| 1080: Avalanche | GTEE01 | 787 | custom (.tpl) |
| Pac-Man World 2 | GP2EAF | 777 | custom (.tpl) |
| WS2002 GAME DISK | GJ2JCM | 692 | custom (.tpl) |
| Go! Go! Hypergrind | GHGEEB | 683 | custom (.tpl) |
| WRESTLE MANIA X8 | GW3E78 | 623 | THQ |
| CustomRobo | GXCE01 | 590 | custom (.tpl) |
| Hunter: The Reckoning | GHNE71 | 566 | custom (.aka) |
| Harvest Moon Magical Melody | G4AEE9 | 552 | custom (.mss) |
| Sonic Mega Collection (US) | GSOE8P | 457 | custom (.tpl) |
| Disney's Magical Mirror starring Mickey Mouse | GDME01 | 391 | custom (.bin) |
| PoolEdge for JPN | GPEJ2Q | 391 | custom (.tpl) |
| Disney's Hide & Sneak | GHVE08 | 353 | Capcom |
| Pro Rally | GRLE41 | 336 | Ubisoft |
| Egg Mania | GEME7F | 333 | custom (.tpl) |
| GTCUBE | GTCJBL | 320 | custom (.tpl) |
| CHAOSFIELD EXPANDED | GKFEGG | 296 | custom (.tpl) |
| RADIRGY GENERIC | GLJJMS | 294 | custom (.tpl) |
| resident evil 4 disc2 | G4BE08 | 287 | Capcom |
| resident evil 4 disc1 | G4BE08 | 287 | Capcom |
| X2 Wolverine's Revenge | GWVE52 | 274 | Activision |
| Harvest Moon: A Wonderful Life | GYWEE9 | 252 | custom (.arc) |
| Harvest Moon: Another Wonderful Life | G4GEE9 | 239 | custom (.arc) |
| Ultimate Muscle: Legends VS. New Generation | GKNEB2 | 217 | custom (.dsp) |
| BUST A MOVE 3000 | G3SE41 | 209 | Ubisoft |
| ZOIDS VS. | GZOJDA | 192 | custom (.adp) |
| Mr.Driller DrillLand | GDPJAF | 187 | custom (.tpl) |
| WAVE RACE / BLUE STORM | GWRE01 | 175 | custom (.adp) |
| Medabots: Infinity REV. | GM6EE9 | 155 | custom (.dat) |
| Monster 4x4: Masters of Metal | GMZE41 | 153 | Ubisoft |
| Fantastic Four | GF4E52 | 142 | Activision |
| RAYMAN 3 HOODLUM HAVOC | GRHE41 | 139 | Ubisoft |
| Charinko Hero | GTHJD9 | 131 | custom (.tpf) |
| Def Jam VENDETTA | GDTE69 | 125 | EA (BIG/VIV) |
| P.N.03 | GPNE08 | 119 | Capcom |
| Resident Evil 0 | GBZE08 | 106 | Capcom |
| Resident Evil 0 | GBZE08 | 106 | Capcom |
| EVOLUTION WORLDS | GEWE41 | 100 | Ubisoft |
| GEKITUISENKI | GZFJBP | 82 | custom (.bin) |
| WWE Day of Reckoning 2 | GW2E78 | 76 | THQ |
| RAYMAN ARENA | GRYE41 | 74 | Ubisoft |
| UniversalStudiosThemeParkAdventure | GUSE7F | 57 | custom (.bin) |
| Dredd 2004-02-26 NTSC RC5 | GJDE5S | 54 | custom (.asr) |
| DISNEY'S PK: OUT OF THE SHADOWS | GPKE41 | 45 | Ubisoft |
| Odama US ver | GOOE01 | 45 | custom (.hps) |
| AnimalCrossing | GAFE01 | 41 | Nintendo (RARC/U8, non-J3D) |
| Army Men Air Combat | GACE5H | 31 | custom (.wgs) |
| Bomberman Generation | GBGE5G | 29 | custom (.adp) |
| Eternal Darkness | GEDE01 | 29 | custom (.(none)) |
| RESIDENT EVIL2 | GHAE08 | 19 | Capcom |
| Resident Evil 3 | GLEE08 | 16 | Capcom |
| TALES OF SYMPHONIA 2 | GQSEAF | 16 | custom (.bin) |
| TALES OF SYMPHONIA 1 | GQSEAF | 16 | custom (.bin) |
| WWE Day of Reckoning | GWPE78 | 14 | THQ |
| CITY RACER | GRQE41 | 12 | Ubisoft |
| Swingerz Golf | GWGE4F | 12 | custom (.slz) |
| Crash Bandicoot:The Wrath of Cortex | GCBE7D | 10 | custom (.ani) |
| Viewtiful Joe | GVJE08 | 10 | Capcom |
| Tom Clancy's Rainbow Six Lockdown | GLQE41 | 9 | Ubisoft |
| WRESTLEMANIA XIX | GW9E78 | 9 | THQ |
| XIII | GX3E41 | 8 | Ubisoft |
| danceCRAZE | GR4EMZ | 7 | custom (.adp) |
| Jedi Knight II: Jedi Outcast | GJKE52 | 7 | Activision |
| Yu-Gi-Oh! The Falsebound Kingdom | GYFEA4 | 7 | custom (.mrg) |
| PuyoPuyo Fever | GPUE8P | 6 | custom (.bin) |
| GrooveRider | GVRE7H | 5 | custom (.coc) |
| Men In Black II: Alien Escape | GMEE70 | 5 | custom (.spd) |
| MarioGolf Toadstool Tour | GFTE01 | 5 | custom (.(none)) |
| Rocket Power: Beach Bandits | GBQE78 | 5 | THQ |
| Mario Soccer | G4QE01 | 5 | custom (.idsp) |
| GR2GC | GGYE41 | 5 | Ubisoft |
| Baldur's Gate: Dark Alliance | GDEE71 | 4 | custom (.lmp) |
| Bomberman Jetters | GJBE5G | 4 | custom (.dsp) |
| Finding Nemo | GNEE78 | 4 | THQ |
| FIFA Soccer 2005 | GF5E69 | 4 | EA (BIG/VIV) |
| FIFA 06 | GF6E69 | 4 | EA (BIG/VIV) |
| MVP Baseball 2005 | GV4E69 | 4 | EA (BIG/VIV) |
| Resident Evil | GBIE08 | 4 | Capcom |
| PokemonChannelMainDisk | GPAE01 | 4 | Nintendo (DAT) |
| The Sims 2 GameCube | G4ZE69 | 4 | EA |
| Resident Evil | GBIE08 | 4 | Capcom |
| SONIC GEMS COLLECTION | G2XE8P | 4 | Sega (PRS) |
| UEFA Champions League 2004 - 2005 | GUCP69 | 4 | EA (BIG/VIV) |
| Burnout | GBOE51 | 3 | custom (.sgd) |
| Beyond Good and Evil | GGEE41 | 3 | EA (BIG/VIV) |
| DONKEY KONGA | GKGE01 | 3 | custom (.bin) |
| Geist | GITE01 | 3 | custom (.song) |
| PoP:WW | G2OE41 | 3 | EA (BIG/VIV) |
| Spyhunter | GSHE5D | 3 | custom (.pcm) |
| Strike Force Bowling | G5BE4Z | 3 | custom (.fuc) |
| SPEED CHALLENGE - Jacques Villeneuve's Racing Vision | GSZP41 | 3 | Ubisoft |
| TAXI 3 | GXQF41 | 3 | Ubisoft |
| TOM CLANCY'S SPLINTER CELL PANDORA TOMORROW | GT7E41 | 3 | Ubisoft |
| James Bond 007(tm): NightFire(tm) | GO7E69 | 2 | EA (BIG/VIV) |
| 2006 FIFA World Cup | G6FE69 | 2 | EA (BIG/VIV) |
| Jimmy Neutron Boy Genius | GJNE78 | 2 | THQ |
| Batman: Rise of Sin Tzu | GUZE41 | 2 | Ubisoft |
| Barnyard | GYAE78 | 2 | THQ |
| Backyard Baseball | GBKE70 | 2 | custom (.dsp) |
| Batman | GINE69 | 2 | EA |
| Batman: Vengeance | GBVE41 | 2 | Ubisoft |
| Call of Duty 2: Big Red One | GQCE52 | 2 | Activision |
| BIONICLE | GVOE69 | 2 | EA |
| Buffy: Chaos Bleeds | GCQE7D | 2 | custom (.h4m) |
| Butt Ugly Martians Zoom or Doom | GZMP7D | 2 | custom (.ngc) |
| Burnout 2 | GB4E51 | 2 | custom (.bgd) |
| Disney's Donald Duck Goin' Quackers | GDDE41 | 2 | Ubisoft |
| FIFA 07 | G4FE69 | 2 | EA (BIG/VIV) |
| DISNEY'S TARZAN | GTZE41 | 2 | Ubisoft |
| Drome Racers | GD9E69 | 2 | EA |
| EA F12002 | GF2E69 | 2 | EA |
| Freekstyle | GFKE69 | 2 | EA |
| Frogger Beyond | GFGEA4 | 2 | custom (.png) |
| Cars | GKJE78 | 2 | THQ |
| Dragon Ball Z Budokai | GD7E70 | 2 | custom (.adx) |
| STAR SOLDIER | GJSJ18 | 2 | custom (.pak) |
| FIFA Soccer 2004 | GXFE69 | 2 | EA (BIG/VIV) |
| Ice Age 2 The Meltdown | GIAE7D | 2 | custom (.h4m) |
| Gauntlet - Dark Legacy | GUNE5D | 2 | custom (.ngc) |
| The Incredibles 2 | GIQE78 | 2 | THQ |
| Kao the kangaroo | GKOE70 | 2 | custom (.pak) |
| kururin3 | GKQJ01 | 2 | Nintendo (DAT) |
| Hello Kitty Roller Rescue | GH6EAF | 2 | custom (.spd) |
| I-Ninja | GNJEAF | 2 | custom (.psc) |
| The Incredibles | GICE78 | 2 | THQ |
| Knockout Kings 2003 | GKKE69 | 2 | EA (BIG/VIV) |
| Mat Hoffman's Pro BMX 2 | GMHE52 | 2 | Activision |
| The Two Towers | GLOE69 | 2 | EA |
| METAL GEAR SOLID THE TWIN SNAKES | GGSEA4 | 2 | custom (.(none)) |
| METAL GEAR SOLID THE TWIN SNAKES | GGSEA4 | 2 | custom (.(none)) |
| MVP Baseball 2004 | GVPE69 | 2 | EA (BIG/VIV) |
| Nicktoons06 | GU6E78 | 2 | THQ |
| NHL2K3 | G2KE8P | 2 | custom (.pvr) |
| PHANTASY STAR ONLINE EPISODE I&II | GPOE8P | 2 | custom (.rel) |
| Monster Jam: Maximum Destruction | GMJE41 | 2 | Ubisoft |
| Over The Hedge | GH5E52 | 2 | Activision |
| Pitfall: The Lost Expedition | GPHE52 | 2 | Activision |
| PSO CARD BATTLE | GPSE8P | 2 | custom (.png) |
| Prince of Persia The Two Thrones | GKME41 | 2 | EA (BIG/VIV) |
| Nicktoons Unite! | GNOE78 | 2 | THQ |
| PHANTASY STAR ONLINE EPISODE I&II | GPOE8P | 2 | custom (.rel) |
| Prince of Persia : The Sands of Time | GPTE41 | 2 | EA (BIG/VIV) |
| Shark Tale | G9TE52 | 2 | Activision |
| ROBOCOP | GR5J1K | 2 | custom (.dsp) |
| The Sims | GCIE69 | 2 | EA |
| Skies of Arcadia Legends | GEAE8P | 2 | custom (.mld) |
| The Sims: Bustin Out GameCube | G4ME69 | 2 | EA |
| Spirits and Spells | G2PE6U | 2 | custom (.dgc) |
| Spyro: Enter the Dragonfly | GS8E7D | 2 | custom (.ilg) |
| Robots | GZQE7D | 2 | custom (.h4m) |
| Scooby-Doo: Night of 100 Frights | GIHE78 | 2 | THQ |
| Spartan: Total Warrior | GWAE8P | 2 | custom (.bin) |
| Sphinx and the Cursed Mummy | GXPE78 | 2 | THQ |
| SpongeBob SquarePants: Battle for Bikini Bottom | GQPE78 | 2 | THQ |
| The SpongeBob SquarePants Movie | GGVE78 | 2 | THQ |
| The Sims 2 Pets | G4OE69 | 2 | EA |
| Star Wars : The Clone Wars | GSXE64 | 2 | custom (.gct) |
| Spyro | G5SE7D | 2 | custom (.h4m) |
| TMNT:Mutant Melee | GE5EA4 | 2 | custom (.thp) |
| Starsky & Hutch | GT5E7N | 2 | custom (.dsp) |
| Surf's Up | GXUE41 | 2 | Ubisoft |
| SOAF | G3ME41 | 2 | Ubisoft |
| TOM CLANCY'S GHOST RECON | GGRE41 | 2 | Ubisoft |
| Tom Clancy's Splinter Cell | GCEE41 | 2 | Ubisoft |
| Tom Clancy's Splinter Cell Double Agent | GWYE41 | 2 | Ubisoft |
| Tom Clancy's Splinter Cell Chaos Theory | GCJE41 | 2 | Ubisoft |
| RainbowSix3 | G63E41 | 2 | Ubisoft |
| Tom Clancy's Splinter Cell Double Agent | GWYE41 | 2 | Ubisoft |
| TMNT | GYRE41 | 2 | EA (BIG/VIV) |
| Tom Clancy's Splinter Cell Chaos Theory | GCJE41 | 2 | Ubisoft |
| Worms 3D | GWME51 | 2 | custom (.dsp) |
| ZooCube | GZCE51 | 2 | custom (.igb) |
| The Urbz GameCube | GUBE69 | 2 | EA |
| Project Zoo | GWLE6L | 2 | custom (.gmb) |
| Alien Hominid | GAHEGG | 1 | custom (.pak) |
| Jimmy Neutron: Jet Fusion | GJFE78 | 1 | THQ |
| Baten Kaitos | GKBEAF | 1 | custom (.(none)) |
| BIG AIR FREESTYLE | GMRE70 | 1 | custom (.mds) |
| American Chopper 2 | GAPE52 | 1 | Activision |
| Asterix & Obelix XXL | GAGP70 | 1 | custom (.rws) |
| Baten Kaitos Origins | GK4E01 | 1 | custom (.(none)) |
| Baten Kaitos | GKBEAF | 1 | custom (.(none)) |
| Conan disc0 | GC9P6S | 1 | custom (.str) |
| Baten Kaitos Origins | GK4E01 | 1 | custom (.(none)) |
| Battalion Wars | G8WE01 | 1 | custom (.adp) |
| Black & Bruised | G2BE5G | 1 | custom (.rep) |
| CuriousGeorge | G3JEAF | 1 | custom (.loc) |
| Dark Summit | GDSE78 | 1 | THQ |
| Conan disc1 | GC9P6S | 1 | custom (.str) |
| DORAEMON1 | GDAJE5 | 1 | custom (.adp) |
| Ratatouille | GLLE78 | 1 | THQ |
| DEAD TO RIGHTS | GDREAF | 1 | custom (.rar) |
| Die Hard Vendetta | GDIE7D | 1 | custom (.dsq) |
| Disney Sports: Basketball | GDLEA4 | 1 | custom (.bdg) |
| Scream Arena | GMNE78 | 1 | THQ |
| Driven | GDVE6L | 1 | custom (.bmp) |
| DoraTheExplorerJourneyToThePurplePlanet | GQLE9G | 1 | custom (.loc) |
| F1 Career Challenge | GFCP69 | 1 | EA |
| FlushedAway | GLHEG9 | 1 | custom (.loc) |
| King Arthur | GKHEA4 | 1 | custom (.thp) |
| Killer7 Disk1 | GK7E08 | 1 | Capcom |
| spyro06 | G6SE7D | 1 | custom (.thp) |
| Lego GameCube | GL5E4F | 1 | custom (.scp) |
| Largo Winch | GLGP41 | 1 | Ubisoft |
| Madagascar | GGZE52 | 1 | Activision |
| IKARUGA | GIKE70 | 1 | custom (.gvr) |
| Killer7 Disk2 | GK7E08 | 1 | Capcom |
| MLB Slugfest 2003 | GSGE5D | 1 | custom (.dff) |
| Mary-Kate and Ashley: Sweet 16 | GMAE51 | 1 | custom (.lgc) |
| NBA LIVE 2004 | GN8E69 | 1 | EA (BIG/VIV) |
| Minority Report | GMWE52 | 1 | Activision |
| Mortal Kombat Deadly Alliance | GMKE5D | 1 | custom (.ssf) |
| Mortal Kombat Deception | GQNE5D | 1 | custom (.ssf) |
| NBA LIVE 06 | G6NE69 | 1 | EA (BIG/VIV) |
| NBA Live 2003 | GNLE69 | 1 | EA (BIG/VIV) |
| NFS: HP2 | GH2E69 | 1 | EA (BIG/VIV) |
| NFLBlitzPro | GFVE5D | 1 | custom (.h4m) |
| MLB SlugFest 20-04 | GS7E5D | 1 | custom (.dff) |
| Outlaw Golf | GOFE7L | 1 | custom (.sph) |
| Relish Rampage | GPQE6L | 1 | custom (.gmf) |
| King Kong | GWKE41 | 1 | Ubisoft |
| NBA LIVE 2005 | GLYE69 | 1 | EA (BIG/VIV) |
| Piglet's BIG GAME | GPLE9G | 1 | custom (.rws) |
| Power Rangers Dino Thunder | GRUE78 | 1 | THQ |
| ROF | GR9E6L | 1 | custom (.txt) |
| Open Season | GOSE41 | 1 | Ubisoft |
| Rogue Ops | GP9E7F | 1 | custom (.adpcm) |
| Scooby-Doo! Unmasked | G5DE78 | 1 | THQ |
| Shrek 2 | G3RE52 | 1 | Activision |
| The Simpsons Hit & Run | GHQE7D | 1 | custom (.p3d) |
| Scaler | GKUE9G | 1 | custom (.dsp) |
| The Simpsons Road Rage | GSPE69 | 1 | EA |
| SpongeBob SquarePants ROTFD | GSQE78 | 1 | THQ |
| Spider-Man (TM) | GSME52 | 1 | Activision |
| Tetris Worlds | GTRE78 | 1 | THQ |
| Tom and Jerry | GTJE5L | 1 | custom (.gmf) |
| TopAngler | GTAE5S | 1 | custom (.x3g) |
| Ty2 | GYTE69 | 1 | EA |
| WarriorBlade | GBNJC0 | 1 | custom (.dsp) |
| Ty3 | GIZE52 | 1 | Activision |
| Winnie the Pooh | GWHE41 | 1 | Ubisoft |
| TY the Tasmanian Tiger | GTYE69 | 1 | EA |

## Games that produce nothing yet (370)

Walked and manifested without error (disc filesystem, archives), but no format gcrip
knows how to decode. Grouped by the survey's engine guess; each group is a candidate
for a new parser module or the Dolphin capture fork.

| engine / publisher guess | discs | examples |
|---|---:|---|
| EA | 36 | CATWOMAN, Cel Damage, Disney's PARTY, Freedom Fighters |
| EA (BIG/VIV) | 30 | 007: Agent Under Fire (tm), 007: Everything or Nothing, 2002 FIFA World Cup, Def Jam Fight For NY |
| Activision | 30 | BLOODY ROAR(R): PRIMAL FURY, Cabela's Dangerous Hunts 2, Cabela's Outdoor Adventures, Cabela's(R) BGH 2005 Adv. |
| THQ | 22 | Avatar 06, Big Mutha Truckers, Bratz: Forever Diamondz, Bratz: Rock Angelz |
| custom (.bin) | 15 | BATMAN: DARK TOMORROW, Beyblade Super Tournament Battle, Cubic Lode Runner, Dance Dance Revolution: Mario Mix for US |
| custom (.dat) | 15 | CaptainTUBASAGC, Conflict: Desert Storm, Cyber Formula -Road To The EVOLUTION-, NBA2k3 |
| custom (.dsp) | 13 | ATV: Quad Power Racing 2, Chicken Little, Crash Nitro Kart, Dragon Ball Z Sagas |
| custom (.thp) | 11 | Animaniacs, BloodRayne, Freestyle Metal X, Legends of Wrestling 2 |
| Capcom | 11 | CAPCOM VS. SNK 2  EO, GotchaForceUsa, MEGA MAN X COMMAND MISSION, MEGAMAN X COLLECTION |
| custom (.adp) | 8 | Aquaman: Battle for Atlantis, CASPER, Dr. Muto, DreamMixTV WorldFighters |
| custom (.bik) | 7 | Conflict: Desert Storm II, Defender, Freaky Flyers, Freaky Flyers |
| Nintendo (DAT) | 7 | Kirby Air Ride, MARIO SUPERSTAR BASEBALL, Mario Party 5, MarioParty4 |
| custom (.fpk) | 6 | NARUTO CLASH OF NINJA, NARUTO2, NARUTO3, NARUTO4 |
| custom (.h4m) | 6 | BomberManLand2, Cubix Showdown, EVOLUTION SNOWBOARDING, Extreme G3 |
| custom (.afs) | 6 | BLEACH for GC, Digimon World 4, HomeRunKING, MOBILE SUIT GUNDAM GUNDAMvs.ZGUNDAM |
| custom (.hps) | 5 | Croket, GASH FULLPOWER, GASH3, YOUJYOU TAG BATTLE 2 |
| custom (.rel) | 4 | Amazing Island, Evolution Skateboarding, Frogger Ancient Shadow, WINNING ELEVEN 6 FINAL EVOLUTION |
| custom (.str) | 4 | Ed, Edd n Eddy, Happy Feet, Teen Titans, The Ant Bully |
| custom (.tex) | 4 | ASB2004, All-Star Baseball 2002, All-Star Baseball 2003, Crazy Taxi |
| custom (.gcp) | 4 | Bad Boys Miami Takedown, Pac-Man World 3, Taz: Wanted, Zapper |
| custom (.sfd) | 4 | Codename: Kids Next Door, LucasArts Gladius, ONE PIECE GRAND BATTLE, ONE PIECE GRANDBATTLE3 |
| custom (.avi) | 4 | Blitz 20-02, Midway Arcade Treasures, NASCAR(R) Dirt to Daytona, NFL Blitz 20-03 |
| custom (.dol) | 4 | NHL HITZ 20-02, NHL HITZ 20-02, NHL Hitz 2003, NHL Hitz 2004 |
| Ubisoft | 3 | CHARLIE'S ANGELS, Rocky, Worms Blast |
| custom (.pc) | 3 | COCOTO FUNFAIR, COCOTO Kart Racer, COCOTO Platform Jumper |
| custom (.rcf) | 3 | Crash Tag Team Racing, The Hulk, The Incredible Hulk:Ultimate Destruction |
| custom (.pak) | 3 | Micro Machines, Second Sight, Top Gun Combat Zones |
| custom (.bnr) | 3 | NBA2K2, Pinball Hall of Fame, QFC: The Tower of Druaga |
| custom (.wad) | 3 | Scorpion King, Smashing Drive, Spawn |
| custom (.pod) | 2 | 4x4 Evolution 2, Blowout |
| custom (.zit) | 2 | Aggressive Inline, Dave Mirra Freestyle Bmx2 |
| custom (.tpl) | 2 | BEACH SPIKERS, VirtuaStriker2002 |
| custom (.vo) | 2 | Dinotopia: The Sunstone Odyssey, Robotech: Battlecry |
| custom (.rom) | 2 | Disney Sports: Football, Disney Sports: Soccer |
| Nintendo (RARC/U8, non-J3D) | 2 | ChibiRobo!, F-ZERO GX (US Version) |
| custom (.res) | 2 | Digimon Rumble Arena 2, jack |
| custom (.spd) | 2 | FutureTactics, HauntedMansion |
| custom (.mid) | 2 | Donkey Konga 2, Donkey Konga 3 |
| custom (.txt) | 2 | Goblin Commander, Mission: Impossible Operation Surma |
| custom (.hdr) | 2 | Karaoke Revolution Party, Street Racing Syndicate |
| Retro (PAK/CMDL) | 2 | Metroid Prime, Metroid Prime 2 Echoes |
| custom (.(none)) | 2 | MarioPowerTennis, SonicRiders |
| custom (.blt) | 2 | Muppets Party Cruise, Shrek Super Party |
| custom (.fsys) | 2 | POKeMON XD, Pokemon Colosseum |
| Sega (PRS) | 2 | Sonic Adventure 2 Battle, SonicAdventureDX |
| custom (.all) | 1 | 18 Wheeler |
| custom (.pik) | 1 | Army Men Sarge's War |
| custom (.obj) | 1 | BysBase07 |
| custom (.cc2) | 1 | BIONICLE Heroes |
| custom (.lfb) | 1 | Backyard Football |
| custom (.prd) | 1 | BillyHatcher |
| custom (.zal) | 1 | BMX XXX |
| custom (.atx) | 1 | Cubivore |
| custom (.dtk) | 1 | Dakar 2 |
| custom (.cct) | 1 | Narnia GameCube |
| custom (.pal) | 1 | Carmen Sandiego |
| custom (.aob) | 1 | Charlie and The Chocolate Factory |
| custom (.gct) | 1 | Darkened Skye |
| custom (.adx) | 1 | Dragon Ball Z 2 |
| custom (.irx) | 1 | ESPN MLS ExtraTime 2002 |
| custom (.w2d) | 1 | Disney Sports: Skateboarding |
| custom (.cha) | 1 | FINAL FANTASY Crystal Chronicles |
| custom (.bdg) | 1 | Godzilla |
| custom (.jam) | 1 | The Grim Adventures of Billy & Mandy |
| custom (.ggf) | 1 | FireBlade |
| custom (.ast) | 1 | Freestyle Street Soccer |
| custom (.chk) | 1 | ESPN International Winter Sports 2002 |
| custom (.wav) | 1 | Hitman 2: Silent Assassin |
| custom (.hfs) | 1 | Frogger's Adventures The Rescue |
| custom (.xmd) | 1 | Knights of the Temple |
| custom (.rez) | 1 | Intellivision Lives! |
| custom (.iff) | 1 | Major League Baseball 2K6 |
| custom (.bgg) | 1 | Blood Omen 2 |
| custom (.can) | 1 | StarWars Lego 2 |
| custom (.ste) | 1 | Monopoly Party |
| custom (.cat) | 1 | Mark Davis Pro Bass Challenge |
| custom (.cgs) | 1 | Namco Museum(tm) 50th Anniversary |
| custom (.wvs) | 1 | Metal Arms |
| custom (.blo) | 1 | Neighbors from Hell |
| custom (.fbc) | 1 | One Piece Pirates Carnival (us) |
| custom (.cam) | 1 | NBA Courtside 2002 |
| custom (.spch) | 1 | NCAA College Basketball 2K3 |
| custom (.gcx) | 1 | Rally Championship |
| custom (.d4) | 1 | RAVE MASTER |
| custom (.gtd) | 1 | Redcard 20-03 |
| custom (.xgc) | 1 | Pac-Man World Rally |
| custom (.one) | 1 | SHADOW THE HEDGEHOG |
| custom (.gcg) | 1 | Sega Soccer Slam |
| custom (.bsf) | 1 | Rampage: Total Destruction |
| custom (.ssw) | 1 | Serious Sam |
| custom (.har) | 1 | SHIKIGAMI NO SHIRO 2 |
| custom (.bmp) | 1 | SONIC HEROES |
| custom (.pdm) | 1 | SPACE RAIDERS |
| custom (.bog) | 1 | Speed Kings |
| custom (.movie) | 1 | Star Wars: Rogue Leader |
| custom (.lmp) | 1 | Shrek Extra Large |
| custom (.lz) | 1 | Super Monkey Ball |
| custom (.dgc) | 1 | Superman(TM): SoA |
| custom (.vsp) | 1 | Star Wars - Rogue Squadron III - Rebel Strike |
| custom (.be) | 1 | Super Bubble Pop |
| custom (.an2) | 1 | Super Monkey Ball Adventures (TM) |
| custom (.mss) | 1 | TimeSplitters 2 |
| custom (.pck) | 1 | Terminator 3: The Redemption |
| custom (.rar) | 1 | Trigger Man |
| custom (.bnk) | 1 | V-Rally 3 |
| custom (.stm) | 1 | Transworld Surf |
| custom (.ngc) | 1 | Whirl Tour |
| custom (.h) | 1 | WTA Tour Tennis |
| custom (.rbb) | 1 | XGRA |

## Survey engine guesses (whole library)

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
