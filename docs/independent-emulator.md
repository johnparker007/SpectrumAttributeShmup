# Independent zx_go timing check

The Windows release's headless command line starts in 48K. This check uses the published zx_go 1.13.0 source and its Go test harness to select 128K and +2A explicitly. The test enables per-access memory contention and steps 70,908 T-states per frame. It records `#7FFD` inside the ULA port callback, after the latch is applied. No GUI or audio device is opened.

```powershell
python tools/prepare_zxgo_snapshots.py --archive <ringo8-source.zip> --assembler <sjasmplus.exe> --output <snapshot-directory>
# Run the two Go commands from the extracted zx_go 1.13.0 module directory.
go run <repo>/tools/zxgo_raster_probe.go -probe -align-int <snapshot-directory>/probe-1079.sna <snapshot-directory>/probe-1080.sna
go run <repo>/tools/zxgo_raster_probe.go -align-int <snapshot-directory>/engine-128k.sna <snapshot-directory>/engine-plus2a.sna
```

The engine snapshots start at the sample's machine-code entry with the stock loader's page layout and +2A remapping. Adding the snapshot directive leaves the assembled TAP byte-identical. A portable Go 1.26.2 toolchain ran both commands.

zx_go's stock harness uses a Spectrum Next-derived interrupt origin of 292 T-states on 128K and 291 on +2A. `-align-int` places its INT assertion at T-state zero for comparison with ZEsarUX. Per-access memory contention is enabled separately because the Go harness defaults leave the CPU flag clear. With it disabled, Frame 1 finished roughly 860–935 T-states earlier than the ZEsarUX frame. The aligned contention-aware result follows.

| Raster probe shadow latch | ZEsarUX 10.3 | zx_go 1.13.0 |
| --- | ---: | ---: |
| 128K, 1,079 loops | 28,152 | 28,152 |
| 128K, 1,080 loops | 28,173 | 28,173 |
| +2A, 1,079 loops | 28,147 or 28,149 | 28,149 |
| +2A, 1,080 loops | 28,175 | 28,173 |

For +2A, the 1,080-loop latch is 28,114 T-states after the normal-screen latch in both emulators. The absolute two-T-state difference originates before the probe's delay loop.

The stock sample comparison covered eight frame pairs per model. All pairs agreed on the ordered port-write sites and values. On 128K, Frame 1 matched exactly except for one first write one T-state late. The Frame 2 writes were all two or three T-states later, matching the shift in interrupt entry. On +2A, Frame 2 matched exactly. During the Frame 1 attribute-row copies, +2A switches in zx_go fell up to 23 T-states later than ZEsarUX. The remaining Frame 1 writes were 13 T-states later. That difference needs a further reference before treating either emulator's +2A attribute-transfer timestamps as physical timing.

This comparison uses the latch callback and instruction boundaries. zx_go's classic rendered image still selects one screen bank for the whole frame, so the mid-line colour check continues to use ZEsarUX video.
