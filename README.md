# Spectrum Attribute Shmup

The first milestone is a headless timing laboratory for the original Ringo-8 renderer on the ZX Spectrum 128K and +2A/+3 hardware families.

## Rebuild the upstream samples

Use Python 3 and SjASMPlus. The upstream README lists 1.20.1. The first local verification used 1.20.2. Keep the [pinned Ringo-8 source ZIP](https://github.com/DenisGrachev/Ringo-8/archive/452fcc86d4ed72574a5cced6e8e5d9184d44c0e7.zip) as the reference copy.

```powershell
python tools/build_ringo8.py --archive <ringo8-source.zip> --assembler <sjasmplus.exe> --output <output-directory>
```

Replace the three placeholders with paths. The script reads the revision from the GitHub ZIP comment and stages the sources in a temporary directory. It comments out `SHELLEXEC "main.tap"` in each staged entry point to prevent the assembler from opening the associated emulator. It compares all 12 freshly assembled TAP files with the upstream copies byte for byte. On success it writes TAPs and symbol maps to the output directory and prints JSON with the upstream revision, assembler version, and per-sample SHA-256 hashes.

Two local runs produced the same report and identical symbol maps. The base template and the all-sprites sample each produced a 122,732-byte TAP matching its upstream reference.

## Source audit

| Source | What to trace |
| --- | --- |
| `01_BASE_TEMPLATE/main.asm` | Entry at `24500`, hardware and display initialisation, IM 2 setup, and two `HALT`-based game-logic windows. |
| `Engine/sys.a80` | `mainInterrupt`, the dispatch call at `intProc`, and model detection via ROM byte `2899`. The 128K/+2 path uses tile banks 4 and 6. The +2A/+3 path patches those to 1 and 3. |
| `Engine/render.a80` | `renderFrame1`, the 48 unrolled logical rows and `#7FFD` writes, `renderFrame2`, and the attribute buffer. |
| `Engine/tileMapCode.a80`, `Engine/tilesCode.a80`, `Engine/tilesCodeShifted.a80` | Map processing, generated tile routines, and shifted tile variants. |
| `Engine/spritesRender.a80`, `Engine/spritesRenderSMALL.a80`, `Engine/spritesRenderBIG.a80` | Sprite dispatch and the two distinct sprite paths. |
| `05_EXAMPLE_ALL_SPRITES/main.asm`, `11_EXAMPLE_DRAW_TO_BUFFER/main.asm` | Existing workloads for the sprite and direct-buffer measurements. |

For the all-sprites sample, the local symbol map places `mainInterrupt` at `#801D`, `attrBuffer` at `#81CD`, `renderFrame1` at `#8E2D`, and `renderFrame2` at `#9B30`. Use the symbol map from the specific build when setting trace points.

## Emulator evaluation

| Candidate | Documented capabilities and next check |
| --- | --- |
| [zx_go](https://github.com/conorarmstrong/zx_go) | The v1.13.0 source harness can select both machine families and timestamp `#7FFD` directly. The [independent timing comparison](docs/independent-emulator.md) details the +2A contention-origin adjustment. The classic renderer takes `ScreenPage` once per frame. |
| [Fuse](https://fuse-emulator.sourceforge.net/) | Independent comparison candidate with both model families. The installed Win32 build is graphical. Use a headless or instrumented build for automated comparison. |
| [ZEsarUX](https://github.com/chernandezba/zesarux) | Windows v10.3 passed the headless mid-scanline probe and the two-frame all-sprites profile on `128k` and `P2A41`. |
| [ZX Spectrum MCP](https://github.com/retro-vault/zx-spectrum-mcp) | The documented emulator targets the 48K model. This milestone requires the two 128K model families and shadow-screen banking. |

## Headless raster probe

```powershell
python tools/verify_zesarux_raster.py --emulator <zesarux.exe> --assembler <sjasmplus.exe>
```

The probe uses an IM 2 interrupt to start each frame, displays red paper from bank 5, then switches to cyan paper from bank 7 through `#7FFD`. The second build adds one 26 T-state delay iteration. The verifier runs ZEsarUX with null video and audio drivers and inspects BGR24 frame dumps. The paper line above the switch must be entirely red and the line below entirely cyan. All captured transitions must stay within one 8-pixel character cell per model and delay setting. The extra delay must shift the transition by 48 or 56 pixels, which bracket the nominal 52 pixels at this capture granularity.

| ZEsarUX v10.3 model | Paper scanline, zero-based | First cyan pixel at 1,079 iterations | First cyan pixel at 1,080 iterations |
| --- | ---: | ---: | ---: |
| `128k` | 60 | 192 | 248 |
| `P2A41` | 60 | 192 or 200 | 248 |

The upstream `05_EXAMPLE_ALL_SPRITES` TAP also loaded all seven machine-code payload blocks on each model and produced six colours in the final sampled paper region.

## Original-engine timing baseline

```powershell
python tools/profile_ringo8.py --emulator <zesarux.exe> --assembler <sjasmplus.exe> --sample <output-directory>/05_EXAMPLE_ALL_SPRITES
```

The profiler verifies the pinned TAP, recaptures the raster probe, and emits JSON for both models. It requires all 256 phases of the sample's built-in motion. Increase `--seconds` if the host captures too few frames. Add `--full` to retain every routine boundary and paging write, including the emulator frame T-state, scanline and T-state within that scanline. The default report includes one complete pair, routine duration ranges and the latch timing range of each paging write across the capture. See [the timing baseline](docs/timing-baseline.md) for measurements and timestamp validation.

The [dot plotting benchmark](docs/dot-plotting.md) verifies the packed attribute fields and measures the cost of drawing nine player shots with 16, 24 or 32 enemy dots.

The [collision benchmark](docs/bullet-collision.md) checks both bullet colours against 5×5 hitboxes and compares buffer probes with coordinate checks.

The [large-sprite timing experiment](docs/large-sprite-slots.md) measures work that can fit between the stock paging writes when large-sprite drawing is removed.

The [AY playback experiment](docs/ay-playback.md) profiles the archived Blokius tracker player and verifies a 50 Hz delta-stream prototype.

The [projectile integration experiment](docs/projectile-integration.md) runs the full 32-dot workload and scheduled hitbox checks in a temporary copy of the stock engine.

The [projectile motion benchmark](docs/projectile-motion.md) verifies integer trajectories, volley expansion, and retirement at the viewport edges.

## Blokius WIP audit

`Blokius - sprite manager wip 1.zip` rebuilt headlessly with SjASMPlus 1.20.2 using the archive's preconverted assets. The generated TAP and SNA matched the archived binaries byte for byte. The `game` directory contains `main.asm`, `spriteManager.asm`, `hotspotCollision.asm`, `barrelScroll.asm`, and `hud.asm`. Its `music/resources.a80` places the 1,617-byte player at 55000 and the 2,015-byte song at 57158 in bank 0. The player call in `main.asm` is commented out in this WIP. The original `meadows edge 1.vt2` was located alongside its numbered revisions.

The [Blokius timing baseline](docs/blokius-timing.md) follows the unmodified game's barrel scroll through completion and measures the HUD and game slots on both models.

The [Blokius scenery test](docs/blokius-integration.md) checks the WIP's barrel scroll and animated tiles with the new projectile and AY workload.

The [playable barrel-scroll build](docs/gameplay.md) adds keyboard movement, three-way firing, enemy waves, and an incremental score HUD.
