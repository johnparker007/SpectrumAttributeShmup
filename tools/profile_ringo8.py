"""Verify the paging and two-frame schedule of the upstream all-sprites sample."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from build_ringo8 import REVISION
from trace_zesarux import breakpoint_log, read_symbols, trace
from verify_zesarux_raster import PAPER_SCANLINE, PROBE, capture, run


MODELS = ("128k", "P2A41")
LINE = 228
FRAME = 311 * LINE
TAP_SHA256 = "4c45c4b5799b14e9d7eabc6d72d732a3fd637d1dadef7c793b62d8fcb55f66b3"
HIT = re.compile(r"Catch breakpoint: (PC=[^\n]+)\n(\d+)\n")
OUT_OPCODE = {"D": 0x51, "E": 0x59, "H": 0x61, "L": 0x69, "A": 0x79}

# OUT (C),r instructions from the SjASMPlus listing for the pinned TAP.
# The tile banks have identical OUT sites and alternate at each of these jumps.
PORTS = {
    0x811B: "A",  # swapPage (interrupt epilogue)
    0x8E3B: "L", 0x9739: "H", 0x9832: "L", 0x9929: "H", 0x9A29: "L",
    0x9B27: "E", 0x9B3B: "E", 0x9B4C: "L",
    0xC21B: "H", 0xC361: "L",  # small sprites
    0xC431: "H", 0xC4E2: "L",  # large sprites
    **{0xC12B + 602 * row: "D" for row in range(10)},
    **{0xC258 + 602 * row: "E" for row in range(9)},
}
FRAME_MARKERS = (
    ("irq", "renderFrame1", "attribute_rows", "tiles1_begin", "tiles1_end", "render_return",
     "resume1", "logic1_begin", "move_sprites_call", "halt2"),
    ("irq", "renderFrame2", "tiles2_begin", "tiles2_end", "map_begin", "map_end", "sprites_begin",
     "small_begin", "small_end", "large_begin", "large_end", "small_begin", "small_end",
     "sprites_stack_restore", "render_return", "resume2", "logic2_begin", "halt1"),
)


def collect(emulator, tap, symbols, model, seconds):
    sym = read_symbols(symbols)
    markers = {
        "irq": sym["mainInterrupt"],
        "render_return": sym["intProc"] + 3,
        "renderFrame1": sym["renderFrame1"],
        "renderFrame2": sym["renderFrame2"],
        "attribute_rows": sym["renderLine00"],
        "tiles1_begin": sym["renderTiles"],
        "tiles1_end": sym["renderTiles1Exit"],
        "tiles2_begin": sym["renderTiles2"],
        "tiles2_end": sym["renderTiles2Exit"],
        "map_begin": sym["processTileMap"],
        "map_end": sym["renderTiles2Exit"] + 6,
        "sprites_begin": sym["doSprites"],
        "small_begin": sym["reRender"],
        "small_end": sym["patchJP"],
        "large_begin": sym["continueJP"],
        "large_end": sym["spritesSP"] - 13,
        "sprites_stack_restore": sym["spritesSP"],
        "halt1": sym["mainLoop"],
        "resume1": sym["mainLoop"] + 1,
        "logic1_begin": sym["mainLoop"] + 7,
        "move_sprites_call": sym["mainLoop"] + 10,
        "halt2": sym["mainLoop"] + 13,
        "resume2": sym["mainLoop"] + 14,
        "logic2_begin": sym["mainLoop"] + 20,
    }

    breakpoints = {}
    for name, address in markers.items():
        expression = "TSTATES"
        if name == "irq":
            expression = "TSTATESP"
        elif name == "logic1_begin":
            expression = f"TSTATES*256+PEEK({sym['sinPointerX'] + 1:04X}H)"
        breakpoints[f"PC={address:04X}H"] = (name, expression)
    for pc, register in PORTS.items():
        condition = f"PC={pc:04X}H AND BC=7FFDH AND PEEKW(PC)={OUT_OPCODE[register]:02X}EDH"
        breakpoints[condition] = ("out", f"TSTATES*256+{register}")
        breakpoints[f"PC={pc + 2:04X}H AND BC=7FFDH"] = ("after_out", "TSTATES")

    log = breakpoint_log(emulator, tap, model, seconds,
                         [(cond, expr) for cond, (_, expr) in breakpoints.items()],
                         fast_autoload=True)
    hits = HIT.findall(log)
    if not hits or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: incomplete debugger log")
    frames = []
    for condition, value in hits:
        name = breakpoints[condition][0]
        value = int(value)
        if name == "irq":
            tstate = value % FRAME
            frames.append({"start": value - tstate, "events": [(name, tstate)], "writes": []})
        elif frames:
            frame = frames[-1]
            pc = int(condition[3:7], 16)
            if name == "out":
                tstate, byte = divmod(value, 256)
                frame["writes"].append({"pc": f"{pc:04X}", "value": byte, "before": tstate})
            elif name == "after_out":
                # A tile bank can execute the same address as a sprite-bank
                # fall-through. Only pair the hit with its own OUT site.
                if not frame["writes"]:
                    continue
                write = frame["writes"][-1]
                if int(write["pc"], 16) + 2 != pc or "after" in write:
                    continue
                if value - write["before"] != 12:
                    raise ValueError(f"{model}: unexpected OUT (C),r boundaries at {pc:04X}")
                write["after"] = value
                # Verified in ZEsarUX 10.3: 8 fetch Ts, 1 early I/O T, latch,
                # then 3 late I/O Ts. A measured 12 Ts excludes all wait states.
                write["latch"] = value - 3
                write["scanline"], write["line_tstate"] = divmod(value - 3, LINE)
            else:
                if name == "logic1_begin":
                    value, frame["motion_phase"] = divmod(value, 256)
                frame["events"].append((name, value))
    return frames


def measure(frame, phase):
    expected = FRAME_MARKERS[phase - 1]
    # The paged tile code can hit an address used by a different render phase.
    events = [(name, tstate) for name, tstate in frame["events"] if name in expected]
    if tuple(name for name, _ in events) != expected:
        raise ValueError(f"Frame {phase} has unexpected routine boundaries: {events}")
    frame["events"] = events
    points = {}
    for name, tstate in events:
        points.setdefault(name, []).append(tstate)

    def point(name, occurrence=0):
        return points[name][occurrence]

    def span(begin, end, occurrence=0):
        return point(end, occurrence) - point(begin, occurrence)

    render = f"renderFrame{phase}"
    logic_begin = point(f"logic{phase}_begin")
    halt = point(f"halt{3 - phase}")
    metrics = {
        "render": span(render, "render_return"),
        "irq_to_resume": span("irq", f"resume{phase}"),
        "logic_window_to_frame_edge": FRAME - logic_begin,
        "logic_used_through_next_halt": halt - logic_begin,
        "remaining_before_frame_edge": FRAME - halt,
    }
    if phase == 1:
        metrics.update({
            "attribute_transfer_and_paging": point("tiles1_begin") - point("attribute_rows"),
            "tiles_first_pass": span("tiles1_begin", "tiles1_end"),
            "scroll_logic_with_call": span("logic1_begin", "move_sprites_call"),
            "sprite_motion_logic_with_call": span("move_sprites_call", "halt2"),
        })
    else:
        metrics.update({
            "tiles_second_pass": span("tiles2_begin", "tiles2_end"),
            "prepare_next_tile_map": span("map_begin", "map_end"),
            "sprites_total": span("sprites_begin", "render_return"),
            "small_sprites_first_eight": span("small_begin", "small_end"),
            "large_sprites_eight": span("large_begin", "large_end"),
            "small_sprites_last_eight": span("small_begin", "small_end", 1),
        })
    if sorted(tstate for _, tstate in events) != [tstate for _, tstate in events] or min(metrics.values()) <= 0:
        raise ValueError(f"Frame {phase} has inconsistent routine boundaries")
    return metrics


def expected_writes(tiles):
    first = [0x17, 0x1F, 0x17, 0x1F, 0x17, 0x18 + tiles]
    first += [0x10 + tiles, 0x18 + tiles] * 9 + [0x10 + tiles, 0x10]
    second = [0x18 + tiles, 0x10] + [0x18, 0x10] * 12 + [0x10]
    return first, second


def summarise(frames, model, full):
    # The closing interrupt establishes that the preceding frame was complete.
    metrics = {1: [], 2: []}
    phase_frames = {1: [], 2: []}
    motion = []
    tile_banks = (4, 6) if model == "128k" else (1, 3)
    exercised_banks = set()
    for index, (frame, following) in enumerate(zip(frames, frames[1:])):
        phase = index % 2 + 1
        values = [write["value"] for write in frame["writes"]]
        if phase == 1:
            tiles = values[5] - 0x18
            exercised_banks.add(tiles)
        expected = expected_writes(tiles)[phase - 1]
        if following["start"] - frame["start"] != FRAME:
            raise ValueError(f"{model}: missing interrupt or unexpected frame period")
        if (tiles not in tile_banks or values != expected
                or any("latch" not in write for write in frame["writes"])):
            raise ValueError(f"{model}: unexpected paging sequence at frame {index}")
        metrics[phase].append(measure(frame, phase))
        phase_frames[phase].append(frame)
        if phase == 1:
            motion.append(frame["motion_phase"])
    if (len(metrics[2]) < 256 or len(set(motion[:256])) != 256
            or any((a + 1) % 256 != b for a, b in zip(motion, motion[1:]))):
        raise ValueError(f"{model}: captured {len(metrics[2])} pairs and {len(set(motion))} motion phases. "
                         "Increase --seconds to cover all 256 phases.")
    if exercised_banks != set(tile_banks):
        raise ValueError(f"{model}: expected both tile banks, saw {sorted(exercised_banks)}")

    summary = []
    for phase, samples in phase_frames.items():
        timing = {}
        for name in metrics[phase][0]:
            values = [sample[name] for sample in metrics[phase]]
            timing[name] = [min(values), max(values)]
        paging = []
        for column in zip(*(frame["writes"] for frame in samples)):
            pc = column[0]["pc"]
            if any(write["pc"] != pc for write in column):
                raise ValueError(f"{model}: inconsistent OUT site at frame phase {phase}")
            times_by_value = {}
            for write in column:
                times_by_value.setdefault(write["value"], []).append(write["latch"])
            variants = [{"value": value, "latch_tstate_range": [min(times), max(times)]}
                        for value, times in sorted(times_by_value.items())]
            paging.append({"pc": pc, "writes": variants})
        summary.append({"phase": phase, "frames": len(samples), "duration_ranges": timing,
                        "paging": paging, "first_frame": samples[0]})
    result = {"model": model, "tstates_per_frame": FRAME, "tstates_per_scanline": LINE,
              "motion_phases": len(set(motion)), "schedule": summary}
    if full:
        result["frames"] = frames[:-1]
    return result


def probe_latch(model, before, after):
    def delay(tstate):
        line, offset = divmod(tstate - 14361, LINE)
        return (6, 5, 4, 3, 2, 1, 0, 0)[offset % 8] if 0 <= line < 192 and offset < 128 else 0

    latch = before + 9
    end = latch + 3
    if model == "128k":
        latch += delay(before + 8)
        end = latch
        for _ in range(3):
            end += delay(end) + 1
    if end != after:
        raise ValueError(f"{model}: probe OUT ended at {after}, predicted {end}")
    return latch


def verify_probe(emulator, assembler, model):
    results = []
    with tempfile.TemporaryDirectory(prefix="ringo8-timing-probe-") as directory:
        scratch = Path(directory)
        snapshot = scratch / "shadow_screen.sna"
        symbols = scratch / "shadow.sym"
        labels = ["show_normal", "normal_shown", "show_shadow", "shadow_shown"]
        for loops in (1079, 1080):
            run([assembler, f"-DDELAY_LOOPS={loops}", f"--sym={symbols}", PROBE], scratch)
            events = trace(emulator, snapshot, symbols, labels, model, 2)["events"]
            if len(events) % 4:
                # The wall-clock stop can land inside the last probe frame.
                events = events[:len(events) // 4 * 4]
            latches = set()
            positions = capture(emulator, snapshot, model)
            for start in range(0, len(events), 4):
                cycle = events[start:start + 4]
                if [event["labels"][0] for event in cycle] != labels:
                    raise ValueError(f"{model}: unexpected raster probe instruction order")
                normal, normal_end, shadow, shadow_end = [event["frame_tstate"] for event in cycle]
                probe_latch(model, normal, normal_end)
                latches.add(probe_latch(model, shadow, shadow_end))
                if shadow - normal != 26 * loops + 34:
                    raise ValueError(f"{model}: probe delay disagrees with the assembled loop")
            if not latches or any(t // LINE != 63 + PAPER_SCANLINE for t in latches):
                raise ValueError(f"{model}: probe latch and rendered paper line disagree")
            results.append({"loops": loops, "shadow_latch_tstates": sorted(latches), "first_cyan_x": positions})
    early, late = results
    for a in early["shadow_latch_tstates"]:
        for b in late["shadow_latch_tstates"]:
            for x1 in early["first_cyan_x"]:
                for x2 in late["first_cyan_x"]:
                    # Separate captures, with an 8-pixel tolerance at each edge.
                    if x2 <= x1 or abs(x2 - x1 - 2 * (b - a)) > 16:
                        raise ValueError(f"{model}: probe latch shift disagrees with the captured raster")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True, help="build output directory for 05_EXAMPLE_ALL_SPRITES")
    parser.add_argument("--model", choices=MODELS, help="default: check both models")
    parser.add_argument("--seconds", type=int, default=90, help="wall-clock capture length per model")
    parser.add_argument("--full", action="store_true", help="include routine events and writes for every frame")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        tap = args.sample / "main.tap"
        if hashlib.sha256(tap.read_bytes()).hexdigest() != TAP_SHA256:
            raise ValueError("Expected the byte-identical upstream all-sprites TAP")
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        if not version.startswith("ZEsarUX v.10.3 "):
            raise ValueError("This paging timestamp verifier requires ZEsarUX 10.3")
        assembler_version = next(line for line in run([assembler, "--help"], assembler.parent).splitlines()
                                 if line.startswith("SjASMPlus"))
        results = []
        for model in (args.model,) if args.model else MODELS:
            probe = verify_probe(emulator, assembler, model)
            frames = collect(emulator, tap, args.sample / "main.sym", model, args.seconds)
            result = summarise(frames, model, args.full)
            result["raster_probe"] = probe
            results.append(result)
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Ringo-8 profiling failed: {error}\n")
    json.dump({"upstream_revision": REVISION, "tap_sha256": TAP_SHA256, "emulator": version,
               "assembler": assembler_version, "input": "none (built-in sample motion)",
               "models": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
