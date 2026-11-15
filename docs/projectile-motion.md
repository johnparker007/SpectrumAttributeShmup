# Integer projectile motion

The motion harness updates three volley origins, expands them to nine player shots and updates a fixed pool of enemy dots once per 25 Hz game tick. The player shots move right. Each volley spreads one logical dot vertically every two ticks around its centre shot. Enemy dots move left with one of eight repeating integer Y step sequences, including straight, shallow, diagonal and steeper paths. Each enemy keeps its own phase. The high bits of its third state byte select the path and the low three bits select the phase.

```powershell
python tools/benchmark_motion.py --emulator <zesarux.exe> --assembler <sjasmplus.exe>
```

The test compares all state bytes and expanded shot coordinates against a separate reference. The edge case exercises retirement at the left and right edges, clipping at the top and bottom, and an inactive slot. Both emulated models returned identical timings.

| Workload | 16 enemy dots | 24 enemy dots | 32 enemy dots |
| --- | ---: | ---: | ---: |
| Full pool, including the three volleys | 4,085 | 5,373 | 6,661 |
| Edge and inactive fixture, including the three volleys | 3,826 | 5,114 | 6,402 |

The three volleys take 1,478 T-states in the full case. The 32-dot pool now takes 5,183, down from 7,834 with an indexed four-byte record. The full motion workload leaves 3,728 T-states against the narrower stock Frame 1 headroom before adding audio or game events. The [moving renderer fixture](projectile-integration.md#moving-shots) verifies active slots and their collision flags with 50 Hz playback running. This standalone test also exercises clipping, retirement and inactive slots.
