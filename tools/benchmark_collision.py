"""Compare packed-buffer and coordinate hitboxes for the stock viewport."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from benchmark_dots import CYAN, MODELS, ROW_BYTES, VIEWPORT_OFFSET, YELLOW, fixture
from trace_zesarux import trace
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "collision" / "probe.asm"
MARKERS = ("packed_begin", "packed_end", "coordinate_begin", "coordinate_end", "passed", "failed")


def scenario(count, name):
    if name == "miss":
        # Every shot passes the horizontal test and misses vertically.
        boxes = [(13, (3 * i) % 31) for i in range(15)] + [(59, 0)]
        players = [(13 + i % 3, 41 + i % 7) for i in range(9)]
        enemies = [(59 + i % 5, 7 + i % 41) for i in range(count)]
    elif name == "last":
        boxes = [(59, 43)] * 15 + [(0, 43)]
        players = [(60, i) for i in range(8)] + [(62, 47)]
        enemies = [(i % 5, i % 43) for i in range(count - 1)] + [(4, 47)]
    else:
        # The shot at 58,47 touches box 0 only at x=59, the exact dot which
        # yellow overwrites. Boxes 1 and 3 also have excluded-edge neighbours.
        boxes = [(59, 43), (0, 0), (1, 0), (59, 34)] + [(i, 9) for i in range(11)] + [(59, 43)]
        players = [(58, 47), (5, 0), (57, 35)] + [(20 + i, 20) for i in range(6)]
        enemies = [(59, 47)] + [(20 + i, 15) for i in range(count - 1)]
    return boxes, players, enemies


def prepare(directory, count, name):
    boxes, players, enemies = scenario(count, name)
    fixture(directory, players, enemies)
    (directory / "boxes.bin").write_bytes(bytes(axis for box in boxes for axis in box))
    for colour, label in ((CYAN, "cyan"), (YELLOW, "yellow")):
        table = bytes(int(pair % 8 == colour) + 2 * int(pair // 8 % 8 == colour) for pair in range(256))
        (directory / f"{label}_lut.bin").write_bytes(table)

    def intersects(box, shots, shot_width):
        x, y = box
        assert 0 <= x <= 59 and 0 <= y <= 43
        return any(x <= sx + shot_width - 1 and sx < x + 5 and y <= sy < y + 5 for sx, sy in shots)

    expected = [intersects(box, players, 2) for box in boxes[:-1]] + [intersects(boxes[-1], enemies, 1)]
    if (name == "miss" and any(expected)) or (name == "last" and not all(expected)):
        raise ValueError(f"{name}: fixture is inconsistent with its intended paths")
    if name == "overlap":
        pair = (directory / "expected_enemies.bin").read_bytes()[VIEWPORT_OFFSET + 47 * ROW_BYTES + 59 // 2]
        if expected[:4] != [True, False, True, False] or not expected[-1] or pair // 8 % 8 != YELLOW:
            raise ValueError("Overlap fixture must lose its cyan marker after the yellow layer")
    (directory / "expected.bin").write_bytes(bytes(expected))
    return sum(expected)


def measure(emulator, directory, model):
    report = trace(emulator, directory / "collision.sna", directory / "collision.sym", MARKERS, model, 1)
    events = report["events"]
    names = [event["labels"][0] for event in events]
    if names != list(MARKERS[:-1]):
        raise ValueError(f"{model}: collision benchmark failed or did not complete: {names}")
    packed_begin, packed_end, coordinate_begin, coordinate_end, passed = [event["frame_tstate"] for event in events]
    if not packed_begin < packed_end < coordinate_begin < coordinate_end < passed:
        raise ValueError(f"{model}: collision sample crossed a frame boundary")
    return {"model": model, "packed_tstates": packed_end - packed_begin,
            "coordinate_tstates": coordinate_end - coordinate_begin}


def benchmark(emulator, assembler):
    results = []
    with tempfile.TemporaryDirectory(prefix="ringo8-collision-") as scratch, ThreadPoolExecutor(max_workers=2) as pool:
        for count in (16, 24, 32):
            for name in ("miss", "last", "overlap"):
                directory = Path(scratch) / f"{count}-{name}"
                directory.mkdir()
                hits = prepare(directory, count, name)
                run([assembler, f"-DENEMY_COUNT={count}", "--sym=collision.sym", PROBE], directory)
                timed = list(pool.map(lambda model: measure(emulator, directory, model), MODELS))
                if timed[0]["packed_tstates"] != timed[1]["packed_tstates"] or timed[0]["coordinate_tstates"] != timed[1]["coordinate_tstates"]:
                    raise ValueError(f"Timing disagrees between models for {directory.name}")
                results.extend({"enemy_count": count, "scenario": name, "hit_boxes": hits, **row} for row in timed)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    args = parser.parse_args()
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        assembler_version = next(line for line in run([assembler, "--help"], assembler.parent).splitlines()
                                 if line.startswith("SjASMPlus"))
        results = benchmark(emulator, assembler)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Collision benchmark failed: {error}\n")
    json.dump({"emulator": version, "assembler": assembler_version, "results": results, "passed": True},
              sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
