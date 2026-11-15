# 50 Hz AY playback experiment

The reference harness uses the compiled VTII PT3 r.7 player and song supplied in the Blokius WIP archive. The player is linked at 55000 and the song at 57158. The archived song is byte-identical to the PT3 payload in the local Vortex Tracker export of `meadows edge 1.ay`. The installed ZEsarUX 10.3 ran one tick per IM 2 video interrupt. The trace records the ordered AY writes and their instruction-start T-states.

```powershell
python tools/benchmark_ay.py --archive <blokius-wip.zip> --ay-export <vortex-export.ay> --assembler <sjasmplus.exe> --emulator <zesarux.exe> | Set-Content -Encoding UTF8 reference.json
python tools/verify_ay_stream.py --reference reference.json --assembler <sjasmplus.exe> --emulator <zesarux.exe>
```

The stream prototype stores register/value pairs followed by a per-tick terminator. It keeps changed values and every actual write to register 13, including repeated values that restart the envelope. The replay runs once per interrupt and verifies the same register state after every tick, with the same envelope data-write sequence. The writes occur earlier within their frames because the stream player has no tracker decode step.

| Workload | Calls | Reference T-states per tick | Stream T-states per tick |
| --- | ---: | ---: | ---: |
| First 256 song ticks | 256 | 3,627–6,555 | 211–841 |
| Synthetic envelope, empty tick and full-update test | 4 | — | 139–1,404 |

The two models produced matching instruction traces on repeated reference runs and matching stream results. The song prefix plus initialization takes 1,993 bytes of stream data. Playback emits 868 register writes instead of 3,342, counting initialization. The song prefix contains no envelope data writes after initialization. The synthetic test checks three tick-level envelope writes, including two consecutive writes of the same shape, and a 14-register update that crosses the end of the stream.

The prefix establishes a CPU budget for the decoder. The complete song's stream size, storage and banking, tracker loop position, and captured-audio comparison still need verification before integration. The standalone stream loops through its initialization entry for repeatable testing.
