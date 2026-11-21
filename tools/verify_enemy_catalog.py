"""Check the real GET READY copies and measure the handoff on both +2 families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from enemy_catalog import FIRST_ORDER, FLIERS, NAMES, ROSTERS, flight_steps, settings, spawn_lane, wave_orders
from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_blokius_integration import CATALOG_VOLLEY_TICKS
from verify_gameplay import aim
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
          f"scenery + enemies {ms(last-load):.1f} ms, selection to renderer {ms(play-start):.1f} ms", flush=True)


def wave_probe(game, assembler, directory, camp=False):
    shutil.copytree(game, directory)
    code = directory / "gameplay.a80"
    before = b"ld hl,playerLives\n    dec (hl)"
    source = code.read_bytes().replace(b"\r\n", b"\n")
    assert source.count(before) == 1
    # Keep rams, deaths and respawns active through a whole unattended rotation.
    # The replacement tests the current lives count and also takes 11 T.
    if camp:
        # Keep the real keyboard poll and hold right, up and fire after it.
        marker = b"controlsReady:\n    ld (lastControls),a"
        assert source.count(marker) == 1
        source = source.replace(marker, b"controlsReady:\n    or 21\n    ld (lastControls),a")
    code.write_bytes(source.replace(before, b"ld hl,playerLives\n    ld a,(hl) : or a"))
    for name in ("main.tap", "main.sna"):
        (directory / name).unlink()
    run([assembler, *(f"-D{flag}=1" for flag in FLAGS), "--sym=main.sym", "main.asm"], directory)


def expected_flight(ship, member, reflected, guns):
    y, upward = spawn_lane(ship, member, reflected)
    active = dict(guns)
    for sample, x, inward in flight_steps(ship):
        height = y - inward if upward else y + inward
        gate = next((col for col in range(x, sample + 1) if col in active), None)
        bearing = None
        if gate is not None:
            angle = active[gate]
            bearing = 1 if angle is None else ((-angle if upward else angle) % 32) * 8
        yield x & 255, height, bearing


def verify_waves(emulator, game, model, level, scratch, camp=False):
    s = read_symbols(game / "main.sym")
    roster = ROSTERS[level - 1]

    def pc(name):
        return f"PC={s[name]:04X}H"

    spawn = pc("writeSpawnArt")
    move, gun = map(pc, ("moveCatalogShip.positionWritten", "moveCatalogShip.gunPositionWritten"))
    aim_at, shot = map(pc, ("catalogBearing", "catalogShotReady"))
    tick, bullet = map(pc, ("moveIncoming", "moveDot"))
    halts = [pc("halt2"), pc("halt1")]
    position = "PEEKW(HL-1)+B*65536"
    window = CATALOG_VOLLEY_TICKS[level - 1]
    target = s["volleyAim"] + 1 if window < 64 else s["playerXY"]
    phase_check = shot + " AND 1=1"
    checks = [(spawn, f"B+PEEK(HL)*256+PEEK({s['spawnSlot']:04X}H)*65536"),
              (move, position), (gun, position), (aim_at, f"PEEKW({target:04X}H)+D*65536"),
              (phase_check, f"PEEK({s['gameTick']:04X}H)"),
              (shot, "B+C*256+D*65536"), (tick, "A"), (bullet, "A"),
              *((halt, "TSTATESP") for halt in halts)]
    hit = pc("updatePlayerLife.checkPlayer") + f" AND PEEK({s['player_hit']:04X}H)>0"
    if camp:
        checks.append((hit, f"PEEKW({s['playerXY']:04X}H)"))
    spool = scratch / f"wave-{model}-{level}.txt"
    spool.write_text(str(level) * 80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 105, checks, True, spool)
    spawns = 0
    slots = {}
    gate_selected = False
    pending = None
    counts = []
    times = []
    aim_player = None
    aimed = 0
    pressure_at_corner = 0
    corner_losses = 0
    order = wave_orders(level)[FIRST_ORDER[level - 1]]
    wave_length = 7 * len(order)
    reflected = False
    for point, raw in HIT.findall(log):
        value = int(raw)
        if point == spawn:
            slot, pose = divmod(value, 65536)
            row, page = divmod(pose, 256)
            member = spawns % 7
            wave = spawns // 7
            kind = order[wave % len(order)]
            if member == 0 and wave and order[(wave - 1) % len(order)] == 0:
                reflected = not reflected
            assert page == s["enemyArt"] // 256 + kind, (model, level, spawns, page)
            if kind >= 2:
                species = roster[kind]
                ship = FLIERS[species - 2]
                assert row == spawn_lane(ship, member, reflected)[0], (model, level, ship.name, member, row)
                slots[slot] = expected_flight(ship, member, reflected, settings(level, species)[1])
            spawns += 1
        elif spawns and point in (move, gun):
            remaining, xy = divmod(value, 65536)
            x, y, bearing = next(slots[s["WAVE_ENEMIES"] - remaining])
            assert xy == y * 256 + x, (model, level, xy, x, y)
            assert (point == gun) == (bearing is not None and not gate_selected)
            if point == gun:
                pending = (x, y + 2, bearing)
                gate_selected = True
        elif spawns and point == aim_at:
            mode, player = divmod(value, 65536)
            aim_player = (player % 256, player // 256)
        elif spawns and point == phase_check:
            assert value % 64 < window, (model, level, "shot during volley rest", value)
        elif spawns and point == shot:
            direction, origin = divmod(value, 65536)
            x, y = origin % 256, origin // 256
            assert (x, y, mode) == pending, (model, level, x, y, mode, pending)
            expected = aim(x, y, aim_player) if mode == 1 else mode
            assert direction == expected, (model, level, x, y, aim_player, direction, expected)
            if mode == 1:
                aimed += 1
                pressure_at_corner += aim_player == (s["PLAYER_RIGHT"], 0)
        elif spawns and point == tick:
            gate_selected = False
            if spawns <= wave_length:
                counts.append(0)
        elif point == bullet and counts and spawns <= wave_length:
            counts[-1] += 1
        elif point == hit and value == s["PLAYER_RIGHT"] and order[(spawns - 1) // 7 % len(order)] >= 2:
            corner_losses += 1
        elif point in halts:
            times.append((point, value))

    assert spawns > wave_length, (model, level, "incomplete rotation", spawns)
    assert aimed > 0, (model, level, "no aimed shots from the additional fliers")
    if camp:
        assert pressure_at_corner > 0, (model, level, "no shots aimed at the corner")
        if level == 9:
            assert corner_losses > 0, (model, level, "corner camper survived")
    assert max(counts) <= s["ENEMY_COUNT"]
    assert len(times) >= 100 and all(k != j and w // FRAME == v // FRAME + 1
               for (k, v), (j, w) in zip(times, times[1:])), (model, level, "overrun")
    print(f"{model} level {level}: {len(times)} video frames, {spawns} spawns, {aimed} aimed shots, "
          f"{pressure_at_corner} aimed at the parked ship, {corner_losses} corner losses, "
          f"{sum(counts)/len(counts):.2f} mean / {max(counts)} peak bullets over the first rotation", flush=True)


def verify_restarts(emulator, game, model, level, scratch):
    """Trace actual ship art across three Enter presses on the playable TAP."""
    s = read_symbols(game / "main.sym")
    reset, spawn = (f"PC={s[name]:04X}H" for name in ("resetLevelWaves", "writeSpawnArt"))
    spool = scratch / f"restarts-{model}-{level}.txt"
    orders = wave_orders(level)
    # Observe a formation, then restart while the unattended player still has
    # ships. Enter is ignored during the two seconds before GAME OVER.
    wait = b"n" * 16
    spool.write_bytes(str(level).encode("ascii") * 12 + (wait + b"\r") * len(orders) + wait)
    log = breakpoint_log(emulator, game / "main.tap", model, 62,
                         [(reset, "A"), (spawn, "B")], True, spool)
    runs = []
    for point, raw in HIT.findall(log):
        if point == reset:
            runs.append([])
        elif runs:
            runs[-1].append(int(raw) - s["enemyArt"] // 256)
    assert len(runs) == len(orders) + 1, (model, level, "attempts", list(map(len, runs)))
    # Slow early formations can still be entering at the next keypress.
    # Check at least one wave boundary and the actual art of every ship seen.
    assert max(map(len, runs)) >= 8, (model, level, "no complete wave")
    for retry, ships in enumerate(runs):
        order = orders[(FIRST_ORDER[level - 1] + retry) % len(orders)]
        assert len(ships) >= 3, (model, level, retry, "too few spawns", len(ships))
        assert all(slot == order[i // 7 % len(order)] for i, slot in enumerate(ships)), (model, level, retry, ships)
    openers = [NAMES[ROSTERS[level - 1][ships[0]]] for ships in runs]
    assert len(set(openers)) == min(len(orders), len(ROSTERS[level - 1]))
    print(f"{model} level {level} openers: {', '.join(openers)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--waves", type=Path, metavar="ASSEMBLER", help="Exercise complete gameplay wave rotations")
    parser.add_argument("--levels", type=int, nargs="+", choices=range(1, len(ROSTERS) + 1),
                        default=range(1, len(ROSTERS) + 1))
    parser.add_argument("--camp", action="store_true", help="Hold fire in the upper right during the wave check")
    parser.add_argument("--restarts", action="store_true", help="Exercise repeated Enter restarts on the playable TAP")
    args = parser.parse_args()
    if args.camp and not args.waves:
        parser.error("--camp needs --waves")
    if args.restarts and args.waves:
        parser.error("--restarts checks the playable TAP directly")
    with TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=4) as workers:
        game = args.game.resolve()
        check = verify_restarts if args.restarts else verify_load
        if args.waves:
            game = Path(tmp) / "waves"
            wave_probe(args.game.resolve(), args.waves.resolve(), game, args.camp)
            check = verify_waves
        options = {"camp": args.camp} if args.waves else {}
        jobs = [workers.submit(check, args.emulator.resolve(), game, model, level, Path(tmp), **options)
                for level in args.levels for model in ("P2", "P2A41")]
        for job in jobs:
            job.result()
