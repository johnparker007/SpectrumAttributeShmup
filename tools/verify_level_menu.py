"""Verify the playable menu and time ZX0 on both hardware families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import tempfile

from build_art import LEVEL_MAPS, map_output
from profile_blokius import ARCHIVE, build
from profile_ringo8 import FRAME, HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_blokius_integration import GREEN_FAST_FROM, GREEN_FIRE_COLUMNS, GREEN_SHIP_Y, SHOT_VECTORS, install
from verify_gameplay import PLAYER_START, aim, packed


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
    expect_at("levelUnpackBegin", "HL", s[f"packedLevel{choice}"])
    expect_at("levelUnpackBegin", peek(s["pageTable"] + 1), input_page)
    expect_at("levelUnpackBegin", peek(s["currentPage"]), 1)
    expect_at("levelPageRestored", peek(s["currentPage"]), 0)
    expect_at("firstFrameLogic", f"PEEKW({s['intProc'] + 1:04X}H)", s["renderFrame2"])

    font = (game / "font/n13.bin").read_bytes()
    for name, address, char in (("menuWait", 0x480c, "B"), ("levelUnpackBegin", 0x4897, str(choice))):
        for row in range(8):
            expect_at(name, peek(address + row * 256), font[(ord(char) - 32) * 8 + row])
    level = game / "maps" / f"{map_output(choice)}.bin"
    expected = level.read_bytes()
    for offset in (0, 8, 9, 27, 53, 54, 72, 130, 580, 999, 1534):
        address = s["sourceTileMap"] + offset
        expect_at("levelUnpackEnd", f"PEEKW({address:04X}H)", int.from_bytes(expected[offset:offset + 2], "little"))
    expect_at("levelUnpackEnd", "DE", s["sourceTileMap"] + len(expected))
    wave_probe = f"PC={s['stepWave.saveSlot']:04X}H"
    queue_probe = f"PC={s['queueGreenShot']:04X}H"
    shot_probe = f"PC={s['enemyShotEmitted']:04X}H"
    motion_probe = f"{points['halt2']} AND 1=1"
    watch.extend(((wave_probe, "PEEK(HL)"), (queue_probe, "PEEKW(HL)"),
                  (shot_probe, "B+C*256+D*65536"),
                  (motion_probe, f"PEEKW({s['enemy_records']:04X}H)")))
    spool = game / f"menu-{model}-{choice}.txt"
    spool.write_text(str(choice) * 80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 35, watch,
                         fast_autoload=True, keyboard_spool=spool)
    rows = [(condition, int(value)) for condition, value in HIT.findall(log)]
    hits = {}
    for condition, value in rows:
        hits.setdefault(condition, int(value))
    required = (*points.values(), *checks)
    if missing := [condition for condition in required if condition not in hits]:
        raise ValueError(f"{model} map {choice}: missing trace points {missing}")
    for condition, value in checks.items():
        if hits[condition] != value:
            raise ValueError(f"{model} map {choice}: {condition} printed {hits[condition]}, expected {value}")
    menu, start, stop, restore, enable, render, gameplay, halt = (hits[point] for point in points.values())
    if not menu < start < stop < restore < enable < render < gameplay < halt:
        raise ValueError(f"{model} map {choice}: renderer ran outside the gameplay handoff")
    frames = [value // FRAME for condition, value in rows if condition == points["halt2"]]
    if len(frames) < 150 or any(second - first != 2 for first, second in zip(frames, frames[1:])):
        raise ValueError(f"{model} map {choice}: irregular gameplay across {len(frames)} frame pairs")
    entrances = [value for condition, value in rows if condition == wave_probe]
    if entrances[:13] != [GREEN_SHIP_Y[0][3]] * 12 + [GREEN_SHIP_Y[1][3]]:
        raise ValueError(f"{model} map {choice}: first two waves did not use opposite sine entrances")
    queued = [value for condition, value in rows if condition == queue_probe]
    shots = [value for condition, value in rows if condition == shot_probe]
    column = GREEN_FIRE_COLUMNS[choice - 1]
    if column == 96:
        if queued or shots:
            raise ValueError(f"{model} map {choice}: an unarmed ship fired")
    else:
        expected_origin = packed((column, GREEN_SHIP_Y[0][column] + 2))
        first_bearing = aim(column, expected_origin >> 8, PLAYER_START)
        if (len(shots) < 12 or len(shots) != len(queued)
                or any((shot & 65535) != origin + 512 or origin & 255 != column
                       for shot, origin in zip(shots, queued))
                or shots[0] != expected_origin + first_bearing * 65536):
            raise ValueError(f"{model} map {choice}: incorrect one-shot firing or first bearing")
        positions = [value for condition, value in rows if condition == motion_probe]
        start_at = positions.index(expected_origin)
        dx, dy = SHOT_VECTORS[first_bearing >> 3]
        if choice < GREEN_FAST_FROM:
            dx, dy = round(dx * 2 / 3), round(dy * 2 / 3)
        if positions[start_at + 8] != packed((column + dx, (expected_origin >> 8) + dy)):
            raise ValueError(f"{model} map {choice}: incorrect projectile speed")
    return {"model": model, "map": choice, "compressed_bytes": level.with_suffix(".zx0").stat().st_size,
            "unpack_tstates": stop - start, "gameplay_frame_pairs": len(frames), "shots": len(shots)}


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
                      for choice in range(1, len(LEVEL_MAPS) + 1) for model in MODELS]
            results = [check.result() for check in checks]
        if args.output_tap:
            args.output_tap.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(game / "main.tap", args.output_tap)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
