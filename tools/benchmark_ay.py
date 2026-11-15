"""Measure the Blokius reference player and record its ordered AY writes at 50 Hz."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from profile_ringo8 import FRAME, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_zesarux_raster import run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "audio" / "reference_player.asm"
HIT = re.compile(r"Catch breakpoint: (PC=[^\n]+)\n(\d+)\n")
FRAMES_REQUIRED = 256
PLAYER = "player_55000.bin"
SONG = "song_57158.bin"


def extract_music(archive_path, directory, ay_export):
    with ZipFile(archive_path) as archive:
        player, song = [archive.read(next(item for item in archive.namelist() if item.endswith(f"/game/music/{name}")))
                        for name in (PLAYER, SONG)]
    if len(player) != 1617 or len(song) != 2015 or player[:6] != b"\x21\x46\xdf\x18\x3a\xc3":
        raise ValueError("Expected the VTII PT3 r.7 player and song built for 55000 and 57158")
    output_loop = bytes.fromhex("ed79 43 eda3 42 3c fe0d 20f5 ed79 7e a7 f8 43 ed79 c9")
    if player[0xDC8C - 55000:0xDC8C - 55000 + len(output_loop)] != output_loop:
        raise ValueError("The compiled player has an unrecognized AY output loop")
    if ay_export is not None and song not in ay_export.read_bytes():
        raise ValueError("The archived PT3 song does not match the requested AY export")
    (directory / PLAYER).write_bytes(player)
    (directory / SONG).write_bytes(song)
    return hashlib.sha256(player).hexdigest(), hashlib.sha256(song).hexdigest()


def capture(emulator, snapshot, symbols, model, seconds, io_points, frames, allow_select_only=False):
    points = {
        f"PC={symbols['tick_begin']:04X}H": ("begin", "TSTATESP"),
        f"PC={symbols['tick_end']:04X}H": ("end", "TSTATESP"),
        **io_points,
    }
    log = breakpoint_log(emulator, snapshot, model, seconds,
                         [(condition, expression) for condition, (_, expression) in points.items()])
    hits = HIT.findall(log)
    if not hits or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: incomplete AY debugger output")
    ticks = []
    current = {"writes": []}
    initial_writes = current["writes"]
    pending = None
    for condition, raw in hits:
        value = int(raw)
        kind = points[condition][0]
        # The PT3 reference can select register 13 then skip its data write.
        incomplete_write = pending is not None and not (allow_select_only and pending[0] == 13)
        if kind == "begin":
            if incomplete_write or ("begin" in current and "cost" not in current):
                raise ValueError(f"{model}: incomplete AY tick")
            pending = None
            current = {"begin": value, "writes": []}
        elif kind == "end":
            if incomplete_write or value // FRAME != current["begin"] // FRAME:
                raise ValueError(f"{model}: AY playback did not complete in its frame")
            pending = None
            current["cost"] = value - current["begin"]
            ticks.append(current)
        elif kind == "select":
            clock, register = divmod(value, 256)
            if pending is not None or register > 13:
                raise ValueError(f"{model}: unexpected AY register selection")
            pending = (register, clock)
        else:
            clock, byte = divmod(value, 256)
            if pending is None or clock <= pending[1]:
                raise ValueError(f"{model}: unexpected AY data write")
            current["writes"].append({"register": pending[0], "value": byte,
                                       "select_instruction_tstate": pending[1], "data_instruction_tstate": clock})
            pending = None
    if len(ticks) < frames:
        raise ValueError(f"{model}: captured only {len(ticks)} ticks. Increase --seconds.")

    # A fixed prefix makes reports comparable across different host speeds.
    ticks = ticks[:frames]
    first_frame = ticks[0]["begin"] // FRAME
    for index, tick in enumerate(ticks):
        if tick["begin"] // FRAME != first_frame + index:
            raise ValueError(f"{model}: playback skipped a 50 Hz frame")
    costs = [tick["cost"] for tick in ticks]
    envelopes = [write["value"] for tick in ticks for write in tick["writes"] if write["register"] == 13]
    return {"model": model, "ticks": ticks, "initial_writes": initial_writes,
            "tick_cost_range": [min(costs), max(costs)], "envelope_writes": len(envelopes)}


def record(emulator, directory, model, seconds):
    ports = {
        "PC=DC8CH AND BC=FFFDH": ("select", "TSTATES*256+A"),
        "PC=DC97H AND BC=FFFDH": ("select", "TSTATES*256+A"),
        "PC=DC8FH AND BC=BFFDH": ("data", "TSTATES*256+PEEK(HL)"),
        "PC=DC9DH AND BC=BFFDH": ("data", "TSTATES*256+A"),
    }
    symbols = read_symbols(directory / "reference_player.sym")
    result = capture(emulator, directory / "reference_player.sna", symbols, model, seconds, ports,
                     FRAMES_REQUIRED, allow_select_only=True)
    for index, tick in enumerate(result["ticks"]):
        registers = [write["register"] for write in tick["writes"]]
        if registers not in (list(range(13)), list(range(14))):
            raise ValueError(f"{model}: unexpected AY write order in tick {index}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Blokius sprite-manager WIP ZIP")
    parser.add_argument("--ay-export", type=Path, help="optional Vortex Tracker .ay export to compare")
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=16, help="wall-clock capture length per model")
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
        with tempfile.TemporaryDirectory(prefix="ringo8-ay-") as scratch:
            directory = Path(scratch)
            player_hash, song_hash = extract_music(args.archive, directory, args.ay_export)
            run([assembler, "--sym=reference_player.sym", PROBE], directory)
            results = [record(emulator, directory, model, args.seconds) for model in MODELS]
        writes = [[(write["register"], write["value"]) for write in tick["writes"]] for tick in results[0]["ticks"]]
        other = [[(write["register"], write["value"]) for write in tick["writes"]] for tick in results[1]["ticks"]]
        if other != writes:
            raise ValueError("Models disagree on the reference AY register stream")
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"AY benchmark failed: {error}\n")
    json.dump({"emulator": version, "assembler": assembler_version, "player_sha256": player_hash,
               "song_sha256": song_hash, "results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
