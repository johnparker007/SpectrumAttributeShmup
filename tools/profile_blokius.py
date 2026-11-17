"""Rebuild the Blokius WIP and measure its unmodified, no-input game slots."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from build_ringo8 import LAUNCH
from profile_ringo8 import FRAME, HIT, MODELS, OUT_OPCODE, PORTS
from trace_zesarux import breakpoint_log, read_symbols
from verify_zesarux_raster import run


TAP_SHA256 = "d4d7b336e8cccaa4799a8dcad4152044e3c0e064824715ed061a6ac7d92653fb"
ARCHIVE = Path(__file__).resolve().parents[1] / "vendor" / "blokius-wip1.zip"


def build(archive_path, assembler, directory):
    with ZipFile(archive_path) as archive:
        archive.extractall(directory)
    root, = directory.iterdir()
    game = root / "game"
    tap = game / "main.tap"
    snapshot = game / "main.sna"
    expected_tap, expected_snapshot = tap.read_bytes(), snapshot.read_bytes()
    if hashlib.sha256(expected_tap).hexdigest() != TAP_SHA256:
        raise ValueError("Expected the Blokius sprite-manager WIP 1 archive")
    source = game / "main.asm"
    data, matches = LAUNCH.subn(rb"\1; \2", source.read_bytes())
    if matches != 1:
        raise ValueError("Unexpected Blokius launcher")
    source.write_bytes(data)
    tap.unlink()
    snapshot.unlink()
    run([assembler, "--sym=main.sym", "main.asm"], game)
    if (tap.read_bytes(), snapshot.read_bytes()) != (expected_tap, expected_snapshot):
        raise ValueError("Blokius TAP or snapshot differs from the archived game/ build")
    return game


def capture(emulator, game, model, seconds, paging=False, scenery=False):
    symbols = read_symbols(game / "main.sym")
    main = symbols["mainLoop"]
    # Byte offsets come from the assembled SET_RENDER_FRAME and game loop
    # in the hash-checked WIP. The HALT fall-through can fire before the IRQ.
    markers = {"irq": symbols["mainInterrupt"], "frame1": symbols["renderFrame1"],
               "frame2": symbols["renderFrame2"], "render_return": symbols["intProc"] + 3,
               "halt1": main + 0x07, "logic1": main + 0x0E, "scroll": main + 0x12,
               "player": main + 0x15, "sprite_manager": main + 0x18, "score_copy": main + 0x1B,
               "halt2": main + 0x2C, "logic2": main + 0x33, "hud": main + 0x37,
               "after_hud": main + 0x3A}
    if scenery:
        markers = {name: markers[name] for name in ("irq", "frame1", "frame2", "render_return")}
        markers.update({name: symbols[name] for name in ("halt1", "halt2")})
    conditions = {f"PC={address:04X}H": name for name, address in markers.items()}
    scroll_complete = f"PEEK({symbols['barrelScrollComplete']:04X}H)"
    expressions = {"irq": "TSTATESP", "halt2": f"TSTATES*256+{scroll_complete}"}
    if paging:
        # The pinned WIP relocates the fixed-bank renderer by #900.
        for address, register in PORTS.items():
            pc = address + (0x900 if address < 0xC000 else 0)
            condition = f"PC={pc:04X}H AND BC=7FFDH AND PEEKW(PC)={OUT_OPCODE[register]:02X}EDH"
            conditions[condition] = condition
            expressions[condition] = f"TSTATES*256+{register}"
            after = f"PC={pc + 2:04X}H AND BC=7FFDH"
            conditions[after] = after
            expressions[after] = "TSTATES"
    log = breakpoint_log(emulator, game / "main.tap", model, seconds,
                         [(condition, expressions.get(name, "TSTATES")) for condition, name in conditions.items()],
                         fast_autoload=True)
    events = HIT.findall(log)
    if not events or len(events) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: incomplete WIP debugger log")
    frames = []
    for condition, raw in events:
        name, value = conditions[condition], int(raw)
        if name == "irq":
            frames.append({"start": value // FRAME, "irq": value % FRAME, "paging": []})
        elif frames:
            if name.startswith("PC="):
                frames[-1]["paging"].append((name, value))
                continue
            if name == "halt2":
                value, frames[-1]["scroll_complete"] = divmod(value, 256)
            frames[-1][name] = value
    first = next(index for index, frame in enumerate(frames) if "frame1" in frame)
    return frames[first:]


def profile(emulator, game, model, seconds):
    frames = capture(emulator, game, model, seconds)
    measurements = {1: [], 2: []}
    scrolling = 0
    for index, (frame, following) in enumerate(zip(frames, frames[1:])):
        phase = index % 2 + 1
        halt_name = f"halt{3 - phase}"
        render, halt = frame[f"frame{phase}"], frame[halt_name]
        logic = frame[f"logic{phase}"]
        if following["start"] != frame["start"] + 1 or not frame["irq"] < render < frame["render_return"] < logic < halt < FRAME:
            raise ValueError(f"{model}: irregular frame or game-slot overrun at {index}")
        metrics = {"render": frame["render_return"] - render, "logic_to_halt": halt - logic,
                   "remaining_before_frame_edge": FRAME - halt}
        if phase == 1:
            scrolling += frame["scroll_complete"] == 0
            metrics.update({"scroll_call": frame["player"] - frame["scroll"],
                            "player_call": frame["sprite_manager"] - frame["player"],
                            "sprite_manager_call": frame["score_copy"] - frame["sprite_manager"]})
        else:
            metrics["hud_call"] = frame["after_hud"] - frame["hud"]
        measurements[phase].append(metrics)
    if not 0 < scrolling < len(measurements[1]):
        raise ValueError(f"{model}: capture ended before completing the map scroll. Increase --seconds.")
    phases = []
    for phase, samples in measurements.items():
        ranges = {}
        for name in samples[0]:
            values = [sample[name] for sample in samples]
            ranges[name] = [min(values), max(values)]
        phases.append({"phase": phase, "frames": len(samples), "tstate_ranges": ranges})
    return {"model": model, "scrolling_game_ticks": scrolling, "schedule": phases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS, help="default: profile both models")
    parser.add_argument("--seconds", type=int, default=145, help="wall-clock capture length per model")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        assembler_version = next(line for line in run([assembler, "--help"], assembler.parent).splitlines()
                                 if line.startswith("SjASMPlus"))
        models = (args.model,) if args.model else MODELS
        with tempfile.TemporaryDirectory(prefix="blokius-profile-") as scratch:
            game = build(args.archive, assembler, Path(scratch))
            results = [profile(emulator, game, model, args.seconds) for model in models]
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Blokius profiling failed: {error}\n")
    json.dump({"emulator": version, "assembler": assembler_version, "tap_sha256": TAP_SHA256,
               "input": "none", "results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
