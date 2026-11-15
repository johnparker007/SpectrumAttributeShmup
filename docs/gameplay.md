# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. Press **Enter** to restart at any time. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Hold Space to fire up to three simultaneous volleys, each expanding into three cyan shots. Shots retire at the edge of the 64×48 viewport.

The waves cycle once the last opponent is destroyed or flies off the left edge. A cyan hit destroys an opponent. Incoming hits take one of the player's three health points and turn the border red during a 24-tick grace period. Both sides use 5×5 hitboxes and projectiles stay in flight after a hit.

| Wave | Formation | Yellow fire |
| --- | --- | --- |
| 1 | One ship in the centre lane | Straight stream |
| 2 | Two ships in opposite lanes | Shallow shots that cross |
| 3 | Three staggered ships | Alternating shallow and steep diagonals |

At zero health the player ship is hidden. Enter clears the projectile pools and hit flags, restores three health points and the opening formation, and rewinds the scenery and tile animations. Holding Enter triggers one restart. Music continues through the reset.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions using the stock paging schedule. The second game slot plots active shots after sprite composition. Inactive slots skip the buffer write. The new gameplay uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all six controls and reaches the restart routine through the emulated Spectrum matrix. The replay covers the three formations, all 41 active projectile slots, a restart while alive, and a restart after losing all health. The first 24 scroll ticks following each restart are compared with the cold-start sequence, including the source cursor, sampled map cells and all five animated-tile pointers. Both builds are compared against the stock render-time paging trace. Increase `--replay-seconds` if the replay paging trace stops short of the second restart.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs with stock paging timestamps | 1,236 | 1,241 |
| Keyboard-build frame pairs with stock paging timestamps | 426 | 419 |
| Minimum Frame 1 replay margin at `HALT` | 1,129 T-states | 1,082 T-states |
| Minimum Frame 2 replay margin at `HALT` | 1,056 T-states | 1,055 T-states |
| Active projectile records checked in one frame | 41 | 41 |
| Enemy shots checked at emission | 464 | 464 |
| AY ticks compared with the reference, spanning the first restart | 1,024 | 1,024 |

Both models agreed with the reference over 815 replayed game ticks and all seven trajectories used by the waves. Headless video showed both ship colours and both projectile colours together. Independently built TAPs matched SHA-256 `07d5efc8e46c37b2089de4fdd8ace487308ea72b72e0b196fb484fb388e209d4`.
