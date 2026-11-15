# Blokius WIP game-slot baseline

The sprite-manager WIP 1 archive contains two TAP/SNA pairs. The profiler rebuilds `game/main.asm` and compares the results with the archived `game/` pair. The files at the archive root are a different build. The TAP under `game/` has SHA-256 `d4d7b336e8cccaa4799a8dcad4152044e3c0e064824715ed061a6ac7d92653fb`.

```powershell
python tools/profile_blokius.py --archive <blokius-wip.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe>
```

The unmodified WIP ran headlessly on ZEsarUX 10.3 with SjASMPlus 1.20.2. The trace follows every update of the original barrel scroll through completion at game tick 1,981, then samples the completed state. The test sends no keyboard input. The WIP's music and gameplay collision calls are commented out.

| Measured span, in T-states | 128K | +2A |
| --- | ---: | ---: |
| Frame 1 total game logic through the next `HALT` | 1,526–2,870 | 1,526–2,870 |
| Barrel scroll call | 385–1,729 | 385–1,729 |
| Idle player update call | 227 | 227 |
| Sprite manager update call | 822 | 822 |
| Frame 1 minimum time remaining at `HALT` | 9,551 | 9,504 |
| Frame 2 total game logic through the next `HALT` | 631 | 631 |
| HUD draw call | 561 | 561 |
| Frame 2 minimum time remaining at `HALT` | 11,727 | 11,727 |

The completed captures had 2,586 and 2,590 complete frame pairs. The narrower Blokius Frame 1 slot has 885 T-states less headroom than the stock all-sprites sample. In Frame 2 the HUD and other game work leave 621 T-states less headroom than the narrower stock slot. The profiling results apply to idle controls and the supplied map. Input paths and any planned changes to the HUD need separate measurements before porting the combined projectile and audio workload.
