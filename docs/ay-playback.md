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
| Complete song through the PT3 loop marker | 5,120 | 3,627–8,218 | — |

The two models produced matching instruction traces on repeated reference runs and matching stream results. The song prefix plus initialization takes 1,993 bytes of stream data. Playback emits 868 register writes instead of 3,342, counting initialization. The song prefix contains no envelope data writes after initialization. The synthetic test checks three tick-level envelope writes, including two consecutive writes of the same shape, and a 14-register update that crosses the end of the stream.

Run the reference benchmark with `--through-loop` to capture all 5,120 ticks before the tracker returns to its loop position. The full capture contains the same first 256 ticks and no envelope data writes after initialization. The uncompressed delta stream for the full song is 49,761 bytes. The standalone prefix benchmark loops through its initialization entry for repeatable timing.

Pass `--pt3 <export.pt3>` to `benchmark_ay.py --through-loop` to capture a Vortex Tracker export with the same reference player. The archive supplies the player. The resulting JSON is the input to the phrase packer below.

## Banked whole-song playback

```powershell
python tools/verify_ay_phrases.py --reference <full-reference.json> --assembler <sjasmplus.exe> --emulator <zesarux.exe> --output <output-directory>
```

Repeated runs of complete tick packets share one literal copy. Each three-byte recipe entry contains a virtual offset into two literal banks and a count of consecutive ticks. Runs end at bank boundaries, and no packet crosses one. A host decode reconstructs the entire original delta stream before the snapshot is built. The guest streams register/value pairs directly from the selected bank and restores the previous test bank after each tick.

On both models, the verifier compared every write of the 5,120-tick song and the first 32 ticks after the reconstructed loop against the corresponding captured reference register states and envelope sequence. The loop starts at the first music tick and restores its state without consuming an initialization frame. Native tracker writes after its first loop boundary were outside the reference capture. The complete recipe and literal data take 23,049 bytes versus 49,769 for the loop-ready unpacked stream. The stand-alone banked player took 221–1,424 T-states per tick.

The [combined renderer experiment](projectile-integration.md#with-50-hz-playback) verifies both a looping 256-tick prefix and banked playback with the complete track loaded. A captured-audio comparison remains open.

## Star Force gameplay music

The gameplay build uses the packed Star Force cover in `game/music`. It plays on channels A and B and loops after 1,280 AY ticks. The 759-byte recipe and 695-byte literal pool were generated from `MainLoop.pt3` (SHA-256 `2e4d488e6070f127f911adbe4f5707043c9145a1c78f681dc154b62a187daa97`). Capture the export with `benchmark_ay.py --pt3 MainLoop.pt3 --through-loop` and pack the resulting JSON with `verify_ay_phrases.py`. The recipe and first literal bank are the gameplay assets.
