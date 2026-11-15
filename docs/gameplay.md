# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. Press **Enter** to restart at any time. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Hold Space to fire up to three simultaneous volleys, each expanding into three cyan shots. Shots retire at the edge of the 64×48 viewport.

The waves cycle once the last opponent is destroyed or flies off the left edge. A cyan hit destroys an opponent, and an incoming hit destroys a vulnerable player ship. You start with three lives. After a loss, the next ship appears at the starting position after 12 game ticks (0.48 seconds) and stays invincible for 75 game ticks (three seconds). Every other 25 Hz game frame hides the ship during invincibility. Movement and firing work on both blink phases after the spawn frame. Both sides use 5×5 hitboxes and projectiles stay in flight after a hit.

| Wave | Formation | Yellow fire |
| --- | --- | --- |
| 1 | One ship in the centre lane | Straight stream |
| 2 | Two ships in opposite lanes | Shallow shots that cross |
| 3 | Three staggered ships | Alternating shallow and steep diagonals |

After the last ship is destroyed, **GAME OVER** and **ENTER TO RESTART** appear in a centred panel. The top-right HUD keeps the final score visible. The score freezes even if a shot already in flight reaches an opponent. Enter clears the panel, projectile pools, hit flags and score, restores three lives and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart. Music continues through the reset.

The HUD at the top right shows the remaining lives as small ships to the left of a six-digit score. It awards 100 points per destroyed ship and stores the four significant digits in packed decimal. The trailing `00` is loaded into both bitmap banks at startup and stays outside the update queue. A life change adds or erases only the affected icons. The queue updates at most one scanline of one glyph per 50 Hz frame and copies it to both banks. The bitmap stays untouched when the HUD has caught up. Tile and sprite composition rebuilds the attribute buffer, so the ten-column HUD strip gets its colours reapplied once per game tick.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions using the stock paging schedule. The second game slot plots active shots after sprite composition. Inactive slots skip the buffer write. The new gameplay uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the three formations, all 41 active projectile slots, a restart while alive, and a restart after losing all lives. The first 24 scroll ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The HUD tests compare each bitmap update and its page restore against score and life changes, including resets. They reject writes to the two trailing zeroes and check decimal carries and saturation. Headless video checks `000000` with three ships at startup and `000100` with two ships after the first kill and life loss.

Across 1,630 replay frames on each model, the HUD updated 72 life-icon rows and 104 score rows per bitmap bank. Each row update cost 235 T-states, including the call, while an idle call cost 72. The smaller attribute strip cost 340 T-states per game tick, down from 392 with the label.

A separate replay crosses the opening wave's horizontal stream in all four movement directions. Each vulnerable crossing must set the collision flag, hide the destroyed ship and deduct one life. The idle run checks two full respawns, alternating draw coordinates across all 75 protected game frames each time, overlap without life loss during protection, and game over on the third hit. The video test checks that the ship visibly disappears and returns.

The main replay ends a run with a score of 900 and a player shot still in flight. The trace checks that its later hit leaves the final score unchanged and that the 16 bitmap rows of the game-over panel are installed and restored incrementally. Headless video checks both lines and the final score together, followed by a cleared panel and reset HUD after Enter.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs with stock paging timestamps | 957 | 959 |
| Keyboard-build frame pairs with stock paging timestamps | 373 | 370 |
| Minimum Frame 1 replay margin at `HALT` | 191 T-states | 144 T-states |
| Minimum Frame 2 replay margin at `HALT` | 296 T-states | 297 T-states |
| Active projectile records checked in one frame | 41 | 41 |
| Enemy shots checked at emission | 365 | 365 |
| AY ticks compared with the reference, spanning the first restart | 1,024 | 1,024 |

Both models agreed with the reference over 815 replayed game ticks. Headless video showed both ship colours and both projectile colours together. Independently built TAPs matched SHA-256 `8c0ab32e068a473cb7bd4adfb7055fe5253455fd5e932b89c5b15b97c89647db`.
