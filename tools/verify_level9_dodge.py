"""Replay thirty seconds of level 9 with movement only and normal collisions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run

# Numeric keypad directions, 5 = stay. Each input lasts three game ticks.
ROUTE = (
    "55555555222222288889751355355335655577774986976187"
    "79792333221544195445673122225338888555554269787965"
    "66515178889999355555521115118555777955555353536114"
    "17555222553336969787764455755555555555555375555559"
    "98235454545234115522233698785178689155335555555555"
)
MASKS = (10, 8, 9, 2, 0, 1, 6, 4, 5)


def verify(emulator, game, model):
    symbols = read_symbols(game / "main.sym")
    tick, bullet, spawn, complete, halt1, halt2 = (
        f"PC={symbols[name]:04X}H" for name in
        ("motionStep", "moveDot", "writeSpawnArt", "gameplayComplete", "halt1", "halt2"))
    checks = [(tick, "A"), (bullet, "A"), (spawn, "B"),
              (complete, f"PEEK({symbols['playerLives']:04X}H)"),
              (halt1, "TSTATESP"), (halt2, "TSTATESP")]
    keys = game / f"route-{model}.txt"
    keys.write_text("9" * 12, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 90, checks, True, keys)
    bullets, lives, halts = [], [], []
    ships = 0
    for key, raw in HIT.findall(log):
        if key == tick:
            if len(bullets) == len(ROUTE) * 3:
                break
            bullets.append(0)
        elif bullets and key == bullet:
            bullets[-1] += 1
        elif bullets and key == spawn:
            ships += 1
        elif bullets and key == complete:
            lives.append(int(raw))
        elif bullets and key in (halt1, halt2):
            halts.append((key, int(raw) // FRAME))
    assert len(lives) == len(ROUTE) * 3 and set(lives) == {3}, (model, "route", len(lives), min(lives, default=0))
    assert ships >= 7 * 12 and 20 <= max(bullets) <= 24, (model, ships, max(bullets))
    assert len(halts) == 2 * len(lives), (model, "incomplete frame trace", len(halts))
    assert all(k != j and w == v + 1 for (k, v), (j, w) in zip(halts, halts[1:])), (model, "frame cadence")
    print(f"{model}: {len(lives)} ticks, {ships} ships, peak {max(bullets)} bullets, three lives throughout")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "assembler", "emulator"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as tmp:
        game = Path(tmp) / "route"
        shutil.copytree(args.game, game)
        inputs = bytearray()
        for direction, group in groupby(ROUTE):
            inputs.extend((3 * sum(1 for _ in group), MASKS[int(direction) - 1]))
        (game / "controls.bin").write_bytes(inputs + bytes(1))
        # Give the regular replay reader a bank 0 table to preserve fixed RAM.
        source = game / "gameplay.a80"
        table = 'replayControls: incbin "controls.bin"'
        code = source.read_text()
        assert code.count(table) == 1
        source.write_text(code.replace(table, ""))
        with (game / "boss.a80").open("a") as out:
            out.write("\n" + table + "\n")
        for name in ("main.sna", "main.tap"):
            (game / name).unlink()
        run([args.assembler.resolve(), *(f"-D{flag}=1" for flag in (*FLAGS, "REPLAY_CONTROLS")),
             "--sym=main.sym", "main.asm"], game)
        with ThreadPoolExecutor(2) as workers:
            for job in [workers.submit(verify, args.emulator.resolve(), game, model) for model in MODELS]:
                job.result()
