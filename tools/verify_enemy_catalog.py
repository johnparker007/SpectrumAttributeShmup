"""Check the real GET READY copies and measure the handoff on both +2 families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from enemy_catalog import FLIERS, ROSTERS, path_bytes, settings
from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_gameplay import PLAYER_START, aim
from verify_scenery import FLAGS
from verify_zesarux_raster import run


def verify_load(emulator, game, model, level, scratch):
    symbols = read_symbols(game / "main.sym")

    def pc(name):
        return f"PC={symbols[name]:04X}H"

    timers = ("menuSelected", "loadLevel", "enemyLoadBegin", "enemyLoadEnd", "enableRender")
    checks = [(pc(name), "TSTATESP") for name in timers]
    packet, art, path = map(pc, ("unpackEnemyPacket", "loadEnemyRoster.artCopy", "loadEnemyRoster.pathCopy"))
    checks.extend(((packet, "HL"), (art, "PEEK(HL)+DE*256"), (path, "PEEK(HL)+DE*256")))
    spool = scratch / f"roster-{model}-{level}.txt"
    spool.write_text(str(level) * 80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 22, checks, True, spool, repeat=True)
    events = [(k, int(v)) for k, v in HIT.findall(log)]

    def samples(key):
        return [v for k, v in events if k == key]

    roster = ROSTERS[level - 1]
    start, load, first, last, play = (samples(pc(name))[0] for name in timers)
    assert start < load < first < last < play
    # Other paged code can execute at these same CPU addresses outside GET READY.
    events = events[events.index((pc("enemyLoadBegin"), first)):events.index((pc("enemyLoadEnd"), last))]
    assert samples(packet) == [symbols[f"enemyPacket{i}"] for i in roster], (model, level, "packet order")
    images, curves = [], []
    for slot, species in enumerate(roster):
        data = (game / f"enemy_packet_{species}.bin").read_bytes()
        address = symbols["enemyArt"] + slot * 256
        images.extend((address + i) * 256 + b for i, b in enumerate(data[:256]))
        address = symbols["catalogPaths"] + (slot - 2) * 256
        curves.extend((address + i) * 256 + b for i, b in enumerate(data[256:]))
    for key, expected in ((art, images), (path, curves)):
        # ZEsarUX can report the same LDIR visit again on an emulated frame
        # boundary. DE is part of each sample and increases for every byte.
        actual = [value for value, _ in groupby(samples(key))]
        if actual != expected:
            diff = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b),
                        min(len(actual), len(expected)))
            raise ValueError(f"{model} level {level} copy {key} first differs at byte {diff}, "
                             f"received {len(actual)} of {len(expected)} bytes")

    def ms(tstates):
        return tstates * 20 / FRAME

    print(f"{model} level {level} ({len(roster)} species): enemies {last-first} T / {ms(last-first):.1f} ms, "
          f"map + enemies {ms(last-load):.1f} ms, selection to renderer {ms(play-start):.1f} ms", flush=True)


def wave_probe(game, assembler, directory):
    shutil.copytree(game, directory)
    code = directory / "gameplay.a80"
    before = b"ld hl,playerLives\n    dec (hl)"
    source = code.read_bytes().replace(b"\r\n", b"\n")
    assert source.count(before) == 1
    # Keep rams, deaths and respawns active through a whole unattended rotation.
    # The replacement tests the current lives count and also takes 11 T.
    code.write_bytes(source.replace(before, b"ld hl,playerLives\n    ld a,(hl) : or a"))
    for name in ("main.tap", "main.sna"):
        (directory / name).unlink()
    run([assembler, *(f"-D{flag}=1" for flag in FLAGS), "--sym=main.sym", "main.asm"], directory)


def verify_waves(emulator, game, model, level, scratch):
    s = read_symbols(game / "main.sym")
    roster = ROSTERS[level - 1]

    def pc(name):
        return f"PC={s[name]:04X}H"

    spawn, read, shot = map(pc, ("writeSpawnArt", "moveCatalogShip.readSample", "catalogShotReady"))
    halts = [pc("halt2"), pc("halt1")]
    checks = [(spawn, "BC"), (read, "HL+PEEK(HL)*65536"), (shot, "B+C*256+D*65536"),
              *((halt, "TSTATESP") for halt in halts)]
    spool = scratch / f"wave-{model}-{level}.txt"
    spool.write_text(str(level) * 80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 82, checks, True, spool)
    events = [(k, int(v)) for k, v in HIT.findall(log)]
    images = [v for k, v in events if k == spawn]
    expected = [s["enemyArt"] + n * 256 for n in range(len(roster)) for _ in range(7)]
    assert images[:len(expected)] == expected, (model, level, "wave rotation", len(images))
    valid_shots = set()
    paths = []
    for slot, species in enumerate(roster[2:], 2):
        curve = path_bytes(FLIERS[species - 2])
        for gun, (x, bearing) in enumerate(settings(level, species)[1], 1):
            for mirror in (0, 1):
                ix = x * 2 + mirror
                y = curve[ix] + 2
                if bearing is None:
                    direction = aim(x, y, PLAYER_START)
                else:
                    direction = ((-bearing if mirror else bearing) % 32) * 8
                valid_shots.add(x + y * 256 + direction * 65536)
                curve[ix] |= gun * 64
        paths.extend(curve)
    visited = set()
    for point, value in events:
        if point == read:
            sample, addr = divmod(value, 65536)
            offset = addr - s["catalogPaths"]
            assert 0 <= offset < len(paths) and paths[offset] == sample, (model, level, offset, sample)
            visited.add(offset // 256)
        if point == shot:
            assert value in valid_shots, (model, level, "bearing or origin", value)
    assert visited == set(range(len(roster[2:])))
    assert not paths or any(k == shot for k, v in events)
    times = [(k, v) for k, v in events if k in halts]
    assert len(times) >= 100 and all(k != j and w // FRAME == v // FRAME + 1
                                     for (k, v), (j, w) in zip(times, times[1:])), (model, level, "overrun")
    print(f"{model} level {level}: {len(images)} spawns, {len(times)} video frames, "
          f"{sum(k == shot for k, v in events)} scripted shots", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--waves", type=Path, metavar="ASSEMBLER", help="Exercise complete gameplay wave rotations")
    parser.add_argument("--levels", type=int, nargs="+", choices=range(1, len(ROSTERS) + 1),
                        default=range(1, len(ROSTERS) + 1))
    args = parser.parse_args()
    with TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=4) as workers:
        game = args.game.resolve()
        check = verify_load
        if args.waves:
            game = Path(tmp) / "waves"
            wave_probe(args.game.resolve(), args.waves.resolve(), game)
            check = verify_waves
        jobs = [workers.submit(check, args.emulator.resolve(), game, model, level, Path(tmp))
                for level in args.levels for model in ("P2", "P2A41")]
        for job in jobs:
            job.result()
