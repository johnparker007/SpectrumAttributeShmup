"""Verify a compact AY delta stream against an emulated PT3 reference capture."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from benchmark_ay import MODELS, capture
from trace_zesarux import read_symbols
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "audio" / "stream_player.asm"
ENVELOPE_SHAPE = 13


def register_pairs(writes):
    return [(write["register"], write["value"]) for write in writes]


def encode(rows):
    state = {}
    data = bytearray()
    for row in rows:
        for register, value in row:
            if not 0 <= register <= ENVELOPE_SHAPE or not 0 <= value <= 255:
                raise ValueError("Invalid AY register or value")
            if register == ENVELOPE_SHAPE or state.get(register) != value:
                data.extend((register, value))
                state[register] = value
        data.append(0xFF)
    return bytes(data)


def loop_audio(rows):
    initial = encode(rows[:1])
    end_state = {reg: value for row in rows for reg, value in row}
    initial_state = dict(rows[0])
    # The first music tick must reach the same state from initialization and
    # from the last tick. Keep both sets of changes and skip init on loop.
    first = [(reg, value) for reg, value in rows[1]
             if reg == ENVELOPE_SHAPE or initial_state.get(reg) != value or end_state.get(reg) != value]
    first_packet = bytes(value for pair in first for value in pair) + b"\xff"
    rest = encode(rows)[len(encode(rows[:2])):]
    return initial, first_packet + rest


def verify_rows(actual, reference, model, expected_wire=None):
    state, reference_state = {}, {}
    for index, (writes, original) in enumerate(zip(actual, reference, strict=True)):
        state.update(writes)
        reference_state.update(original)
        shapes = [value for register, value in writes if register == ENVELOPE_SHAPE]
        reference_shapes = [value for register, value in original if register == ENVELOPE_SHAPE]
        if state != reference_state or shapes != reference_shapes:
            raise ValueError(f"{model}: AY register state or retriggers differ at entry {index}")
    actual_stream = b"".join(bytes(byte for pair in row for byte in pair) + b"\xff" for row in actual)
    if actual_stream != (encode(reference) if expected_wire is None else expected_wire):
        raise ValueError(f"{model}: retained AY writes differ in content or order")


def compare(emulator, directory, model, seconds, reference):
    symbols = read_symbols(directory / "stream_player.sym")
    points = {
        f"PC={symbols['select_register']:04X}H AND BC=FFFDH": ("select", "TSTATES*256+A"),
        f"PC={symbols['write_register']:04X}H AND BC=BFFDH": ("data", "TSTATES*256+A"),
    }
    capture_data = capture(emulator, directory / "stream_player.sna", symbols, model, seconds, points, len(reference) - 1)
    rows = [register_pairs(capture_data["initial_writes"])]
    rows.extend(register_pairs(tick["writes"]) for tick in capture_data["ticks"])
    verify_rows(rows, reference, model)
    return {"model": model, "ticks": len(rows) - 1, "tick_cost_range": capture_data["tick_cost_range"],
            "envelope_writes": capture_data["envelope_writes"], "writes_per_tick": [len(row) for row in rows[1:]]}


def benchmark(emulator, assembler, reference, seconds):
    cases = {item["model"]: item for item in reference["results"]}
    reference_rows = [register_pairs(cases[MODELS[0]]["initial_writes"])]
    reference_rows.extend(register_pairs(tick["writes"]) for tick in cases[MODELS[0]]["ticks"])
    other_rows = [register_pairs(cases[MODELS[1]]["initial_writes"])]
    other_rows.extend(register_pairs(tick["writes"]) for tick in cases[MODELS[1]]["ticks"])
    if reference_rows != other_rows:
        raise ValueError("Reference AY writes disagree between models")

    # Exercise repeated envelope writes, a tick with no writes, and a full
    # 14-register update at the stream wrap point.
    zero = [(register, 0) for register in range(14)]
    changed = [(register, register + 1) for register in range(14)]
    synthetic = [zero, changed, changed, changed[:-1], zero]
    results = []
    with tempfile.TemporaryDirectory(prefix="ringo8-ay-stream-") as scratch, ThreadPoolExecutor(max_workers=2) as pool:
        for name, rows, duration in (("song_prefix", reference_rows, seconds), ("envelope_and_full_update", synthetic, 2)):
            directory = Path(scratch) / name
            directory.mkdir()
            stream = encode(rows)
            (directory / "stream.bin").write_bytes(stream)
            run([assembler, "--sym=stream_player.sym", PROBE], directory)
            models = list(pool.map(lambda model: compare(emulator, directory, model, duration, rows), MODELS))
            results.append({"scenario": name, "bytes": len(stream), "models": models,
                            "raw_register_writes": sum(map(len, rows)),
                            "stream_register_writes": (len(stream) - len(rows)) // 2})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="JSON from benchmark_ay.py")
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=16, help="wall-clock capture length per model")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        reference = json.loads(args.reference.read_text(encoding="utf-8-sig"))
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        if not reference["passed"] or version != reference["emulator"]:
            raise ValueError("Expected a passing reference capture from this emulator version")
        results = benchmark(emulator, assembler, reference, args.seconds)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"AY stream verification failed: {error}\n")
    json.dump({"emulator": version, "song_sha256": reference["song_sha256"], "results": results, "passed": True},
              sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
