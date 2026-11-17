"""Verify the playable menu and time ZX0 on both hardware families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import tempfile

from profile_blokius import ARCHIVE, build
from profile_ringo8 import FRAME, HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_blokius_integration import install


def verify_choice(emulator, game, model, choice):
    s = read_symbols(game / "main.sym")
    points = {name: f"PC={s[name]:04X}H" for name in (
        "menuWait", "levelUnpackBegin", "levelUnpackEnd", "levelPageRestored",
        "enableRender", "renderFrame1", "firstFrameLogic", "halt2",
    )}
    watch = [(point, "TSTATESP") for point in points.values()]
    checks = {}

    def expect_at(name, expression, value):
        condition = f"{points[name]} AND {len(watch)}={len(watch)}"
        watch.append((condition, expression))
        checks[condition] = value

    def peek(address):
        return f"PEEK({address:04X}H)"

    input_page = 0x11 if model == "128k" else 0x14
    expect_at("menuWait", f"PEEKW({s['intProc'] + 1:04X}H)", s["nullProc"])
    expect_at("levelUnpackBegin", f"PEEKW({s['intProc'] + 1:04X}H)", s["nullProc"])
    expect_at("levelUnpackBegin", "HL", s["packedLevelOne" if choice == 1 else "packedLevelTwo"])
    expect_at("levelUnpackBegin", peek(s["pageTable"] + 1), input_page)
    expect_at("levelUnpackBegin", peek(s["currentPage"]), 1)
    expect_at("levelPageRestored", peek(s["currentPage"]), 0)
    expect_at("firstFrameLogic", f"PEEKW({s['intProc'] + 1:04X}H)", s["renderFrame2"])

    font = (game / "font/n13.bin").read_bytes()
    for name, address, char in (("menuWait", 0x480c, "B"), ("levelUnpackBegin", 0x4897, str(choice))):
        for row in range(8):
            expect_at(name, peek(address + row * 256), font[(ord(char) - 32) * 8 + row])
    level = game / ("maps/tilemap.bin" if choice == 1 else "maps/tilemap-2.bin")
    expected = level.read_bytes()
    for offset in (0, 8, 9, 27, 53, 54, 72, 130, 580, 999, 1534):
        address = s["sourceTileMap"] + offset
        expect_at("levelUnpackEnd", f"PEEKW({address:04X}H)", int.from_bytes(expected[offset:offset + 2], "little"))
    expect_at("levelUnpackEnd", "DE", s["sourceTileMap"] + len(expected))
    spool = game / f"menu-{model}-{choice}.txt"
    spool.write_text(str(choice) * 80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 35, watch,
                         fast_autoload=True, keyboard_spool=spool)
    hits = {}
    for condition, value in HIT.findall(log):
        hits.setdefault(condition, int(value))
    if any(condition not in hits for condition, _ in watch):
        missing = [condition for condition, _ in watch if condition not in hits]
        raise ValueError(f"{model} map {choice}: missing trace points {missing}")
    for condition, value in checks.items():
        if hits[condition] != value:
            raise ValueError(f"{model} map {choice}: {condition} printed {hits[condition]}, expected {value}")
    menu, start, stop, restore, enable, render, gameplay, halt = (hits[point] for point in points.values())
    if not menu < start < stop < restore < enable < render < gameplay < halt:
        raise ValueError(f"{model} map {choice}: renderer ran outside the gameplay handoff")
    frames = [int(value) // FRAME for condition, value in HIT.findall(log) if condition == points["halt2"]]
    if len(frames) < 150 or any(second - first != 2 for first, second in zip(frames, frames[1:])):
        raise ValueError(f"{model} map {choice}: irregular gameplay across {len(frames)} frame pairs")
    return {"model": model, "map": choice, "compressed_bytes": level.with_suffix(".zx0").stat().st_size,
            "unpack_tstates": stop - start, "gameplay_frame_pairs": len(frames)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("assembler", "emulator", "output-tap"):
        parser.add_argument(f"--{arg}", type=Path, required=arg != "output-tap")
    args = parser.parse_args()
    assembler, emulator = (p.resolve(strict=True) for p in (args.assembler, args.emulator))
    with tempfile.TemporaryDirectory(prefix="shmup-levels-") as scratch:
        game = build(ARCHIVE, assembler, Path(scratch))
        install(game, assembler, live=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            checks = [pool.submit(verify_choice, emulator, game, model, choice)
                      for model in MODELS for choice in (1, 2)]
            results = [check.result() for check in checks]
        if args.output_tap:
            args.output_tap.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(game / "main.tap", args.output_tap)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
