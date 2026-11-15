# Attribute-buffer dot plotting

Ringo-8 fills both screen bitmaps with `11110000`. For each 8-pixel display cell, the left four pixels therefore use INK and the right four use PAPER. The renderer sends 48 logical rows of packed attributes to the two screens. Inside the engine, a row is 38 bytes wide and the visible viewport occupies 32 bytes of it. Screen-relative dot `(x,y)` is in `(attrPointer) + 38*y + floor(x/2)`. Even X uses bits 0–2, odd X uses bits 3–5. Both dots share BRIGHT and FLASH. The active pointer varies with scroll. The draw-to-buffer sample and the sprite renderer both load it before drawing.

The plotter masks and replaces only the selected colour field. An even-X `2×1` shot can replace both fields in one byte. An odd-X shot spans the PAPER field and the next byte's INK field. The `1×1` shot always touches one field. The test uses a nonzero viewport offset, preserves row padding and flag bits, and compares the entire result against a host reference after each bullet layer. Colour 3 is included because an OR of blue and red can produce it. OR-only bullet plotting is unsuitable for this palette. Cyan OR red and yellow OR blue both produce white.

## Headless benchmark

```powershell
python tools/benchmark_dots.py --emulator <zesarux.exe> --assembler <sjasmplus.exe>
```

All 18 cases passed with SjASMPlus 1.20.2 and ZEsarUX 10.3. Fixtures use bounded coordinates, all slots occupied, even-X, odd-X and mixed alignment, and a player/enemy overlap. Code, stack, coordinates and buffer are in uncontended bank 2 on both models. Timings include coordinate-to-address conversion, the plot, and loop overhead. They exclude motion, clipping, collision, paging and raster synchronization.

| Workload | All even X | Mixed | All odd X |
| --- | ---: | ---: | ---: |
| Nine player shots, `2×1` | 2,203 | 2,311 | 2,446 |
| Sixteen enemy dots | 3,904 | 3,848 | 3,792 |
| Twenty-four enemy dots | 5,848 | 5,764 | 5,680 |
| Thirty-two enemy dots | 7,792 | 7,680 | 7,568 |

The slowest possible combination of these plotting paths costs 6,350, 8,294 or 10,238 T-states for nine player shots and 16, 24 or 32 enemy dots respectively. The 32-dot case leaves 151 T-states against the narrowest stock Frame 1 headroom, before paying for motion or collisions. That comparison gives a cost scale. The stock Frame 1 game slot occurs during the tile pipeline, and the correct composition point needs separate raster verification.

A hit probe may mask a field and compare its three bits against cyan (5) or yellow (6) while the background palette stays within 0–3. In the tested draw order, yellow replaces cyan when bullets share the same logical dot. A collision system that needs evidence of both layers at a shared dot needs another representation or a different sampling order. Once sprites are drawn, their colour fields can also replace bullet markers.
