# Blokius barrel-scroll scenery

The verifier rebuilds the pinned Blokius archive and checks the TAP and SNA against the archived `game/` binaries. It takes the barrel scroll, source map, tileset and tile animations into a temporary experimental build. The scene loop drops the WIP's player, sprite manager, HUD, scoring, and tracker player. The new workload advances three volleys and 32 enemy dots, checks 16 hitboxes in the large-sprite slots, and draws after Frame 2 composition.

```powershell
python tools/verify_blokius_integration.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --phrase-reference <full-reference.json> --output-tap <experimental.tap>
```

Generate the AY reference with `benchmark_ay.py --through-loop`. The recipe starts at `#CB00` in bank 0. The literal pools use the same logical banks 1 and 3 as the [Ringo-8 workload](projectile-integration.md#banked-whole-song-data).

The test runs without input on both emulated models. It compares the ordered render-time OUT sites, values and instruction boundaries with captures of the archived build. A second trace compares the scroll position, source cursor, animated tile pointer and samples from all six map rows at every game tick through the end of the map. The remaining checks cover moving coordinates, hit flags, visible 4×4 blocks and the first 1,024 AY ticks across both literal banks.

| ZEsarUX 10.3 measurement | 128K | +2A |
| --- | ---: | ---: |
| Game ticks matched through scroll completion | 1,981 | 1,981 |
| Complete frame pairs with archived paging signatures | 469 | 470 |
| Minimum Frame 1 time remaining at `HALT` | 2,730 T-states | 2,683 T-states |
| Minimum Frame 2 time remaining at `HALT` | 1,489 T-states | 1,488 T-states |
| AY playback call duration | 361–1,549 T-states | 361–1,549 T-states |

Both runs verified all 16 projectile phases and eight video frames. The independently assembled 122,732-byte TAPs have identical SHA-256 `2d1ff6d98d89874295f737c3a2181eaf7f772a1e1225553ebeb0159befad89d5`. Increase `--seconds` or `--scroll-seconds` if the corresponding trace is too short on a slower host.
