# Boom Zoo (Taiwan) — Complete ROM Text & Graphics Inventory

Full audit of `Boom Zoo (Taiwan).bin` (Super A'Can, Funtech 1996, 512 KB byteswapped, expanded to 1 MB for relocated compressed assets). All graphics and tilemaps use the `$002B22` `$D222`-family LZSS+Huffman/RLE compressor (`0xF0` raw, `0xF1` RLE, `0xF3`/`0xF4` LZ+Huffman with tables at `0x002F9C` and `0x002E2A`). Unlike Sango Fighter, Boom Zoo contains **zero ASCII/Big5 script text strings** for gameplay UI; every piece of Chinese UI text is baked into 4bpp BG tilemaps or sprite frames.

---

## 1. Localized Chinese Blocks (7 Targets, Zero Overlap)

| # | Screen / Asset | Gfx Offset | Map Offset | LUT / OAM / Spawn Refs | Palette / Style | Original (ZH) | Localized (EN) |
|---|---|---|---|---|---|---|---|
| 1a | Title Subtitle (`fid=19..22`) | `0x025EF6` (527t) | `0x01EC78` | LUT `0x01EC28`; OAM `0x01B350..0x01B368`; State 0 `0x00C870..0x00C8C0` | Pal 0 (`fg=2`, drop shadow `14`) | `爆爆動物園` | `"BOOM"` + `"BOOM"` + `"ZOO"` (`fid=19,19,20`) |
| 1b | Title Menu (`fid=23..28`) | `0x025EF6` (527t) | `0x01EC78` | OAM `0x01B370..0x01B398` (`4x2 -> 8x2`); State 0 `0x00C8D4..0x00C994` | Pal 3 (`13` blue) / Pal 4 (`13` cyan blink) | `開始` / `挑戰` / `接關` | `"1P GAME"` / `"VS MODE"` / `"PASSWORD"` |
| 2 | 1P Character Select BG | `0x043CA6` (64t) | `0x043B90` | Gfx ptr `0x0097B6`; Map ptr `0x0097D6` (`r=7..9, c=8..23`) | Pal 13 (`fg=14`, `outline=1` on wood `0x22`; `r=9` flowers restored) | `角色選擇` | `"SELECT FIGHTER"` |
| 3 | Gameplay HUD Sprites | `0x024C9C` (247t) | `0x01E868` | LUT `0x01E7F6` (`fid=200..254`); 44 Gfx ptrs `0x023516..0x023D4E`; 44 Map ptrs `0x01D2F8..0x01E462`; OAM `0x01B0E8..0x01B170` | Pal 13: `fg=4` (`237..238`), gold bevel `6/10/8` (`239..247`), white blink bevel `6/4/13` (`249..253`), original `!` (`248`, `254`) preserved | `快加入!!` / `按START` / `遊戲暫停!` / `時間快到了!` | `"JOIN IN!"` / `"PUSH START"` / `"PAUSED!"` / `"HURRY UP!"` |
| 4 | Continue Speech Bubble | `0x03B3DC` (48t) | `0x022862` | LUT `0x022850` (`fid=6`); Gfx ptr `0x02351E`; Map ptr `0x01D304`; OAM `0x01CEC8` (`8x9`); cursor `0x00DB70`/`0x00DB94` | Pal 13 (`fill=15`, slate-blue text `14`, border `2`) | `接關？` / `不要` / `要` | `"CONTINUE?"` / `"NO"` / `"YES"` |
| 5 | VS Setup BG | `0x049ACC` (125t) | `0x04A076` | Gfx ptr `0x00B27E`; Map ptr `0x00B29E` (`r=5..7`, `12..14`, `20..22`) | Pal 13 (`bg=0, fill=1, outline=2, top=4`) | `挑戰人數` / `選擇角色` / `回合制` | `"PLAYERS"` / `"CHARACTERS"` / `"ROUNDS"` |
| 6 | VS Stage Select Sprite | `0x03E5CE` (127t) | `0x023184` | LUT `0x023158` (`fid=0`); Gfx ptr `0x023536`; Map ptr `0x01D320`; OAM `0x01CFC0` (`16x3`) | Pal 13 (`bg=0, fill=1, outline=2, top=4`, `<= 104px` to clear digit) | `選擇場地` | `"SELECT STAGE"` |
| 7 | VS Results BG | `0x04A1CA` (65t) | `0x04A4FA` | Gfx ptrs `0x00B814`, `0x00B92A`; Map ptr `0x00B834` (`r=4..6, c=11..21`) | Pal 13 (`bg=9` beige `0xD025`, `fill=1, outline=2, top=4`); `0x04A5B2` untouched | `成績單` | `"RESULTS"` |

---

## 2. Already-English & Intentionally Preserved Content

- **Intro Cutscene (`0x416E6`, `0x41F76`, `0x4201A`)**: All sound/explosion typography (`BOOOO OO ON !!!!`, etc.) is already in English. Zero Chinese text.
- **Title Screen BG (`0x421B2`, `0x436E2`, `0x43294`, `0x43588`, `0x4364C`)**: Contains only the `BOOM ZOO` logo, spinning porthole beach ball, and `© 1996 FUNTECH ALL RIGHTS RESERVED.` Zero Chinese text.
- **Password Entry (`0x48DC6`, `0x491C2`, `0x4922A`)**: Header (`PASSWORD`) and UI are already in English.
- **Game Over Screen**: Already in English (`GAME OVER`).
- **VS Match Winner (`0x4A1CA`, `0x4A5B2`)**: Header (`VICTOR!`) is already in English; preserved alongside localized `RESULTS`.
- **Ending Credits (`State 1`, `0x1F084`, `0x1F0BC`, `0x3F89C`)**: Role headers (`DESIGNED BY`, `GRAPHIC DESIGN`, `MUSIC`, `SOUND EFFECT`, `GNEST`, `PROGRAM`) are already in English. Adjacent brush signatures (`劉安書`, `許銘凱`, `周良燦`, `楊博欽`, etc.) and the developer portrait (`fid=19`) are personal autographs and are intentionally preserved unmodified.
