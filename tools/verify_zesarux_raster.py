"""Check mid-scanline shadow-screen switching from headless ZEsarUX video."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


PROBE = Path(__file__).resolve().parents[1] / "tests" / "raster" / "shadow_screen.asm"
WIDTH, HEIGHT = 352, 304
PAPER_X, PAPER_Y, PAPER_WIDTH = 48, 56, 256
RED, CYAN = b"\x00\x00\xff", b"\xff\xff\x00"  # BGR24
PAPER_SCANLINE = 60


def run(command, cwd):
    completed = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, errors="replace",
        timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log = completed.stdout + completed.stderr
    if completed.returncode:
        raise ValueError(f"{Path(command[0]).name} exited {completed.returncode}:\n{log}")
    return log


def paper_row(frame, y):
    start = 3 * ((PAPER_Y + y) * WIDTH + PAPER_X)
    return frame[start:start + 3 * PAPER_WIDTH]


def capture(emulator, snapshot, model):
    video = snapshot.parent / f"{model}.raw"
    log = run([
        emulator, "--noconfigfile", "--vo", "null", "--ao", "null",
        "--disable-debug-console-win", "--nowelcomemessage",
        "--stats-disable-check-updates", "--stats-disable-check-yesterday-users",
        "--machine", model, "--realvideo", "--snap-no-change-machine",
        "--snap", snapshot, "--exit-after", "3", "--quickexit",
        "--verbose", "2", "--vofile", video,
    ], emulator.parent)
    if not re.search(r"Writing video output file.*352 X 304, bgr24", log):
        raise ValueError(f"Unexpected capture format for {model}:\n{log}")

    frame_bytes = WIDTH * HEIGHT * 3
    transitions = set()
    with video.open("rb") as recording:
        while frame := recording.read(frame_bytes):
            if len(frame) != frame_bytes:
                raise ValueError(f"Truncated video for {model}")
            if (paper_row(frame, PAPER_SCANLINE - 1) != RED * PAPER_WIDTH
                    or paper_row(frame, PAPER_SCANLINE + 1) != CYAN * PAPER_WIDTH):
                raise ValueError(f"Expected red above and cyan below paper line {PAPER_SCANLINE} on {model}")
            row = paper_row(frame, PAPER_SCANLINE)
            red_bytes = row.find(CYAN)
            x = red_bytes // 3
            if not 0 < x < PAPER_WIDTH or row != RED * x + CYAN * (PAPER_WIDTH - x):
                raise ValueError(f"Expected a red-to-cyan transition within paper line {PAPER_SCANLINE} on {model}")
            transitions.add(x)
    if not transitions or max(transitions) - min(transitions) > 8:
        raise ValueError(f"Expected a transition within one character cell on {model}, got {sorted(transitions)}")
    return sorted(transitions)


def verify(emulator, assembler):
    version_lines = run([emulator, "--version"], emulator.parent).splitlines()
    version = next((line for line in version_lines if line.startswith("ZEsarUX v")), None)
    if version is None:
        raise ValueError("Could not identify the ZEsarUX version")
    assembler_help = run([assembler, "--help"], assembler.parent).splitlines()
    assembler_version = next((line for line in assembler_help if line.startswith("SjASMPlus")), None)
    if assembler_version is None:
        raise ValueError("Could not identify the SjASMPlus version")
    results = []
    with tempfile.TemporaryDirectory(prefix="zesarux-raster-") as directory:
        scratch = Path(directory)
        for loops in (1079, 1080):
            run([assembler, f"-DDELAY_LOOPS={loops}", PROBE], scratch)
            snapshot = scratch / "shadow_screen.sna"
            for model in ("128k", "P2A41"):
                positions = capture(emulator, snapshot, model)
                results.append({"model": model, "delay_loops": loops,
                                "paper_scanline": PAPER_SCANLINE, "first_cyan_x": positions})
    shifts_by_model = {}
    for early, late in zip(results[:2], results[2:]):
        shifts = {end - start for start in early["first_cyan_x"] for end in late["first_cyan_x"]}
        if not shifts <= {48, 56}:
            raise ValueError(f"A 26 T-state delay shifted {early['model']} by {sorted(shifts)} pixels")
        shifts_by_model[early["model"]] = sorted(shifts)
    return {"emulator": version, "assembler": assembler_version, "added_tstates": 26,
            "switch_shift_pixels": shifts_by_model, "results": results, "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", required=True, type=Path)
    parser.add_argument("--assembler", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.emulator.resolve(strict=True), args.assembler.resolve(strict=True))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Raster verification failed: {error}\n")
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
