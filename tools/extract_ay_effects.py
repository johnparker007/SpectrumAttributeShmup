"""Extract the game's noise and tone effects from a traced two-pattern module."""

import argparse
import json
from pathlib import Path
import re

from verify_ay_stream import register_pairs


def extract(module, capture):
    parts = re.split(r"^\[(.+)\]\s*$", module, flags=re.MULTILINE)
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    settings = dict(line.split("=", 1) for line in sections["Module"].splitlines() if "=" in line)
    speed = int(settings["Speed"])
    if settings["PlayOrder"] != "L0,1" or speed < 1:
        raise ValueError("Expected a fixed-tempo module playing patterns 0 and 1")
    if not capture.get("passed") or not capture.get("through_loop"):
        raise ValueError("Expected a verified through-loop PT3 capture")

    state, frames = {}, []
    trace = capture["results"][0]
    state.update(register_pairs(trace["initial_writes"]))
    for tick in trace["ticks"]:
        state.update(register_pairs(tick["writes"]))
        frames.append(state.copy())

    effects = []
    start = 0
    for pattern in range(2):
        rows = [line.split("|")[2].split() for line in sections[f"Pattern{pattern}"].splitlines() if "|" in line]
        end = next((row for row, (note, fields, _) in enumerate(rows) if note != "---" and fields[0] == "3"), None)
        if end is None:
            raise ValueError(f"Pattern {pattern} has no sample 3 end marker on channel A")
        active, stop = frames[start:start + end * speed], frames[start + end * speed]
        if not active or not active[0][8] or stop[8] or any(frame[8] > 15 for frame in active):
            raise ValueError(f"Pattern {pattern} must use fixed volume and end with a silent sample 3")
        effects.append((active, stop))
        start += len(rows) * speed
    if start != len(frames):
        raise ValueError("The module and capture disagree on the total duration")

    noise, _ = effects[0]
    shot, mute = effects[1]
    if any(frame[7] & 9 != 1 for frame in noise) or any(frame[7] & 9 != 8 for frame in shot if frame[8]):
        raise ValueError("Expected noise-only explosion and tone-only shot on A")
    return {
        "explosion-noise.bin": bytes([*(frame[6] & 31 for frame in noise), 255]),
        "shot-sound.bin": bytes(value for frame in (*shot, mute)
                               for value in (frame[0], frame[1] & 15, frame[8])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", type=Path, help="editable VT2 corresponding to the traced PT3 export")
    parser.add_argument("reference", type=Path, help="JSON from benchmark_ay.py --pt3 ... --through-loop")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        files = extract(args.module.read_text(encoding="utf-8-sig"),
                        json.loads(args.reference.read_text(encoding="utf-8-sig")))
        args.output.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (args.output / name).write_bytes(data)
    except (OSError, ValueError, IndexError, KeyError) as error:
        parser.exit(1, f"AY effect extraction failed: {error}\n")


if __name__ == "__main__":
    main()
