# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. Press **Enter** to restart at any time. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Hold Space to fire up to three simultaneous volleys, each expanding into three cyan shots. Shots retire at the edge of the 64×48 viewport.

Enemy ships enter beyond the right edge and move left one logical dot per game tick. The formation has 12 slots and admits a new ship every five ticks when its next slot is free. The player and formation use 13 of the 16 small-sprite slots. Each group of 12 uses the next of four paths, cycling through a straight line and three sine patterns with different centres, amplitudes and periods. The build generates 256 absolute Y coordinates. A ship uses its X position and pattern to fetch a Y coordinate during play.

The scenery advances every other game tick, at half the horizontal speed of the ships. Tile animations continue to update every game tick.

The ships take turns firing, with at most one shot across the formation every eight game ticks. An integer comparison of the horizontal and vertical distances picks one of eight bearings toward the player. When the player is absent, shots go straight left. Enemy shots advance two trajectory steps per game tick. The build combines the two vertical deltas into one lookup. Collisions are sampled at the resulting position, once per game tick.

A cyan hit destroys an opponent, and an incoming hit destroys a vulnerable player ship. Both play a three-frame explosion over six game ticks. Their hitboxes disappear as soon as the explosion starts. You start with three lives. After a loss, the next ship appears at the starting position after 12 game ticks (0.48 seconds) and stays invincible for 75 game ticks (three seconds). Every other 25 Hz game frame hides the ship during invincibility. Movement and firing work on both blink phases after the spawn frame. Both sides use 5×5 hitboxes and projectiles stay in flight after a hit.

After the last ship is destroyed, **GAME OVER** and **ENTER TO RESTART** appear in a centred panel. The top-right HUD keeps the final score visible. The score freezes even if a shot already in flight reaches an opponent. Enter clears the panel, projectile pools, hit flags and score, restores three lives and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart. Music continues through the reset.

The HUD at the top right shows the remaining lives as small ships to the left of a six-digit score. It awards 100 points per destroyed ship and stores the four significant digits in packed decimal. The trailing `00` is loaded into both bitmap banks at startup and stays outside the update queue. A life change adds or erases only the affected icons. The queue updates at most one scanline of one glyph per 50 Hz frame and copies it to both banks. The bitmap stays untouched when the HUD has caught up. Tile and sprite composition rebuilds the attribute buffer, so the ten-column HUD strip gets its colours reapplied once per game tick.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions using the stock paging schedule. The second game slot plots active shots after sprite composition. Inactive slots skip the buffer write. The new gameplay uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the moving formations, a restart while alive, and a restart after losing all lives. The first 24 scroll ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The HUD tests compare each bitmap update and its page restore against score and life changes, including resets. They reject writes to the two trailing zeroes and check decimal carries and saturation. Headless video checks `000000` with three ships at startup and the first score update.

The replay checks 1,630 HUD frames and expects 85 life-icon row updates and 256 score row updates per bitmap bank. Each row update takes 235 T-states, including the call, while an idle call takes 72. The attribute strip takes 340 T-states per game tick.

The idle run checks two full respawns, alternating draw coordinates across all 75 protected game frames each time, overlap without life loss during protection, and game over on the third hit. It also checks all 12 enemy draw positions and hitboxes in a full formation before and after game over. The gameplay trace compares both player and enemy explosion artwork with the expected frame sequence. A separate assembly probe verifies all eight aimed bearings and two axis boundaries.

The main replay ends a run with a nonzero score. The trace checks that the final score stays fixed and that the 16 bitmap rows of the game-over panel are installed and restored incrementally. Headless video checks both lines and the final score together, followed by a cleared panel and reset HUD after Enter.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs checked against stock paging | ≥815 | ≥815 |
| Keyboard-build frame pairs checked against stock paging | ≥256 | ≥256 |
| Minimum Frame 1 margin across the 815-tick replay | 1,106 T-states | 1,059 T-states |
| Minimum Frame 2 margin across the 815-tick replay | 4,537 T-states | 4,535 T-states |
| Visible enemy ships checked together | 12 | 12 |
| Enemy shots checked at emission | 71 | 71 |
| AY ticks compared with the reference, spanning the first restart | 1,024 | 1,024 |

Both models matched the 815-tick replay, including two restarts. Headless video checks magenta ships, cyan player shots, yellow enemy shots and white explosion sprites. Independent builds of the keyboard TAP matched SHA-256 `ec74f2e052807388723b34fa80bbcdb301c7e4e342727faaf5002ee57e835019`.
