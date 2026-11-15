# Playable barrel-scroll build

Use **O** and **P** to move left and right, **Q** and **A** to move up and down, and **Space** to fire. The player moves one logical dot per axis per 25 Hz game tick. Opposite directions cancel. Fire can be held. Three volleys can be active at once, each expanding into three cyan shots. Shots retire at the edge of the 64×48 viewport.

The player and opponent use hardware-independent logical positions and 5×5 hitboxes. The opponent enters from the right and sends straight yellow dots left. Its next pass uses another lane. A cyan hit destroys the current opponent. Incoming hits take one of the player's three health points and turn the border red during a 24-tick grace period. At zero health, the player ship is hidden and stops responding to input. Reload the TAP to start again. Collision checks leave projectiles in flight.

The first game slot reads the keyboard, resolves the previous collision flags, moves the ships and advances the projectiles. The large-sprite intervals check the new positions using the stock paging schedule. The second game slot plots active shots after sprite composition. Inactive slots skip the buffer write. The new gameplay uses the archived barrel-scroll scenery and the banked 50 Hz AY player.

## Reproduce

```powershell
python tools/verify_gameplay.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <playable.tap>
```

Generate the song reference with `benchmark_ay.py --through-loop`. The verifier builds a keyboard-controlled TAP and a separate deterministic replay build. Only the keyboard-controlled TAP is exported. A keyboard spool checks all five controls through the emulated Spectrum matrix. The replay exercises all four movement bounds, opposite directions, firing, opponent destruction, player damage and all 41 active projectile slots. The keyboard build is also checked with no input until all player health is lost. Both builds are compared against the stock render-time paging trace. Increase `--seconds` if the raster trace captures fewer than 256 pairs.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Replay frame pairs with stock paging timestamps | 383 | 382 |
| Keyboard-build frame pairs with stock paging timestamps | 386 | 382 |
| Minimum Frame 1 replay margin at `HALT` | 1,557 T-states | 1,510 T-states |
| Minimum Frame 2 replay margin at `HALT` | 1,055 T-states | 1,056 T-states |
| Active projectile records checked in one frame | 41 | 41 |
| AY ticks compared with the reference | 1,024 | 1,024 |

Both models agreed with the reference over 226 replayed game ticks. Headless video showed both ship colours and both projectile colours together. Independently built TAPs matched SHA-256 `e38ed616843d2e826ce135c320c73521fdfd46563b8ace5b877b32e96355c179`.
