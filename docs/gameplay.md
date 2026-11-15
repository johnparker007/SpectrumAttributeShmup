# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. Press **Enter** to restart at any time. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Hold Space to fire two parallel cyan shots at a time, with up to five pairs in flight. The two shots share an X coordinate and fly two dots apart vertically.

Enemy ships enter beyond the right edge and move left one logical dot every other game tick. The formation has 12 slots and admits a new ship every ten ticks when its next slot is free, spacing them five dots apart horizontally. The player and formation use 13 of the 16 small-sprite slots. Each group of 12 uses the next of four paths, cycling through a straight line and three sine patterns with different centres, amplitudes and periods. The build generates 256 absolute Y coordinates. A ship uses its X position and pattern to fetch a Y coordinate during play.

The scenery and tile animation tables advance every other game tick. The eight preshifted parallax frames each stay visible for four game ticks. The other four animated tiles use the same frame duration.

The ships take turns firing, with one firing opportunity across the formation every eight game ticks. At firing time, integer comparisons against precomputed thresholds pick the closest of 32 bearings toward the player. The second and fourth flight patterns fire three shots centred on that bearing, with one shot 22.5° to either side and at least 16 game ticks between spreads. The first and third patterns fire single shots. When the player is absent, the centre bearing points straight left. Horizontal and vertical shots alternate one and two dots per game tick. Exact diagonal shots move one dot on each axis per tick. The build distributes the intermediate angles' X and Y steps across eight-tick sequences. In flight, each shot reads its deltas from two 256-byte tables and uses a three-byte record. Collisions are sampled at the resulting position, once per game tick.

Either cyan shot destroys an opponent in one hit and retires its whole pair before the next enemy is checked. A pair also retires at the right edge. An incoming hit destroys a vulnerable player ship. Both ships play a three-frame explosion over six game ticks. Their hitboxes disappear as soon as the explosion starts. You start with three lives. After a loss, the next ship appears at the starting position after 12 game ticks (0.48 seconds) and stays invincible for 75 game ticks (three seconds). Every other 25 Hz game frame hides the ship during invincibility. Movement and firing work on both blink phases after the spawn frame. Both sides use 5×5 hitboxes.

After the last ship is destroyed, **GAME OVER** and **ENTER TO RESTART** appear in a centred panel. The top-right HUD keeps the final score visible. The score freezes even if a shot already in flight reaches an opponent. Enter clears the panel, projectile pools, hit flags and score, restores three lives and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart. Music continues through the reset.

The HUD at the top right shows the remaining lives as small ships to the left of a six-digit score. It awards 100 points per destroyed ship and stores the four significant digits in packed decimal. The trailing `00` is loaded into both bitmap banks at startup and stays outside the update queue. A life change adds or erases only the affected icons. The queue updates at most one scanline of one glyph per 50 Hz frame and copies it to both banks. The bitmap stays untouched when the HUD has caught up. Tile and sprite composition rebuilds the attribute buffer, so the ten-column HUD strip gets its colours reapplied once per game tick.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions and retire spent pairs using the stock paging schedule. The second game slot expands each paired record into two shots for plotting after sprite composition. Inactive shots skip the buffer write. The game uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the moving formations, a restart while alive, and a restart after losing all lives. The first 36 game ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The HUD tests compare each bitmap update and its page restore against score and life changes, including resets. They reject writes to the two trailing zeroes and check decimal carries and saturation. Headless video checks `000000` with three ships at startup and the first score update.

The replay checks 1,630 HUD frames and expects 64 life-icon row updates and 117 score row updates per bitmap bank. Each row update takes 235 T-states, including the call, while an idle call takes 72. The attribute strip takes 340 T-states per game tick.

The idle run checks two full respawns, alternating draw coordinates across all 75 protected game frames each time, overlap without life loss during protection, and game over on the third hit. It also checks all 12 enemy draw positions and hitboxes in a full formation before and after game over. The gameplay trace checks ten simultaneous player shots and compares both player and enemy explosion artwork with the expected frame sequence. Assembly probes verify all 32 aimed bearings, two angle boundaries and paired-shot retirement when either shot hits.

The main replay ends a run with a nonzero score. The trace checks that the final score stays fixed and that the 16 bitmap rows of the game-over panel are installed and restored incrementally. Headless video checks both lines and the final score together, followed by a cleared panel and reset HUD after Enter.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs checked against stock paging | ≥815 | ≥815 |
| Keyboard-build frame pairs checked against stock paging | ≥256 | ≥256 |
| Minimum Frame 1 margin across the 815-tick replay | 1,641 T-states | 1,594 T-states |
| Minimum Frame 2 margin across the 815-tick replay | 4,371 T-states | 4,372 T-states |
| Visible enemy ships checked together | 12 | 12 |
| Player shots verified in flight together | 10 | 10 |
| Enemy shots checked at emission | 72 | 72 |
| Aimed three-way spreads checked | 13 | 13 |
| AY ticks compared with the reference, spanning the first restart | 1,024 | 1,024 |

Both models matched the 815-tick replay, including two restarts. Headless video checks magenta ships, cyan player shots, yellow enemy shots and white explosion sprites. Independent builds of the keyboard TAP matched SHA-256 `08b291cc98401f9fed77380bfd4645b2cf9ae54f774812f561358b9bfc080e4f`.
