"""Deduplicate whole AY packets and verify banked replay of a complete captured tune."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from benchmark_ay import MODELS, capture
from trace_zesarux import read_symbols
from verify_ay_stream import loop_audio, register_pairs, verify_rows
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "audio" / "phrase_player.asm"
BANK_SIZE = 0x4000
MAX_RUN = 255
MIN_REUSE_BYTES = 9


def packets(stream):
    start = cursor = 0
    while cursor < len(stream):
        if stream[cursor] == 255:
            cursor += 1
            yield stream[start:cursor]
            start = cursor
        else:
            cursor += 2
    if start != len(stream):
        raise ValueError("Unterminated AY packet")


def pack(rows, first_bank_limit=BANK_SIZE):
    literals, runs = [], []
    offsets_by_packet = defaultdict(list)
    index = 0
    while index < len(rows):
        best_start = best_count = best_bytes = 0
        for start in offsets_by_packet[rows[index]]:
            count = size = 0
            while (count < MAX_RUN and index + count < len(rows) and start + count < len(literals)
                   and rows[index + count] == literals[start + count]):
                size += len(rows[index + count])
                count += 1
            if size > best_bytes:
                best_start, best_count, best_bytes = start, count, size
        if best_bytes >= MIN_REUSE_BYTES:
            start, count = best_start, best_count
        else:
            start, count = len(literals), 1
            offsets_by_packet[rows[index]].append(start)
            literals.append(rows[index])
        # The initialization is its own run and is skipped at the song loop.
        if index > 1 and runs[-1][0] + runs[-1][1] == start and runs[-1][1] + count <= MAX_RUN:
            runs[-1] = (runs[-1][0], runs[-1][1] + count)
        else:
            runs.append((start, count))
        index += count

    banks = [bytearray(), bytearray()]
    offsets = []
    bank = 0
    for literal in literals:
        limit = first_bank_limit if bank == 0 else BANK_SIZE
        if len(banks[bank]) + len(literal) > limit:
            bank += 1
        if bank == len(banks):
            raise ValueError("Literal packets exceed the two-bank fixture")
        offsets.append(bank * BANK_SIZE + len(banks[bank]))
        banks[bank].extend(literal)

    recipe = bytearray()
    for start, count in runs:
        end = start + count
        while start < end:
            bank = offsets[start] // BANK_SIZE
            following = start + 1
            while following < end and offsets[following] // BANK_SIZE == bank:
                following += 1
            recipe.extend(offsets[start].to_bytes(2, "little"))
            recipe.append(following - start)
            start = following

    restored = []
    for index in range(0, len(recipe), 3):
        offset = int.from_bytes(recipe[index:index + 2], "little")
        bank, start = divmod(offset, BANK_SIZE)
        cursor = start
        for _ in range(recipe[index + 2]):
            while banks[bank][cursor] != 255:
                cursor += 2
            cursor += 1
        restored.extend(packets(bytes(banks[bank][start:cursor])))
    if restored != rows or recipe[2] != 1:
        raise ValueError("AY recipe failed its round-trip check")
    return (bytes(recipe), *map(bytes, banks))


def compare(emulator, directory, model, seconds, reference, expected_wire):
    symbols = read_symbols(directory / "phrase_player.sym")
    points = {
        f"PC={symbols['select_register']:04X}H AND BC=FFFDH": ("select", "TSTATES*256+A"),
        f"PC={symbols['write_register']:04X}H AND BC=BFFDH": ("data", "TSTATES*256+A"),
    }
    result = capture(emulator, directory / "phrase_player.sna", symbols, model, seconds, points, len(reference) - 1)
    rows = [register_pairs(result["initial_writes"])]
    rows.extend(register_pairs(tick["writes"]) for tick in result["ticks"])
    verify_rows(rows, reference, model, expected_wire)
    return {"model": model, "ticks_verified": len(result["ticks"]), "tick_cost_range": result["tick_cost_range"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="JSON from benchmark_ay.py --through-loop")
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="optional directory for the verified recipe and literal banks")
    parser.add_argument("--seconds", type=int, default=290, help="wall-clock capture length per model")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        source = json.loads(args.reference.read_text(encoding="utf-8-sig"))
        if not source["passed"] or source["emulator"] != version:
            raise ValueError("Expected the verified AY capture from this emulator version")
        case = source["results"][0]
        reference = [register_pairs(case["initial_writes"])]
        reference.extend(register_pairs(tick["writes"]) for tick in case["ticks"])
        init, loop = loop_audio(reference)
        loop_packets = list(packets(loop))
        files = dict(zip(("recipe.bin", "literal0.bin", "literal1.bin"), pack([init, *loop_packets]), strict=True))
        expected_rows = [*reference, *reference[1:33]]
        expected_wire = init + loop + b"".join(loop_packets[:32])
        with tempfile.TemporaryDirectory(prefix="ringo8-phrases-") as scratch, ThreadPoolExecutor(max_workers=2) as pool:
            directory = Path(scratch)
            for name, data in files.items():
                (directory / name).write_bytes(data)
            flags = ["-DUSE_BANK1=1"] if files["literal1.bin"] else []
            run([assembler, *flags, "--sym=phrase_player.sym", PROBE], directory)
            model_results = list(pool.map(lambda model: compare(emulator, directory, model, args.seconds,
                                                               expected_rows, expected_wire), MODELS))
        if args.output is not None:
            args.output.mkdir(parents=True, exist_ok=True)
            for name, data in files.items():
                (args.output / name).write_bytes(data)
    except (OSError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"AY phrase verification failed: {error}\n")
    sizes = {name: len(data) for name, data in files.items()}
    json.dump({"emulator": version, "song_sha256": source["song_sha256"], "unpacked_bytes": len(init) + len(loop),
               "packed_bytes": sum(sizes.values()), "file_bytes": sizes, "results": model_results, "passed": True},
              sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
