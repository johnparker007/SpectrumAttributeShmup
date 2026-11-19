# Editing the artwork

The playable build reads these files on every build.

| File | Purpose |
| --- | --- |
| `gfx/tileSet.png` | Background sheet, 128 by 64 pixels, with 128 tiles of 8 by 8 dots |
| `gfx/tileSet.xcf` | Imported GIMP master, export changes to `tileSet.png` |
| `sprites/player.png` | Player ship, 5 by 5 dots |
| `sprites/enemy_green_sine.png` | Green sine flier, 5 by 5 dots |
| `sprites/enemy_yellow_z.png` | Yellow retreating flier, 5 by 5 dots |
| `sprites/explosion_1.png` through `explosion_3.png` | Shared three-frame explosion, 5 by 5 dots per frame |
| `maps/level.tmx` | Test map 1 for Tiled, 256 by 6 tiles |
| `maps/level-2.tmx` | Test map 2 for Tiled, 256 by 6 tiles |
| `maps/level-3.tmx` through `level-8.tmx` | Test maps 3–8 for Tiled, 256 by 6 tiles |
| `maps/tileSet.tsx` | Tiled tileset linked to `gfx/tileSet.png` |
| `maps/destructible.tsx` | Tiled tileset for the destructible target and its explosion |
| `gfx/destructible.png` | Four 8×8 tiles laid out as the intact target followed by three explosion frames |
| `gfx/blokius-logo.pbm` | Main menu wordmark, 224 by 32 screen pixels, white on black. Export as binary PBM |
| `fonts/Blokius-Arcade-8.bdf` | Editable 8×8 source for the menu, HUD and GAME OVER lettering |

Each PNG pixel represents one engine dot, displayed as a 4 by 4 pixel block on the Spectrum. Use the eight Spectrum colours at full RGB intensity. Keep sprites at 5 by 5 pixels and use transparent pixels around their shapes. The small-sprite converter supplies both horizontal alignments. Ship collision boxes stay 5 by 5 dots.

The tile animation sequences are defined in the archived engine's `data.asm`. The imported sheet preserves their existing tile positions, including the preshifted parallax frames. Keep tiles in their existing slots when changing their artwork. Save the Tiled map with CSV layer data and fill every cell with a tile.

Levels 1 and 8 contain destructible scenery for playtesting. Paint the first tile from **Destructible Scenery** on the normal scenery layer. The build reserves engine tile IDs 124–127 for this atlas and places a blank after the third explosion frame.

Blokius Arcade 8 adapts ASCII 32–95 from Cody “CodeMan38” Boisclair’s Press Start 2P. Every glyph cell starts with a blank scanline to separate the HUD lettering from the playfield. The comma and underscore already used the bottom row, so they retain their placement. The build packs the 64 cells into 512 bytes. [Pinned bitmap source](https://github.com/googlefonts/googlefontdirectory-hg/blob/52f780bc9d197280a9f430574e179a5f233c56b6/ofl/pressstart2p/src/PressStart2P-8.bdf) · [SIL Open Font License](fonts/OFL.txt)

## Build

Double-click `Build-TAP.bat` in the repository root to rebuild `build/game.tap` with the 50 Hz logo and cyan copper menu text. It uses `SJASMPLUS` if set, then searches PATH, then tries John's existing Desktop installation. The window stays open to show the result or any errors.

From the repository root, using your installed SjASMPlus executable:

```powershell
python tools/build_game.py --assembler "C:/path/to/sjasmplus.exe"
```

The playable TAP is written to `build/game.tap`. Graphics are converted automatically. To inspect the converted graphics on their own, run `python tools/build_art.py`. Converted files appear in `build/art`.

The build compresses all eight maps with the bundled ZX0 tool. Press **1–8** on the title screen to choose a level. Enter during gameplay restarts that level. Each difficulty uses the same green sine artwork.

The original Windows sprite and tile converters are included in `gfx`. Python 3 and Windows are required for this conversion workflow. The game build also needs SjASMPlus. The headless verifier additionally needs ZEsarUX.

The gameplay verifier uses solid-colour reference sprites in `tests/fixtures/sprites` for its visual checks. All playable TAPs use your edits in `art/sprites`.

## Imported originals

The active sheet comes from the archived WIP used by the timing baseline. Your loose Dropbox sheet differed, so it is preserved in `original/working-folder-tileSet.png`. The corresponding loose Tiled map is saved alongside it.

The archived Tiled and CSV sources differed from the compiled map used by the game. `maps/level.tmx` was reconstructed from that compiled map to preserve the current scenery exactly. The archived sources and compiled map are retained in `original`.

The complete reference archive at `vendor/blokius-wip1.zip` includes the prototype's sprite sheets and converter batch file. Builds extract the archive into a temporary directory, verify the original build, then apply the current game code and convert the artwork above.
