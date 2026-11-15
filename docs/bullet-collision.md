# Bullet collision on the packed attribute buffer

The probe expects a tile palette within 0–3 and clipped, in-bounds hitboxes. Immediately after the cyan pass, colour bit 2 can only have come from a cyan dot. The scan ORs the two fully covered attribute bytes before testing their colour bits, and checks the partial byte separately. The later yellow probe uses a 256-byte lookup table that identifies yellow INK and PAPER even if cyan is also present. For an even-X box, the last byte contributes only INK. For an odd-X box, the first byte contributes only PAPER. Both scans ignore BRIGHT and FLASH.

Probe enemy hitboxes immediately after drawing cyan. Then plot yellow and probe the player hitbox. This order detects both collisions even when yellow overwrites the only cyan dot inside an enemy's box. The headless fixture verifies that overlap, both parities, rejected dots next to hitbox edges and a hit in the final row. The reference computes rectangle/shot intersections from logical coordinates. Both guest routines must return the same 16 hit flags.

```powershell
python tools/benchmark_collision.py --emulator <zesarux.exe> --assembler <sjasmplus.exe>
```

All 18 fixtures passed on ZEsarUX 10.3 with SjASMPlus 1.20.2. Both models returned the same durations. These figures cover 15 enemy hitboxes against nine `2×1` player shots, then one player hitbox against the given enemy count. The benchmark supplies the layers and hitboxes before timing starts.

| Workload | Packed-buffer probe | Coordinate probe, 16 / 24 / 32 enemy shots |
| --- | ---: | ---: |
| All miss after horizontal overlap | 10,540 | 20,493 / 21,429 / 22,365 |
| All hit late in the scan | 10,279 | 20,189 / 21,125 / 22,061 |
| Overlap and selective hits | 10,089 | 11,649 / 11,649 / 11,649 |

The original lookup scan for both colours peaked at 12,850 T-states. The cyan-only bit test cuts the measured maximum by 2,310 T-states and saves one 256-byte lookup table. The packed probe's measured maximum is independent of the enemy shot count. The coordinate probe can win when horizontal tests reject shots quickly. At 32 enemy dots, plotting and the optimized probe together cost up to 20,778 T-states in these tests. That is before motion, clipping or audio. The estimate does not yet account for the placement of raster switches or the first eight small sprites, which the stock renderer draws before the large-sprite phase.
