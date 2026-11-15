# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. Press **Enter** to restart at any time. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Hold Space to fire up to three simultaneous volleys, each expanding into three cyan shots. Shots retire at the edge of the 64×48 viewport.

The waves cycle once the last opponent is destroyed or flies off the left edge. A cyan hit destroys an opponent. Incoming hits take one of the player's three health points. The ship flashes white and green during the 24-tick grace period, just under a second at 25 Hz. Further contact during that period leaves health unchanged. Both sides use 5×5 hitboxes and projectiles stay in flight after a hit.

| Wave | Formation | Yellow fire |
| --- | --- | --- |
| 1 | One ship in the centre lane | Straight stream |
| 2 | Two ships in opposite lanes | Shallow shots that cross |
| 3 | Three staggered ships | Alternating shallow and steep diagonals |

At zero health the player ship is hidden. Enter clears the projectile pools, hit flags and score, restores three health points and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart. Music continues through the reset.

The HUD at the top right awards 100 points per destroyed ship and displays six digits. The opening layout and glyphs are loaded into both screen banks at startup. The original WIP drew a complete digit in each of five phases and converted its binary score to text in a sixth. This HUD keeps the four significant digits in packed decimal. It queues only changed digits and updates at most one scanline of one glyph per 50 Hz frame. Each changed row is written to both bitmap banks. In steady state the bitmap stays untouched. A narrow attribute strip is repainted once per game tick because tile and sprite composition rebuilds the attribute buffer.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions using the stock paging schedule. The second game slot plots active shots after sprite composition. Inactive slots skip the buffer write. The new gameplay uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the three formations, all 41 active projectile slots, a restart while alive, and a restart after losing all health. The first 24 scroll ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

The HUD tests compare each bitmap update and its page restore against the replay's score, check decimal carries and saturation, and verify `000000` and `000100` in headless video. Across 1,630 video frames, the score changed three glyphs and wrote 24 bitmap scanlines to each screen bank. Both models measured 235 T-states for an active row, 72 for an idle call, up to 313 for a digit selection in the replay, and 392 for the attribute strip. These measurements include the calls. In the archived WIP, the sampled complete-glyph phases took 557 T-states and the decimal conversion phase took 760, excluding the phase dispatch and return.

A separate replay crosses the opening wave's horizontal stream in all four movement directions. Each fresh crossing must set the collision flag and reduce health from three to two. The original HUD build at `67b2868` recorded damage in all four cases. Its border cue was cleared by the renderer at the start of each video frame. The current trace also checks the grace counter and sprite image through repeated overlaps. The video test detects the white ship silhouette in the playfield and rejects the original footage.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs with stock paging timestamps | 1,191 | 1,192 |
| Keyboard-build frame pairs with stock paging timestamps | 401 | 397 |
| Minimum Frame 1 replay margin at `HALT` | 1,042 T-states | 995 T-states |
| Minimum Frame 2 replay margin at `HALT` | 473 T-states | 474 T-states |
| Active projectile records checked in one frame | 41 | 41 |
| Enemy shots checked at emission | 464 | 464 |
| AY ticks compared with the reference, spanning the first restart | 1,024 | 1,024 |

Both models agreed with the reference over 815 replayed game ticks and all seven trajectories used by the waves. Headless video showed both ship colours and both projectile colours together. Independently built TAPs matched SHA-256 `dfba0dc3cde8cf5b682f841c6ed70f85a209e78d05c1ec147d0e75c895123a16`.
