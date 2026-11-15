# Projectile workload in the stock two-frame schedule

This experiment builds a temporary variant of the pinned all-sprites sample. It keeps the tile renderer, all 16 small sprites, and the stock paging cadence. With `--collision`, fixed-time coordinate checks replace large-sprite drawing. The original sample TAP and source archive are used as references.

```powershell
python tools/verify_dot_overlay.py --archive <ringo8-source.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --baseline <full-stock-profile.json> --collision
```

The fixture draws nine `2×1` cyan shots and 32 yellow dots after Frame 2 rendering. Every cyan shot crosses an attribute-byte boundary and every yellow dot exercises its slower plot branch. All 41 shots are screen-relative, bounded, and fixed across the scrolling sample. The player and enemy hitboxes include misses, hits and a shared cyan/yellow dot. Both hits survive because the collision path reads coordinates independently of the buffer.

The collision probe initializes and checks the first two incoming dots before the first large-sprite OUT. Each of the 15 middle intervals checks one enemy box against all nine player shots and two incoming dots against the player. Fixed-length axis checks keep the timing independent of hits and misses. After the overlay, the guest checks all 16 hit flags and representative attribute fields. A separate headless video check verifies five complete `4×4` colour blocks at opposite viewport edges in eight consecutive captured frames.

| Result | 128K | +2A |
| --- | ---: | ---: |
| Complete frame pairs verified with `--collision` | 532 | 530 |
| Overlay plotting, including the viewport pointer update | 10,270 T-states | 10,270 T-states |
| Frame 2 time remaining at the next `HALT`, overlay only | 1,891 T-states | 1,888 T-states |
| Frame 2 time remaining at the next `HALT`, including hit-flag checks | 1,043 T-states | 1,040 T-states |

The verification covered all 256 stock motion phases. Each paging sequence matched an observed stock signature exactly. The added work preserves the four-T-state phase of the next `HALT`. A one-T-state error in that phase shifted the next frame's paging during bring-up.

The overlay appears over the small sprites because it runs after stock sprite composition. Moving bullets under the sprites would require placing their draw earlier in the composition pipeline. The fixture keeps positions and hitboxes fixed and uses the stock sample's motion to exercise scrolling and raster timing. A live projectile pool, clipping and in-game hit responses remain separate from this timing test.
