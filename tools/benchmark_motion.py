"""Verify and time integer motion for three volleys and 16–32 enemy dots."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from benchmark_dots import MODELS
from trace_zesarux import trace
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "dots" / "motion.asm"
MARKERS = ("players_begin", "players_end", "enemies_begin", "enemies_end", "passed", "failed")
STEPS = ((0,) * 8, (0, -1) * 4, (0, 1) * 4, (0, 0, 0, -1) * 2, (0, 0, 0, 1) * 2,
         (-1,) * 8, (1,) * 8, (-2, -1) * 4)
DEAD = 255


def step(enemies, volleys):
    moved = []
    for x, y, index in enemies:
        if x in (0, DEAD):
            moved.append((DEAD, y, index))
            continue
        path, phase = divmod(index, 8)
        phase = (phase + 1) % 8
        next_y = y + STEPS[path][phase]
        index = 8 * path + phase
        moved.append((x - 1, next_y, index) if 0 <= next_y < 48 else (DEAD, y, index))
    next_volleys, shots = [], []
    for x, y, age in volleys:
        if x >= 62:
            next_volleys.append((DEAD, y, age))
            shots.extend([(DEAD, 0)] * 3)
            continue
        x += 1
        age += 1
        spread = age // 2
        next_volleys.append((x, y, age))
        shots.extend((x, py) if 0 <= py < 48 else (DEAD, 0) for py in (y - spread, y, y + spread))
    return moved, next_volleys, shots


def fixture(directory, count, edges):
    enemies = [(12 + (i * 7) % 52, 10 + (i * 11) % 28, 8 * (i % len(STEPS)) + (3 * i + i // 8) % 8)
               for i in range(count)]
    volleys = [(12, 19, 4), (29, 27, 8), (47, 34, 12)]
    if edges:
        enemies[:4] = [(0, 20, 0), (11, 0, 5 * 8), (12, 47, 6 * 8), (DEAD, 10, 0)]
        volleys = [(61, 0, 4), (51, 47, 3), (62, 20, 3)]
    original = [*enemies, *volleys, *([(0, 0)] * 9)]
    (directory / "initial.bin").write_bytes(bytes(value for record in original for value in record))
    moved, next_volleys, shots = step(enemies, volleys)
    expected = [*moved, *next_volleys, *shots]
    (directory / "expected.bin").write_bytes(bytes(value for record in expected for value in record))
    (directory / "trajectories.bin").write_bytes(bytes(step % 256 for path in STEPS for step in path))


def measure(emulator, directory, model):
    results = trace(emulator, directory / "motion.sna", directory / "motion.sym", MARKERS, model, 1)
    events = results["events"]
    if [event["labels"][0] for event in events] != list(MARKERS[:-1]):
        raise ValueError(f"{model}: motion state did not match the reference")
    start, end, enemy_start, enemy_end, passed = (event["frame_tstate"] for event in events)
    if not start < end < enemy_start < enemy_end < passed:
        raise ValueError(f"{model}: motion timing crossed the frame boundary")
    return {"model": model, "player_motion_tstates": end - start, "enemy_motion_tstates": enemy_end - enemy_start}


def benchmark(emulator, assembler):
    results = []
    with tempfile.TemporaryDirectory(prefix="ringo8-motion-") as scratch, ThreadPoolExecutor(max_workers=2) as pool:
        for count in (16, 24, 32):
            for edges in (False, True):
                directory = Path(scratch) / f"{count}-{edges}"
                directory.mkdir()
                fixture(directory, count, edges)
                run([assembler, f"-DENEMY_COUNT={count}", "--sym=motion.sym", PROBE], directory)
                for timed in pool.map(lambda model: measure(emulator, directory, model), MODELS):
                    results.append({"enemy_count": count, "scenario": "edges" if edges else "full", **timed})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    args = parser.parse_args()
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        results = benchmark(emulator, assembler)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Motion benchmark failed: {error}\n")
    json.dump({"results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
