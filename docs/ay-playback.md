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

## Meadows Edge menu music

The title menu uses the archive's original 2,015-byte Meadows Edge PT3 and 1,617-byte tracker player in logical bank 3. The main menu calls it once per frame in the bottom border. The logo writes 28 attributes right to left every scanline. The left nine attribute pairs are written for the following scanline because the ULA has already fetched them. Four colour pairs follow independent paths over a 256-step sequence, advancing once every four frames. The gameplay renderer is disabled throughout the menu. Choosing a level mutes the tracker while the ready screen loads the map. Gameplay initializes its packed AY player separately.

## Star Force gameplay music

The gameplay build uses the packed Star Force cover in `game/music`. It plays on channels A and B and loops after 1,280 AY ticks. The 759-byte recipe and 695-byte literal pool were generated from `MainLoop.pt3` (SHA-256 `2e4d488e6070f127f911adbe4f5707043c9145a1c78f681dc154b62a187daa97`). Capture the export with `benchmark_ay.py --pt3 MainLoop.pt3 --through-loop` and pack the resulting JSON with `verify_ay_phrases.py`. The recipe and first literal bank are the gameplay assets.

## Gameplay sound effects

Capture `SoundEffects.pt3` with `benchmark_ay.py --pt3 SoundEffects.pt3 --through-loop`, then run `python tools/extract_ay_effects.py SoundEffects.vt2 <reference.json> game/music`. The extractor uses the sample 3 notes to cut pattern 0 (enemy explosion) and pattern 1 (player fire). The effects occupy 90 bytes in total.

A launched shot pair starts the tone sweep on channel C. An enemy entering its explosion animation starts the 27-tick noise sequence on C. Each effect follows its captured volume when it plays alone. While both play, the AY noise gates the shot tone and channel C uses the higher of the two volumes for that tick. The music stays on A and B. A new event of the same kind restarts its effect, and a game restart clears both effects while the music continues.
