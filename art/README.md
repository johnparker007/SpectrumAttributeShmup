# Editing the artwork

The playable build reads these files on every build.

| File | Purpose |
| --- | --- |
| `gfx/tileSet.png` | Background sheet, 128 by 64 pixels, with 128 tiles of 8 by 8 dots |
| `gfx/tileSet.xcf` | Imported GIMP master, export changes to `tileSet.png` |
| `sprites/player.png` | Player ship, 5 by 5 dots |
| `sprites/enemy.png` | Enemy ship, 5 by 5 dots |
| `sprites/explosion_1.png` through `explosion_3.png` | Shared three-frame explosion, 5 by 5 dots per frame |
| `maps/level.tmx` | Test map 1 for Tiled, 256 by 6 tiles |
| `maps/level-2.tmx` | Test map 2 for Tiled, 256 by 6 tiles |
| `maps/tileSet.tsx` | Tiled tileset linked to `gfx/tileSet.png` |

Each PNG pixel represents one engine dot, displayed as a 4 by 4 pixel block on the Spectrum. Use the eight Spectrum colours at full RGB intensity. Keep sprites at 5 by 5 pixels and use transparent pixels around their shapes. The small-sprite converter supplies both horizontal alignments. Ship collision boxes stay 5 by 5 dots.

The tile animation sequences are defined in the archived engine's `data.asm`. The imported sheet preserves their existing tile positions, including the preshifted parallax frames. Keep tiles in their existing slots when changing their artwork. Save the Tiled map with CSV layer data and fill every cell with a tile.

## Build

Double-click `Build-TAP.bat` in the repository root to rebuild `build/game.tap`. It uses `SJASMPLUS` if set, then searches PATH, then tries John's existing Desktop installation. The window stays open to show the result or any errors.

From the repository root, using your installed SjASMPlus executable:

```powershell
python tools/build_game.py --assembler "C:/path/to/sjasmplus.exe"
```

The playable TAP is written to `build/game.tap`. Graphics are converted automatically. To inspect just the converted graphics, run `python tools/build_art.py` or double-click `art/_BUILD_ALL.bat`. Converted files appear in `build/art`.

The build compresses both maps with the bundled ZX0 tool. Choose either map with the number keys on the title screen. Enter during gameplay restarts the selected map.

The original Windows sprite and tile converters are included in `gfx`. Python 3 and Windows are required for this conversion workflow. The game build also needs SjASMPlus. The headless verifier additionally needs ZEsarUX.

## Imported originals

The active sheet comes from the archived WIP used by the timing baseline. Your loose Dropbox sheet differed, so it is preserved in `original/working-folder-tileSet.png`. The corresponding loose Tiled map is saved alongside it.

The archived Tiled and CSV sources differed from the compiled map used by the game. `maps/level.tmx` was reconstructed from that compiled map to preserve the current scenery exactly. The archived sources and compiled map are retained in `original`.

`gfx/sprite.png`, `gfx/spriteSmall.png` and `gfx/_BUILD_ALL.bat` preserve the old prototype's sprite sheets and conversion commands. The playable game's current ship and explosion images are in `sprites`.

The complete 1 MB reference archive is included at `vendor/blokius-wip1.zip`. Builds extract its engine into a temporary directory, verify the original build, then apply the current game code and convert the artwork above.
