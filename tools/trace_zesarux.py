"""Trace frame-relative instruction boundaries in headless ZEsarUX 10.3."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from verify_zesarux_raster import run


SYMBOL = re.compile(r"^(\S+): EQU 0x([0-9A-Fa-f]+)$", re.MULTILINE)
HIT = re.compile(r"Catch breakpoint: PC=([0-9A-F]{4})H\n(\d+)\n")


def read_symbols(symbols):
    return {name: int(value, 16) for name, value in SYMBOL.findall(symbols.read_text())}


def breakpoint_log(emulator, image, model, seconds, breakpoints, fast_autoload=False, keyboard_spool=None):
    if len(breakpoints) > 100:
        raise ValueError("ZEsarUX supports up to 100 breakpoints")
    image = image.resolve(strict=True)
    if image.suffix.lower() == ".tap":
        load = ["--tape", image]
    elif image.suffix.lower() == ".sna":
        load = ["--snap-no-change-machine", "--snap", image]
    else:
        raise ValueError("Expected a .tap or .sna image")
    command = [
        emulator, "--noconfigfile", "--vo", "null", "--ao", "null",
        "--disable-debug-console-win", "--nowelcomemessage",
        "--stats-disable-check-updates", "--stats-disable-check-yesterday-users",
        "--machine", model, "--realvideo", *load, "--enable-breakpoints",
        "--exit-after", str(seconds), "--quickexit", "--verbose", "2",
    ]
    if fast_autoload:
        command.append("--fastautoload")
    if keyboard_spool is not None:
        command.extend(["--keyboardspoolfile", keyboard_spool, "--keyboardspoolfile-play",
                        "--keyboardspoolfile-keylength", "8"])
    for index, (condition, expression) in enumerate(breakpoints, 1):
        command.extend([
            "--set-breakpoint", str(index), condition,
            "--set-breakpointaction", str(index), f"printe {expression}",
        ])
    return run(command, emulator.parent, timeout=max(25, seconds + 25))


def trace(emulator, image, symbols, labels, model, seconds):
    addresses = read_symbols(symbols)
    points = {}
    for label in labels:
        address = addresses.get(label)
        if address is None or not 0 <= address <= 0xFFFF:
            raise ValueError(f"Expected a 16-bit address for {label}")
        points.setdefault(f"{address:04X}", []).append(label)
    breakpoints = [(f"PC={address}H", "TSTATES") for address in points]
    log = breakpoint_log(emulator, image, model, seconds, breakpoints)
    events = [
        {"pc": int(address, 16), "labels": points[address], "frame_tstate": int(tstate)}
        for address, tstate in HIT.findall(log)
    ]
    if not events or log.count("Catch breakpoint: PC=") != len(events):
        raise ValueError("Expected a T-state for every breakpoint hit")
    version = run([emulator, "--version"], emulator.parent)
    banner = next(line for line in version.splitlines() if line.startswith("ZEsarUX v"))
    return {"emulator": banner, "model": model, "image": image.name, "events": events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--symbols", required=True, type=Path)
    parser.add_argument("--model", required=True, choices=("128k", "P2A41"))
    parser.add_argument("--seconds", type=int, default=8, choices=range(1, 16), metavar="1-15")
    parser.add_argument("labels", nargs="+")
    args = parser.parse_args()
    try:
        result = trace(
            args.emulator.resolve(strict=True), args.image, args.symbols,
            args.labels, args.model, args.seconds,
        )
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Timing trace failed: {error}\n")
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
