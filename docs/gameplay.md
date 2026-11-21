# Playable barrel-scroll build

Choose **K** for Keyboard, **J** for Kempston or **S** for Sinclair on the title screen before choosing a level. Keyboard is selected when the TAP loads. Sinclair uses player 1, the port mapped to **6–0**. **Enter** restarts the level in every control mode.

Press **R** on the title screen to assign Left, Right, Up, Down and Fire. Use five different letter, number or Space keys. **M** is reserved for the GAME OVER menu shortcut. **Enter** cancels an unfinished definition. A completed definition selects Keyboard. The keyboard bindings are kept until the TAP is reloaded or the keys are redefined again.

On the keyboard, use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. The ship can touch the left edge, and its right edge stops three quarters of the way across the playfield. Hold fire to launch a pair of parallel cyan-and-white shots every four game ticks while a slot is free, with up to five pairs in flight. Each shot has cyan on the left and white on the right. The two shots share an X coordinate, leave three empty rows between them and move three dots per tick.

Green sine fliers enter beyond the right edge and move left one logical dot every other game tick. The renderer clips them as they exit on the left. Each green wave has seven ships, with at least ten ticks between spawns. The mirrored paths span all 41 dots of vertical ship travel, with the first visible column aligned to the top or bottom edge. An Enter restart flips the first wave’s entrance. The build bakes both paths as absolute Y coordinates indexed by X.

The scenery and tile animation tables advance every other game tick. Each pose of the winding drum, scanner or rotor lasts four game ticks (160 ms). The four quadrants of the common extractor use the same frame duration. Eight blue stars move at two speeds behind sky tiles.

At the end of each map, the current seven-ship wave finishes spawning. Once the last flier has left or finished exploding, a 10×10 boss enters from the right and patrols vertically. Its four 5×5 quarters share one health pool. The centre shot of each volley aims at the player and neighbouring shots are one of the 32 bearings apart.

| Levels | Hits to destroy the boss | Shots per volley | Time between volleys by level |
| --- | --- | --- | --- |
| 1–3 | 8, 10, 12 | 1 | 1.44, 1.28, 1.12 seconds |
| 4–6 | 14, 16, 18 | 3 | 1.28, 1.12, 0.96 seconds |
| 7–9 | 20, 22, 24 | 5 | 0.96, 0.80, 0.64 seconds |

Destroying the boss clears the enemy bullets and awards 1,000 points. Score and surviving ships carry into the next sector. Clearing level 9 shows the final score and **ALL SECTORS CLEAR** before returning to the title. To export a playtest TAP starting near the end of each sector, run `tools/verify_boss.py --game <assembled-game-directory> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --trial-tap <output.tap>`.

The level loader selects the green flier's firing column and the level's bullet speed during **GET READY**. Each armed green flier gets one shot when it crosses that column. The shot uses the closest of 32 bearings towards the player, or points left while the player is absent. Slow trajectories average about two thirds of the original speed. Each in-flight shot uses the same three-byte record and reads X and Y deltas from the selected pair of 256-byte tables.

| Level | Green flier firing |
| --- | --- |
| 1–5 | One slow aimed shot on entry |
| 6–9 | One shot on entry at the original speed |

Every wave contains seven ships of one type. On a fresh start, level 1 opens with Green Sine, Yellow Z, Cobalt Skimmer and Ivory Stair in that order. Each level has three wave orders. A new attempt advances to the next order, which repeats during that run. Level 2 opens with Scarlet Hook and level 3 with Amber Kite on the first visit. On level 9 the opening pairs are Polar Wraith / Azure Hopper, Ruby Crown / Silver Splitter and Green Sine / Yellow Z.

Levels 1–5 give every resident type one wave per rotation. From level 6 selected later types get a second wave. On level 1 the next formation can begin three ticks (120 ms) after the seventh ship enters. Within a formation, green ships enter ten ticks apart and yellow ships five ticks apart. When a sprite slot is busy the next entrant waits. Two full waves and the player use fifteen of the sixteen sprite slots.

| Level | Resident types alongside Green Sine and Yellow Z | Total |
| --- | --- | ---: |
| 1 | Cobalt Skimmer, Ivory Stair | 4 |
| 2 | Cobalt Skimmer, Scarlet Hook | 4 |
| 3 | Cobalt Skimmer, Scarlet Hook, Ivory Stair, Amber Kite | 6 |
| 4 | Ivory Stair, Amber Kite, Violet Needle, Mint Manta | 6 |
| 5 | Violet Needle, Mint Manta, Copper Drill, Azure Hopper | 6 |
| 6 | Copper Drill, Azure Hopper, Rose Claw, Jade Pendulum | 6 |
| 7 | Amber Kite, Rose Claw, Jade Pendulum, Silver Splitter, Crimson Comet | 7 |
| 8 | Copper Drill, Jade Pendulum, Silver Splitter, Crimson Comet, Rose Claw, Polar Wraith | 8 |
| 9 | Azure Hopper, Jade Pendulum, Silver Splitter, Crimson Comet, Polar Wraith, Ruby Crown | 8 |

Each of the fourteen additional waves uses seven entry heights. Cobalt Skimmers fly straight across in evenly spaced lanes. Scarlet Hooks enter from alternating edges and turn back towards their starting height. Azure Hoppers accelerate through two parts of a double hop, and Silver Splitters break inward after a long straight approach. Each completed green wave flips the vertical orientation for subsequent formations.

On level 1 the Skimmer and Stair each take a single slow aimed shot near the right edge. Yellow Z fires at the end of its retreat. Amber Kite first appears on level 3 with two firing positions, sits out levels 5 and 6, and returns on level 7 with six firing positions in the volley cycle.

The additional fliers mix aimed shots with fixed bearings that mirror their flight path. From level 4 they share a 64-tick volley cycle across overlapping formations. At the start of the cycle they take one reading of the player's position. Each aimed shot uses its own launch point and that same target, so moving away from the point draws the fire behind the ship. During the rest of the cycle these fliers hold fire and their existing bullets continue across the screen. Green and yellow fliers keep their individual attack patterns. All waves share the 24-bullet pool and only one of the additional fliers can launch per tick.

| Level | Firing positions per additional flier | Ticks open / resting | Gap before yellow / other wave (ticks) |
| --- | ---: | ---: | ---: |
| 1 | 1 | Always open | 3 / 3 |
| 2 | 2 | Always open | 20 / 16 |
| 3 | 2 for Stair and Kite, 3 for Skimmer and Hook | Always open | 18 / 14 |
| 4 | 3 | 56 / 8 | 16 / 12 |
| 5 | 4 | 52 / 12 | 14 / 11 |
| 6 | 5 | 48 / 16 | 12 / 10 |
| 7 | 6 | 46 / 18 | 10 / 9 |
| 8 | 6 for Copper Drill, 8 for the others | 43 / 21 | 8 / 7 |
| 9 | 10 | 40 / 24 | 6 / 6 |

The build bakes each ship's vertical steps, horizontal dashes, entry lanes and firing positions into its existing 256-byte path page. GET READY enables the positions for the selected difficulty. Each ship shares its four animation frames across every difficulty. See [the enemy catalogue](../tools/enemy_catalog.py) for the editable formations, paths, bearings and rosters.

The sixteen compressed ship packets occupy 2,366 bytes in bank 6. Bank 0 reserves 2,048 bytes for eight sets of flight poses and 1,536 bytes for six additional flight paths. Level 1 expands 1,536 bytes of art and paths. An eight-species level expands 3,584 bytes. A returning species reuses its packet and gets its current level’s firing positions during GET READY. The renderer reads the resident poses directly throughout play.

| Enemy graphics and path load | Grey +2 | Black +2A |
| --- | ---: | ---: |
| Level 1 enemy load | 43.3 ms | 45.1 ms |
| Level 2 enemy load | 44.4 ms | 46.8 ms |
| Longest enemy load, levels 1–9 | 102.5 ms | 107.3 ms |

The headless loader check traces each decompressed byte and its destination on both machines. The gameplay check follows a full wave order, including entry lanes, each ship's X and Y, bullet origins and bearings. Run `tools/verify_enemy_catalog.py` on an assembled game directory, adding `--waves PATH_TO_SJASMPLUS` for the gameplay check. Add `--levels 9 --camp` to hold fire at the upper-right movement limit and check that aimed shots and ship losses occur there. Use `--restarts --levels 9` to check the four successive openings on the playable TAP.

To test a dodge route on both models, run `tools/verify_level9_dodge.py --game <assembled-game-directory> --assembler <sjasmplus.exe> --emulator <zesarux.exe>`. It plays the first level 9 wave order with normal lives, holds each direction for at least three game ticks, and leaves Fire released so all the enemies can shoot.

Yellow fliers enter at varied heights and travel straight left at one dot per game tick. Around 60% across the playfield, each flier captures the player's Y position. It then retreats right at two dots per tick for twelve ticks, using a prebaked path that reaches the captured height at the end of the retreat. It resumes flying left at one dot per tick.

| Level | Yellow flier firing |
| --- | --- |
| 1–5 | One slow aimed shot at the end of the retreat |
| 6–9 | An aimed shot halfway through the retreat and another at its end |

All enemies on a level share the same 32 prebaked bullet directions and speed. Up to 24 enemy bullets can be active at once. They alternate yellow and white on successive 25 Hz gameplay ticks.

Either player shot destroys an opponent in one hit and retires its whole pair before the next enemy is checked. A pair also retires at the right edge. A bullet destroys a vulnerable player ship, and a ram destroys both the vulnerable player and the enemy it hits. Both sides use 5×5 hitboxes and play a three-frame explosion over six game ticks. Their hitboxes disappear as soon as the explosion starts. You start with three lives. After a loss, the next ship appears at the starting position after 12 game ticks (0.48 seconds) and stays invincible for 75 game ticks (three seconds). Every other 25 Hz game frame hides the ship during invincibility. Protected contact is harmless to both ships. Movement and firing work on both blink phases after the spawn frame.

After the last ship is destroyed, the action continues for two seconds and the score freezes. The centred **GAME OVER**, **ENTER TO RESTART** and **M TO MAIN MENU** panel then appears above the final HUD. Enter restarts the same level with three ships. M returns to the title and starts Meadows Edge again. Leaving the panel alone returns to the title when the Game Over song finishes.

The Game Over cue is a three-channel AY arrangement of *Name Regist* from the TurboGrafx-16 version of *Raiden*. The supplied recording credits Akira Satoh and Shinichi Sakamoto. Edit [the Vortex Tracker master](../game/music/name-regist.vt2), save a PT3 copy alongside it as `name-regist.pt3`, then rebuild the TAP. The build compresses the module with ZX0. At Game Over, it expands into the idle renderer's attribute buffer and the title-screen PT3 player plays it once at 50 Hz. The player's end-of-song flag controls the return, so editing the song length requires no timer change.

The bottom HUD shows the level on the left, spare ships across the middle, and the right-aligned score at the far right. You start with one active ship and two spare icons. An empty strip means you are flying your last ship. Each enemy scores 100 points. You earn an extra ship and hear its chime at 20,000 points, then at 70,000 and every 50,000 points thereafter. All 22 possible spares fit beside a six-digit score and a two-digit level. The playfield is 46 logical rows high.

Each of the first 18 ships gets a full character of width. Each extra life packs four ships into three cells at the right of the strip. Losing that life restores the wider spacing in those cells. A life change redraws only the affected cells.

The score starts at `0`. The units zero is drawn at startup and the tens zero changes only when the score crosses between zero and a positive value. Each Frame 2 selects one changed cell or copies two scanlines of an already selected cell to both bitmap banks.

Frame 1 draws the first tile of the bottom tile row during the former HUD attribute-copy interval. Shifted tiles merge shared edge bytes in left-to-right order. The last tile pass omits the two hidden logical rows and skips the display swap inside the HUD. The fixed-time collision slots keep their original schedule and read eight inactive reserve records behind the 24 live projectile slots.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the projectile positions against ship hitboxes and retire spent pairs using the stock paging schedule. After sprite composition, the second game slot checks for ship contact and expands each paired record into two shots for plotting. Enemy bullets and rams check the middle three columns and all five rows of the player ship. The attribute buffer holds the colours for drawing. Inactive shots skip the buffer write. The banked 50 Hz AY player plays the 25.6-second Star Force loop on A and B. Channel C plays the player-shot tone and enemy-explosion noise.

## Reproduce

Press the keyboard Fire key (Space by default), Kempston fire or Sinclair fire (**0**) to start Level 1 with that controller. A held fire button must be released when returning to the menu. **1–9** start a level with the current controller. Press **R** to redefine keys. Sinclair fire takes priority over its direction keys on the same keyboard row.

The build packs the tiles used across the nine levels into 17 shared ZX0 strips (3,842 bytes). At GET READY, a per-level list selects strips and copies runs of tiles into the two existing renderer banks. The loader uses the future 1,536-byte map buffer as scratch space, generates the shifted rows, then unpacks the map over the scratch space and loads the enemy roster. The renderer stays idle throughout. The following measurements come from the playable TAP. The last two columns include the 35-frame ready hold, enemy loading and screen setup.

| Level | Packed map bytes | Resident tiles | Grey +2 to gameplay | Black +2A to gameplay |
| --- | ---: | ---: | ---: | ---: |
| 1 | 386 | 111 | 1.25 s | 1.28 s |
| 2 | 310 | 99 | 1.23 s | 1.26 s |
| 3 | 354 | 86 | 1.23 s | 1.26 s |
| 4 | 222 | 73 | 1.21 s | 1.24 s |
| 5 | 232 | 72 | 1.21 s | 1.24 s |
| 6 | 272 | 96 | 1.25 s | 1.30 s |
| 7 | 343 | 103 | 1.29 s | 1.32 s |
| 8 | 451 | 87 | 1.27 s | 1.32 s |
| 9 | 398 | 96 | 1.29 s | 1.30 s |

Run `tools/verify_level_tiles.py --game <assembled-game-directory> --emulator <zesarux.exe>` to check the normal and shifted graphics, GET READY text and elapsed time on all nine levels. The longest scenery-art installation was 293 ms on the +2 and 300 ms on the +2A.

`tools/verify_level_menu.py` takes the same assembler, emulator and optional TAP output arguments as the gameplay verifier. It checks all nine level keys on both models, screen text, sample map data, bank restoration, renderer startup, wave entrances, the yellow retreat and firing stages, and green shot aiming and speed. It also checks at least 150 consecutive gameplay frame pairs after each choice. Measurements include the call to ZX0 and exclude the ready screen delay and level setup.

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --output-tap <playable.tap>
```

The default build uses the packed Star Force assets in `game/music`. To audition an alternate tune, pass `--phrase-reference <full-reference.json>` with a full-song capture from `benchmark_ay.py --through-loop`. The gameplay regression uses the prototype waves and solid-colour artwork to retain its scripted collision scenarios. The exported keyboard-controlled TAP uses the current artwork and level waves. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the moving formations, a restart while alive, and a restart after losing all lives. The first 36 game ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The bottom HUD test (`tools/verify_bottom_score.py`) compares every pixel in both bitmap banks across score carries, bonus awards, a life loss, resets, the score cap and one- and two-digit level labels. The older prototype replay separately checks the original six-digit display and its two fixed trailing zeroes.

The prototype replay checks 1,630 HUD frames and expects 64 life-icon row updates and 168 score row updates per bitmap bank. Each row update takes 235 T-states, including the call, while an idle call takes 72. The prototype's in-playfield attribute strip takes 340 T-states per game tick.

The idle run checks two full respawns, alternating draw coordinates across all 75 protected game frames each time, overlap without life loss during protection, and game over on the third hit. It also checks all 12 enemy draw positions and hitboxes in a full formation before and after game over. A separate trace verifies the coordinates and visible pixels of a ship exiting on the left. The gameplay trace checks mutual destruction from rams, protected ship contact and ten simultaneous player shots. It also compares player and enemy explosion artwork with the expected frame sequence. Assembly probes verify all 32 aimed bearings, two angle boundaries and paired-shot retirement when either shot hits.

The prototype replay checks the original incremental two-line panel and its final score. For the current game, `tools/verify_game_over.py` seeds a last-ship hit on level 8. It checks the two-second delay, frame-by-frame tracker playback, retained score, same-level restart and both routes back to the title on the grey +2 and +2A.

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
