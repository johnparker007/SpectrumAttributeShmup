"""Measure and verify standalone Ringo-8 attribute-buffer bullet plotting."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from trace_zesarux import breakpoint_log, read_symbols
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "dots" / "plot.asm"
MODELS = ("128k", "P2A41")
WIDTH, HEIGHT, ROW_BYTES = 64, 48, 38
VIEWPORT_OFFSET = 7 * ROW_BYTES + 4
BUFFER_SIZE = 56 * ROW_BYTES
CYAN, YELLOW = 5, 6
HIT = re.compile(r"Catch breakpoint: (PC=[0-9A-F]{4}H)\n(\d+)\n")
MARKERS = ("players_begin", "players_end", "enemies_begin", "enemies_end", "passed", "failed")


def positions(count, alignment):
    def x_for(index):
        return 2 * ((7 * index + 11) % 31) + (index % 2 if alignment == "mixed" else int(alignment == "odd"))

    players = [(x_for(i), (5 * i + 3) % HEIGHT) for i in range(9)]
    players[0] = (61 if alignment == "odd" else 62, HEIGHT - 1)
    players[1] = (int(alignment != "even"), 0)
    enemies = [(x_for(i + 2), (9 * i + 12) % HEIGHT) for i in range(count)]
    # Touch the last row and overlap one player dot. The display must show yellow
    # at the shared coordinate and retain cyan in the other half of the shot.
    enemies[0] = (players[0][0] if alignment == "even" else players[0][0] | 1, HEIGHT - 1)
    enemies[-1] = (1 if alignment == "odd" else 0, 0)
    return players, enemies


def fixture(directory, players, enemies):
    for name, points in (("player", players), ("enemy", enemies)):
        (directory / f"{name}_positions.bin").write_bytes(bytes(axis for point in points for axis in point))

    # Exercise all palette and flag combinations, including blue OR red and
    # untouched guards. The oracle works in logical dots, then packs bytes.
    initial = bytes(((13 * i + (i // ROW_BYTES) * 7) % 64) // 16 * 64
                    + ((i // 4 + i // ROW_BYTES) % 4) * 8 + i % 4
                    for i in range(BUFFER_SIZE))
    (directory / "initial.bin").write_bytes(initial)
    dots = [colour for pair in initial for colour in (pair % 8, pair // 8 % 8)]
    for name, points, colour, width in (("players", players, CYAN, 2), ("enemies", enemies, YELLOW, 1)):
        for x, y in points:
            assert 0 <= x <= WIDTH - width and 0 <= y < HEIGHT
            index = 2 * (VIEWPORT_OFFSET + ROW_BYTES * y) + x
            dots[index:index + width] = [colour] * width
        packed = bytes((pair // 64) * 64 + dots[2 * i] + 8 * dots[2 * i + 1] for i, pair in enumerate(initial))
        (directory / f"expected_{name}.bin").write_bytes(packed)


def measure(emulator, snapshot, markers, model):
    conditions = {f"PC={markers[name]:04X}H": name for name in MARKERS}
    log = breakpoint_log(emulator, snapshot, model, 1, [(condition, "TSTATESP") for condition in conditions])
    matches = HIT.findall(log)
    names = [conditions[condition] for condition, _ in matches]
    if names != list(MARKERS[:-1]) or len(matches) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: dot benchmark failed or did not complete: {names}")
    players_begin, players_end, enemies_begin, enemies_end, passed = [int(value) for _, value in matches]
    if not players_begin < players_end < enemies_begin < enemies_end < passed:
        raise ValueError(f"{model}: dot benchmark timestamps are out of order")
    return {"model": model, "player_plot_tstates": players_end - players_begin,
            "enemy_plot_tstates": enemies_end - enemies_begin}


def benchmark(emulator, assembler):
    results = []
    with tempfile.TemporaryDirectory(prefix="ringo8-dots-") as scratch, ThreadPoolExecutor(max_workers=2) as pool:
        for count in (16, 24, 32):
            for alignment in ("even", "odd", "mixed"):
                directory = Path(scratch) / f"{count}-{alignment}"
                directory.mkdir()
                players, enemies = positions(count, alignment)
                fixture(directory, players, enemies)
                run([assembler, f"-DENEMY_COUNT={count}", "--sym=plot.sym", PROBE], directory)
                markers = read_symbols(directory / "plot.sym")
                futures = [pool.submit(measure, emulator, directory / "plot.sna", markers, model) for model in MODELS]
                # 21 Ts of setup, minus 5 on the final DJNZ. Address calculation
                # and the even-X loop together cost 243 Ts per slot.
                player_cost = 16 + sum(243 + 27 * (x % 2) for x, _ in players)
                enemy_cost = 16 + sum(243 - 7 * (x % 2) for x, _ in enemies)
                for result in futures:
                    measured = result.result()
                    if (measured["player_plot_tstates"], measured["enemy_plot_tstates"]) != (player_cost, enemy_cost):
                        raise ValueError(f"Unexpected loop timing at {count} {alignment}: {measured}")
                    results.append({"enemy_count": count, "alignment": alignment, **measured})
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
        parser.exit(1, f"Dot benchmark failed: {error}\n")
    json.dump({"emulator": version, "assembler": assembler_version, "results": results, "passed": True},
              sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
