# Ringo-8 all-sprites timing baseline

The workload is `05_EXAMPLE_ALL_SPRITES` from upstream revision `452fcc86d4ed72574a5cced6e8e5d9184d44c0e7`, assembled with SjASMPlus 1.20.2 and verified byte for byte against the published TAP. ZEsarUX 10.3 ran with null video and audio drivers on `128k` and `P2A41`. The test supplies no input and requires a complete 256-step motion cycle. The recorded run measured 392 frame pairs on 128K and 389 on +2A, covering both tile banks and every motion phase on each model. Other maps, sprite modes, and Blokius require their own measurements.

## Two-frame schedule

The counter wraps at 70,908 T-states, with 311 lines of 228 T-states. Consecutive IM 2 entries are checked using the debugger's accumulated counter. `renderFrame1` returns after the 48 attribute rows and the first tile pass. `renderFrame2` finishes the tile pass, prepares the next map and draws the sprites. The interrupt restores the game page and registers before the game switches the next interrupt target and enters its logic slot.

| Frame-relative timestamp from one observed pair | 128K | +2A |
| --- | ---: | ---: |
| Frame 1 IM 2 entry → attribute rows → first tile pass | 30 → 289 → 22,500 | 30 → 289 → 22,547 |
| Frame 1 renderer return → logic start → next `HALT` | 58,238 → 58,487 → 60,472 | 58,285 → 58,534 → 60,519 |
| Frame 2 IM 2 entry → second tile pass → map preparation → sprite entry | 29 → 266 → 9,459 → 13,701 | 32 → 269 → 9,462 → 13,704 |
| Frame 2 renderer return → logic start → next `HALT` | 58,298 → 58,547 → 58,557 | 58,301 → 58,550 → 58,560 |

| Measured span, in T-states | 128K | +2A |
| --- | ---: | ---: |
| Frame 1 render, entry to interrupt call return | 58,061 | 58,108–58,109 |
| Attribute rows through first tile entry, including paging | 22,211 | 22,258–22,259 |
| First tile pass | 35,718 | 35,718 |
| Frame 2 render, entry to interrupt call return | 58,122 | 58,122 |
| Second tile pass | 9,166 | 9,166 |
| Prepare next tile map | 4,212 | 4,212 |
| Sprite rendering, including setup and cleanup | 44,597 | 44,597 |
| First eight small sprites | 7,269 | 7,269 |
| Eight large sprites | 29,209 | 29,209 |
| Last eight small sprites | 7,269 | 7,269 |
| Frame 1 logic slot to frame edge, minimum | 12,421 | 12,374 |
| Frame 1 sample logic to next `HALT`, maximum | 1,985 | 1,985 |
| Frame 1 remaining to frame edge at `HALT`, minimum | 10,436 | 10,389 |
| Frame 2 logic slot to frame edge, minimum | 12,361 | 12,358 |
| Frame 2 sample logic to next `HALT`, maximum | 10 | 10 |
| Frame 2 remaining to frame edge at `HALT`, minimum | 12,351 | 12,348 |

The two tile passes total 44,884 T-states, plus 4,212 for map preparation. Frame 1 logic consists of 157 T-states for scrolling and 1,828 for sprite motion, including the calls. Frame 2 only jumps back to the first `HALT`. The logic window starts after the interrupt dispatch patch. Its remaining time ends at video-frame wrap, so reserve time to reach and execute `HALT` before treating that figure as a scheduling budget. Sprite group durations use the group dispatch labels. The whole-sprite duration also includes the intervening jumps, list setup and stack restoration.

## Paging timestamp validation

The sample performs 26 writes to `#7FFD` in Frame 1 and 27 in Frame 2, including one page restore per interrupt. Bit 3 selects screen bank 5 or 7. The low three bits select the paged RAM bank. The tile code uses banks 4 and 6 on 128K and banks 1 and 3 on +2A. The profiler checks the byte sequence against the selected tile bank and confirms the port address and opcode at every watched site. All measured sample writes take 12 T-states. ZEsarUX applies each at instruction start +9, three T-states before the following guest instruction. The JSON includes every slot's PC, possible values and frame-relative latch ranges, and `--full` includes the individual writes.

The Windows v10.3 binary used for direct checks has SHA-256 `aa6dfb86a4c06b2b09e91d77aa30f1d67f2ed91bcea982ff00dab83d9da7cd38`. Its `_out_port_spectrum` calls `_out_port_spectrum_no_time` after early port timing and before late port timing. GDB 7.6.1 sampled `t_estados`, the guest PC and the output byte at the latter call. The 53 ordered `(PC, T-state, byte)` triples for one pair on each model matched pairs in the profiler output. The same hook timestamped the raster probe's `0x18` write. The [independent zx_go check](independent-emulator.md) records where a second implementation agrees and where the +2A attribute-transfer timing still differs.

| Model | Shadow latch at 1,079 loops | Shadow latch at 1,080 loops | First cyan pixel, early → late |
| --- | ---: | ---: | --- |
| 128K | 28,152 | 28,173 | 192 → 248 |
| +2A | 28,147 or 28,149 | 28,175 | 192 or 200 → 248 |

Both probes switch on paper row 60. The extra iteration is 26 T-states. On 128K the early `OUT` has contention and the late one does not, giving a 21 T-state latch shift. The +2A probe has a two-T-state interrupt-entry variation and its `OUT` takes 12 T-states. The video check allows one 8-pixel character cell per measured edge. In particular, the 128K video edge moves 56 pixels while the latch moves 21 T-states. Use the debugger values for emulator latch timing and the captured picture to check where the displayed screen changes.
