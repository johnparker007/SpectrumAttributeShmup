# Playable barrel-scroll build

Choose **K** for Keyboard, **J** for Kempston or **S** for Sinclair on the title screen before choosing a level. Keyboard is selected when the TAP loads. Sinclair uses player 1, the port mapped to **6–0**. **Enter** restarts the level in every control mode.

Press **R** on the title screen to assign Left, Right, Up, Down and Fire. Use five different letter, number or Space keys. **M** is reserved for the GAME OVER menu shortcut. **Enter** cancels an unfinished definition. A completed definition selects Keyboard. The keyboard bindings are kept until the TAP is reloaded or the keys are redefined again.

On the keyboard, use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. The ship can touch the left edge, and its right edge stops three quarters of the way across the playfield. Hold fire to launch a pair of parallel cyan-and-white shots every four game ticks while a slot is free, with up to five pairs in flight. Each shot has cyan on the left and white on the right. The two shots share an X coordinate, leave three empty rows between them and move three dots per tick.

Green sine fliers enter beyond the right edge and move left one logical dot every other game tick. The renderer clips them as they exit on the left. Each green wave has seven ships, with at least ten ticks between spawns. The mirrored paths span all 41 dots of vertical ship travel, with the first visible column aligned to the top or bottom edge. An Enter restart flips the first wave’s entrance. The build bakes both paths as absolute Y coordinates indexed by X.

The scenery and tile animation tables advance every other game tick. The eight preshifted parallax frames each stay visible for four game ticks. The other four animated tiles use the same frame duration.

The level loader selects the firing column and baked bullet speed during **GET READY**. Each armed flier gets one shot when it crosses that column. The shot uses the closest of 32 bearings towards the player, or points left while the player is absent. Slow trajectories average about two thirds of the original speed. Each in-flight shot uses the same three-byte record and reads X and Y deltas from the selected pair of 256-byte tables.

| Level | Green flier firing |
| --- | --- |
| 1–2 | Unarmed |
| 3 and 5 | One slow shot, five dots inside the playfield |
| 4 | One slow shot on entry |
| 6–8 | One shot on entry at the original speed |

From level 4, each green wave alternates with a separate wave of seven yellow fliers. Yellow ships enter five ticks apart when an enemy slot is free. Levels 4 and 5 leave enough time for the previous wave to clear. Levels 6–9 shorten the gaps so waves can overlap. Two full waves and the player use fifteen of the sixteen sprite slots.

Yellow fliers enter at varied heights and travel straight left at one dot per game tick. Around 60% across the playfield, each flier captures the player's Y position. It then retreats right at two dots per tick for twelve ticks, using a prebaked path that reaches the captured height at the end of the retreat. It resumes flying left at one dot per tick.

| Level | Yellow flier firing |
| --- | --- |
| 4–5 | Unarmed |
| 6 | One aimed shot at the end of the retreat |
| 7–8 | An aimed shot halfway through the retreat and another at its end |

All enemies on a level share the same 32 prebaked bullet directions and speed. The yellow fliers first shoot on level 6, which uses the faster paths. Up to 24 enemy bullets can be active at once. They alternate yellow and white on successive 25 Hz gameplay ticks.

Either player shot destroys an opponent in one hit and retires its whole pair before the next enemy is checked. A pair also retires at the right edge. A bullet destroys a vulnerable player ship, and a ram destroys both the vulnerable player and the enemy it hits. Both sides use 5×5 hitboxes and play a three-frame explosion over six game ticks. Their hitboxes disappear as soon as the explosion starts. You start with three lives. After a loss, the next ship appears at the starting position after 12 game ticks (0.48 seconds) and stays invincible for 75 game ticks (three seconds). Every other 25 Hz game frame hides the ship during invincibility. Protected contact is harmless to both ships. Movement and firing work on both blink phases after the spawn frame.

After the last ship is destroyed, **GAME OVER**, **ENTER TO RESTART** and **M TO MAIN MENU** appear in a centred panel. The HUD keeps the final score visible. The score freezes even if a shot already in flight reaches an opponent. Enter clears the panel, projectile pools, hit flags and score, restores three lives and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart, with gameplay music continuing through the reset. Press **M** to return to the level menu with your selected controls and hear Meadows Edge from the start.

The bottom HUD shows the level on the left, spare ships across the middle, and the right-aligned score at the far right. You start with one active ship and two spare icons. An empty strip means you are flying your last ship. Each enemy scores 100 points. The first bonus ship comes at 20,000, followed by another every 50,000 points (70,000, 120,000 and so on). All 22 possible spares fit beside a six-digit score and a two-digit level. The playfield is 46 logical rows high.

Each of the first 18 ships gets a full character of width. Each extra life packs four ships into three cells at the right of the strip. Losing that life restores the wider spacing in those cells. A life change redraws only the affected cells.

The score starts at `0`. The units zero is drawn at startup and the tens zero changes only when the score crosses between zero and a positive value. Each Frame 2 selects one changed cell or copies two scanlines of an already selected cell to both bitmap banks.

Frame 1 draws the first tile of the bottom tile row during the former HUD attribute-copy interval. Shifted tiles merge shared edge bytes in left-to-right order. The last tile pass omits the two hidden logical rows and skips the display swap inside the HUD. The fixed-time collision slots keep their original schedule and read eight inactive reserve records behind the 24 live projectile slots.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the projectile positions against ship hitboxes and retire spent pairs using the stock paging schedule. After sprite composition, the second game slot checks for ship contact and expands each paired record into two shots for plotting. Enemy bullets and rams check the middle three columns and all five rows of the player ship. The attribute buffer holds the colours for drawing. Inactive shots skip the buffer write. The banked 50 Hz AY player plays the 25.6-second Star Force loop on A and B. Channel C plays the player-shot tone and enemy-explosion noise.

## Reproduce

Press the keyboard Fire key (Space by default), Kempston fire or Sinclair fire (**0**) to start Level 1 with that controller. A held fire button must be released when returning to the menu. **1–9** start a test map with the current controller. Press **R** to redefine keys. Sinclair fire takes priority over its direction keys on the same keyboard row. The test maps share a tile sheet. Level 9 adds destructible scenery and shortens the gap between green and yellow waves. The ready screen displays the selected level while ZX0 Standard expands its map into the 1,536-byte buffer. The renderer stays idle until gameplay starts. The loader uses logical bank 1 for compressed maps and restores bank 0 before configuring the wave.

| Map | Packed bytes | 128K family unpack T-states | +2A unpack T-states |
| --- | ---: | ---: | ---: |
| 1 | 463 | 142,338 | 147,434 |
| 2 | 477 | 142,980 | 148,038 |
| 3 | 457 | 139,939 | 145,270 |
| 4 | 463 | 140,528 | 145,750 |
| 5 | 443 | 138,895 | 143,914 |
| 6 | 452 | 140,561 | 145,957 |
| 7 | 466 | 142,336 | 147,389 |
| 8 | 465 | 143,157 | 148,265 |
| 9 | 485 | 144,624 (+2) | 149,625 |

`tools/verify_level_menu.py` takes the same assembler, emulator and optional TAP output arguments as the gameplay verifier. It checks all nine level keys on both models, screen text, sample map data, bank restoration, renderer startup, wave entrances, the yellow retreat and firing stages, and green shot aiming and speed. It also checks at least 150 consecutive gameplay frame pairs after each choice. Measurements include the call to ZX0 and exclude the ready screen delay and level setup.

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --output-tap <playable.tap>
```

The default build uses the packed Star Force assets in `game/music`. To audition an alternate tune, pass `--phrase-reference <full-reference.json>` with a full-song capture from `benchmark_ay.py --through-loop`. The gameplay regression uses the prototype waves and solid-colour artwork to retain its scripted collision scenarios. The exported keyboard-controlled TAP uses the current artwork and level waves. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the moving formations, a restart while alive, and a restart after losing all lives. The first 36 game ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The bottom HUD test (`tools/verify_bottom_score.py`) compares every pixel in both bitmap banks across score carries, bonus awards, a life loss, resets, the score cap and one- and two-digit level labels. The older prototype replay separately checks the original six-digit display and its two fixed trailing zeroes.

The prototype replay checks 1,630 HUD frames and expects 64 life-icon row updates and 168 score row updates per bitmap bank. Each row update takes 235 T-states, including the call, while an idle call takes 72. The prototype's in-playfield attribute strip takes 340 T-states per game tick.

The idle run checks two full respawns, alternating draw coordinates across all 75 protected game frames each time, overlap without life loss during protection, and game over on the third hit. It also checks all 12 enemy draw positions and hitboxes in a full formation before and after game over. A separate trace verifies the coordinates and visible pixels of a ship exiting on the left. The gameplay trace checks mutual destruction from rams, protected ship contact and ten simultaneous player shots. It also compares player and enemy explosion artwork with the expected frame sequence. Assembly probes verify all 32 aimed bearings, two angle boundaries and paired-shot retirement when either shot hits.

The main replay ends a run with a nonzero score. The trace checks that the final score stays fixed and that the 16 bitmap rows of the game-over panel are installed and restored incrementally. Headless video checks both lines and the final score together, followed by a cleared panel and reset HUD after Enter.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs checked against stock paging | ≥815 | ≥815 |
| Keyboard-build frame pairs checked against stock paging | ≥256 | ≥256 |
| Minimum Frame 1 margin across the 815-tick replay | 1,526 T-states | 1,479 T-states |
| Minimum Frame 2 margin across the 815-tick replay | 2,933 T-states | 2,934 T-states |
| Visible enemy ships checked together | 12 | 12 |
| Player shots verified in flight together | 10 | 10 |
| Enemy shots checked at emission | 78 | 78 |
| Aimed three-way spreads checked | 17 | 17 |
| AY ticks checked through the full tune, loop and first restart | 1,312 | 1,312 |
| AY ticks with both sound effects active | 202 | 202 |

The 815-tick replay includes two restarts. Headless video checks magenta ships, cyan-and-white player shots at both horizontal alignments, yellow enemy shots and white explosion sprites.
