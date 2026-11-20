# Editing the artwork

The playable build reads these files on every build.

| File | Purpose |
| --- | --- |
| `gfx/tileSet.png` | Background sheet, 128 by 64 pixels, with 128 tiles of 8 by 8 dots |
| `sprites/player.png` | 5×5 player ship and source for the monochrome HUD life icon. Enclosed cyan cockpit dots appear as cut-outs in the icon. |
| `sprites/enemy_green_sine.png`, then `enemy_green_sine_2.png` through `_4.png` | Green sine flier folding and extending its fins |
| `sprites/enemy_yellow_z.png`, then `enemy_yellow_z_2.png` through `_4.png` | Yellow Z flier with a spinning cyan core |
| `sprites/enemy_<name>.png`, then `enemy_<name>_2.png` through `_4.png` | Four editable flight poses for each of the fourteen additional ships |
| `sprites/explosion_1.png` through `explosion_3.png` | Shared three-frame explosion, 5 by 5 dots per frame |
| `maps/level.tmx` through `maps/level-9.tmx` | Nine 256 × 6 maps. Each layer carries the sector name |
| `maps/tileSet.tsx` | Tiled scenery palette with previews of the extractor and pump animations |
| `maps/destructible.tsx` | Four shootable deck fixtures marked for painting in Tiled |
| `gfx/destructible.png` | Four intact fixtures followed by their three shared explosion frames |
| `gfx/blokius-logo.svg` | Editable vector master for the Interceptor Rounded menu logo |
| `gfx/blokius-logo.pbm` | Baked 224×32 monochrome logo used by the TAP build |
| `fonts/Blokius-Arcade-8.bdf` | Editable 8×8 source for the menu, HUD and GAME OVER lettering |

Each PNG pixel represents one engine dot, displayed as a 4 by 4 pixel block on the Spectrum. Use the eight Spectrum colours at full RGB intensity. Keep sprites at 5 by 5 pixels and use transparent pixels around their shapes. The small-sprite converter supplies both horizontal alignments. Each enemy keeps its 5 by 5 collision box throughout its flight loop.

Each enemy has a four-pose flight loop. Edit the unsuffixed PNG for the spawn pose and the three numbered PNGs for the following poses. Each pose lasts four gameplay ticks (160 ms). Double-click `Build-TAP.bat` to rebuild the game after editing.

### Scenery

Paint sky with tile 0. The eight moving blue stars can appear anywhere this tile is visible. Tile numbers here are zero-based, as in the Tiled tile inspector. Tiles 64–79 supply the two rows of star positions and are reserved for the renderer.

Paint tile 3 for an animated pump. Stamp the extractor as a 2 × 2 block with tiles 12 and 13 above 28 and 29. Both animations share the existing tile pointer updates. Sections with open sky, trusses, transmitters and radiator wings alternate with solid decks, asteroid ridges and industrial bays.

Paint shootable objects **inside a deck** using the first four tiles from **Destructible Scenery**. Their blue backing matches hull plate 1. Tile 104 shows the plate with a black crater and red embers. The build fills every black dot in the three explosion frames with the corresponding dot from tile 104, so the deck shows through the blast and the crater stays when it clears.

The PNGs and TMX files are the editable masters. Save maps with one CSV tile layer and fill every cell. The optional command `python tools/compose_scenery.py build/map-drafts` generates fresh copies of the original nine layouts in a separate folder. Normal TAP builds read your Tiled edits directly.

With ImageMagick on PATH, `python tools/preview_scenery.py build/routes.png` draws all nine complete routes. Add `--column 32` to compare one game-sized viewport from each map at that column. These previews show the scenery layer at rest.

Blokius Arcade 8 adapts ASCII 32–95 from Cody “CodeMan38” Boisclair’s Press Start 2P. Every glyph cell starts with a blank scanline to separate the HUD lettering from the playfield. The comma and underscore already used the bottom row, so they retain their placement. The build packs the 64 cells into 512 bytes. [Pinned bitmap source](https://github.com/googlefonts/googlefontdirectory-hg/blob/52f780bc9d197280a9f430574e179a5f233c56b6/ofl/pressstart2p/src/PressStart2P-8.bdf) · [SIL Open Font License](fonts/OFL.txt)

## Build

After editing the logo SVG, export it at 896×128, then box-filter to 224×32 and threshold at 50% to reproduce the one-bit edges. From the repository root with Inkscape and ImageMagick on PATH:

```powershell
New-Item -ItemType Directory -Force build | Out-Null
inkscape art/gfx/blokius-logo.svg --export-width=896 --export-height=128 --export-filename=build/blokius-logo.png
magick build/blokius-logo.png -colorspace Gray -filter Box -resize 224x32! -threshold 50% art/gfx/blokius-logo.pbm
```

Double-click `Build-TAP.bat` in the repository root to rebuild `build/game.tap` with the 50 Hz logo and cyan copper menu text. It uses `SJASMPLUS` if set, then searches PATH, then tries John's existing Desktop installation. The window stays open to show the result or any errors.

From the repository root, using your installed SjASMPlus executable:

```powershell
python tools/build_game.py --assembler "C:/path/to/sjasmplus.exe"
```

The playable TAP is written to `build/game.tap`. Graphics are converted automatically. To inspect the converted graphics on their own, run `python tools/build_art.py`. Converted files appear in `build/art`.

The build compresses all nine maps and each ship's four poses with ZX0. Press **1–9** on the title screen to choose a level. GET READY expands only the ships on that level's roster. All difficulty settings for a ship share its PNGs. The roster and flight profiles are in [enemy_catalog.py](../tools/enemy_catalog.py).

The original Windows sprite and tile converters are included in `gfx`. Python 3 and Windows are required for this conversion workflow. The game build also needs SjASMPlus. The headless verifier additionally needs ZEsarUX.

The gameplay verifier uses solid-colour reference sprites in `tests/fixtures/sprites` for its visual checks. All playable TAPs use your edits in `art/sprites`.

## Imported originals

The prototype GIMP sheet is archived in `original/prototype-tileSet.xcf`. The loose Dropbox sheet and map, the archived Tiled and CSV sources, and the original compiled map are also in `original`.

The complete reference archive at `vendor/blokius-wip1.zip` includes the prototype's sprite sheets and converter batch file. Builds extract the archive into a temporary directory, verify the original build, then apply the current game code and convert the artwork above.
