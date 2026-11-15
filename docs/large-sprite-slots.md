# Work slots in the large-sprite interval

The original all-sprites sample takes 29,209 T-states for its eight-large-sprite phase. Sixteen `#7FFD` writes fall inside that interval. They change the display screen while bank 0 stays mapped for the sprite code. The first OUT starts 1,316 T-states after large-sprite dispatch. The middle intervals alternate 1,792 and 1,856 T-states. The last OUT starts 565 T-states before the phase ends. These intervals are the same on both emulated hardware families.

The experiment builds a temporary copy of the pinned sample and replaces its large-sprite include. The replacement keeps the original OUT addresses, sets up a scratch stack in bank 0, and alternates bounded synthetic work with the stock `DELAY` routine. The original small-sprite groups stay on either side. Neither the source archive nor the stock timing profiler's TAP changes.

```powershell
python tools/verify_sprite_slots.py --archive <ringo8-source.zip> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --baseline <full-stock-profile.json>
```

Use `profile_ringo8.py --full` to produce the stock profile. `--baseline` also accepts separate stock reports for the two machine models. The verifier checks each replacement frame's ordered `(PC, byte, latch T-state)` sequence against the verified stock traces. It also checks every synthetic slice and the two-frame control flow. Increase `--seconds` if the capture falls short of all 256 motion phases.

| Measured synthetic work per Frame 2 | Slices | Body T-states per slice |
| --- | ---: | ---: |
| Before the first large-sprite OUT | 1 | 996 |
| Between successive large-sprite OUTs | 15 | 1,464 |
| After the final large-sprite OUT | 1 | 281 |
| Total | 17 | 23,237 |

Both models executed 23,237 T-states of synthetic body work, or 23,815 including the setup, call and return of each slice. The verified captures covered 541 frame pairs on 128K and 538 on +2A. Every observed paging sequence matched a stock sequence, with 26 writes in Frame 1 and 27 in Frame 2. The stock and replacement runs measured the same small-sprite group durations and Frame 2 logic headroom.

The 32-dot plotting and optimized collision benchmark totals 20,778 T-states, 2,459 below the synthetic body total. An integrated workload has to fit individual slices, preserve its state between them and account for clipping, movement and audio. The large-sprite phase also begins after the first eight small sprites, while the packed collision test requires the relevant bullet colour to be sampled before sprite colours overwrite it. The experiment establishes the paging schedule and measured slot capacity. It leaves layer ordering and an integrated object budget to further tests.
