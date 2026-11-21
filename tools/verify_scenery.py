"""Check the complete scenery stream and a saturated gameplay tick on both Spectrum families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile

from build_art import map_output
from enemy_catalog import FLIERS, ROSTERS, flight_steps, settings, spawn_lane
from profile_blokius import ARCHIVE, build
from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_blokius_integration import install
from verify_zesarux_raster import run

FIXTURE = Path(__file__).resolve().parents[1] / "tests/scenery/sector_seed.a80"
MODELS = ("P2", "P2A41")
FLAGS = ("OVERLAY_MOTION OVERLAY_FAST_PLOT SCHEDULE_COLLISION OVERLAY_AUDIO OVERLAY_PHRASES "
         "BARREL_SCENERY LIVE_SHMUP LEVEL_WAVES BOTTOM_HUD LEVEL_MENU LUMINANCE_LOGO LIVE_SFX").split()


def make_probe(game, directory, assembler, *, bonus=False, catalog=False):
    shutil.copytree(game, directory)
    source = directory / "main.asm"
    marker = b"            call gameInit"
    code = source.read_bytes()
    if code.count(marker) != 2:
        raise ValueError("Unexpected game initializer")
    source.write_bytes(code.replace(marker, b"            call sectorTest", 1))
    resources = directory / "gfx/resources.a80"
    with resources.open("ab") as dest:
        dest.write(b'\n    include "sector_seed.a80"\n    assert $<=#10000\n')
    shutil.copyfile(FIXTURE, directory / FIXTURE.name)
    for name in ("main.sna", "main.tap"):
        (directory / name).unlink()
    flags = FLAGS + (["STRESS_BONUS_LIFE"] if bonus else [])
    if catalog:
        flags.append("STRESS_CATALOG")
        positions = bytearray()
        for i in range(15):
            species = ROSTERS[8][2 + i % 6]
            ship = FLIERS[species - 2]
            entry, upward = spawn_lane(ship, 0, i % 2)
            gates = dict(settings(9, species)[1])
            prev_x, prev_y = 67, entry
            for sample, x, height in flight_steps(ship):
                if any(c in gates for c in range(x, sample + 1)):
                    break
                prev_x, prev_y = x, entry + (-height if upward else height)
            positions.extend((prev_x, prev_y, upward))
        (directory / "catalog-stress.bin").write_bytes(positions)
    run([assembler, *("-D" + flag + "=1" for flag in flags), "--sym=main.sym", "main.asm"], directory)


def verify(emulator, game, model, level, *, bonus=False, catalog=False):
    symbols = read_symbols(game / "main.sym")

    def pc(name):
        return f"PC={symbols[name]:04X}H"

    def peek(address):
        return f"PEEK({address:04X}H)"

    begin, done, tile = map(pc, ("sectorTest", "sectorStreamDone", "streamSceneryTile.next"))
    right = tile + " AND C>9 AND C<18"
    end = pc("overlayEnemies")
    mount = symbols["tileMap"] + 54
    checks = [(begin, "TSTATESP"), (done, "TSTATESP"),
              (tile, "B+C*256+L*65536+PEEK(HL)*16777216"), (right, "PEEK(HL+10)"),
              (pc("halt2"), "TSTATESP"), (pc("halt1"), "TSTATESP"),
              (end, peek(symbols["sceneryBlastCount"])),
              (end + " AND 1=1", peek(symbols["tileMapScroll_H"]))]
    for slot in range(5):
        checks.append((end + f" AND {slot+2}={slot+2}",
                       peek(mount+slot) + "+256*" + peek(mount+10+slot)))
    # Observe the actual colours after the plotter has selected its active
    # ink and paper immediates. Both lanes must alternate every composition.
    colours = pc("overlayEnd")
    checks.append((colours, peek(symbols["plotIncomingDot.ink"]+1) + "+256*" +
                   peek(symbols["plotIncomingDot.paperColour"]+1)))
    # The seeded green and yellow ships eight slots apart share an update tick.
    # Sample both full pointers before the renderer advances the next quartet.
    flight = pc("advanceFlightSprites")
    checks.append((flight, f"PEEKW({symbols['sprite10']:04X}H)"))
    yellow = flight + " AND 1=1"
    checks.append((yellow, f"PEEKW({symbols['sprite18']:04X}H)"))
    if catalog:
        armed = pc("moveCatalogShip.readSample") + " AND PEEK(HL)>63"
        checks.append((armed, "B"))
        accepted = pc("moveCatalogShip.gunPositionWritten")
        checks.append((accepted, "B"))
    a_hits = end + " AND 8=8"
    checks.append((a_hits, peek(symbols["sceneryAHits"])))
    sheen = end + " AND 9=9"
    crate = symbols["DESTRUCTIBLE_TILE"]
    checks.append((sheen, f"PEEKW({symbols['tilesLUT']+2*crate:04X}H)"))
    if bonus:
        checks.append((pc("hudScoreAwarded.extraLife"), "TSTATESP"))
    spool = game / f"sector-{model}-{level}.txt"
    spool.write_text(str(level)*80, encoding="ascii")
    log = breakpoint_log(emulator, game / "main.tap", model, 22, checks, True, spool)
    events = [(k, int(v)) for k, v in HIT.findall(log)]
    start = next(i for i, (k, _) in enumerate(events) if k == begin)
    stop = next(i for i, (k, _) in enumerate(events[start:], start) if k == done)
    streaming = events[start:stop]
    exported = (game / "maps" / (map_output(level) + ".bin")).read_bytes()
    expected = exported[54:] + bytes(5)
    writes = [v for k, v in streaming if k == tile]
    aliases = iter(v for k, v in streaming if k == right)
    assert len(writes) == len(expected)
    for index, (value, record) in enumerate(zip(expected, writes, strict=True)):
        col = 9 + (index // 6) % 10
        offset = index % 6 * 18 + (col if col == 9 else col-10)
        assert record == value + 256*col + 65536*offset + 16777216*value, (level, index)
        if 9 < col < 18:
            assert next(aliases) == value, (level, index, "right copy")
    assert next(aliases, None) is None

    play = events[stop:]
    halts = [(k, v) for k, v in play if k in (pc("halt1"), pc("halt2"))]
    assert len(halts) > 120
    assert all(k != j and w//FRAME == v//FRAME + 1
               for (k, v), (j, w) in zip(halts, halts[1:])), (model, level, "missed interrupt")
    assert [v for k, v in play if k == end][:7] == [5]*6 + [0]
    # Five paired shots hit both barrel aliases. Only slots 0 and 4 held As.
    assert [v for k, v in play if k == a_hits][:7] == [2]*7
    first = symbols["CRATE_SHEEN_FIRST"]
    count = symbols["CRATE_SHEEN_POSES"]
    cycle = [*range(first, first+count)] + [crate]*(32-count)
    pointers = [v for k, v in play if k == sheen]
    assert pointers[:64] == [symbols["tileSet"] + 48*slot for slot in cycle*2]
    assert [v for k, v in play if k == checks[7][0]][:3] == [79, 79, 0]
    stages = (121, 121, 122, 122, 123, 123, symbols["SCENERY_MOUNT"])
    for watch, _ in checks[8:13]:
        assert [v for k, v in play if k == watch][:7] == [stage*257 for stage in stages]
    assert [v for k, v in play if k == colours][:12] == [7 + 256*56, 6 + 256*48]*6
    bases = (symbols["enemyArt"], symbols["yellowArt"])
    if catalog:
        bases = tuple(symbols["enemyArt"] + (2+slot%6)*256 for slot in (1, 9))
        # Slot zero takes the bonus-awarding hit. The survivors reach their
        # gates across two ticks while the projectile pool is saturated.
        opening = play[:[i for i, (k, _) in enumerate(play) if k == end][1]]
        gates = sum(k == armed for k, _ in opening)
        grants = sum(k == accepted for k, _ in opening)
        assert gates >= 14 and grants == 2, (model, "saturated guns", gates, grants)
    for watch, base in zip((flight, yellow), bases):
        poses = [v - base for k, v in play if k == watch]
        first_step = poses.index(64)
        assert 1 <= first_step <= 4 and poses[:first_step] == [0]*first_step
        cycle = [offset for offset in (64, 128, 192, 0) for _ in range(4)]
        assert poses[first_step:first_step+16] == cycle, (model, level, base, poses[:20])
    if bonus:
        assert any(k == checks[-1][0] for k, _ in play)
    margins = [min(FRAME - v % FRAME for k, v in halts if k == pc(phase))
               for phase in ("halt2", "halt1")]
    print(f"{model} level {level}{' + bonus' if bonus else ''}{' + catalog' if catalog else ''}: "
          f"{len(writes)} streamed cells, {len(halts)} frames, "
          f"minimum margins {margins} T", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembler", required=True, type=Path)
    parser.add_argument("--emulator", required=True, type=Path)
    parser.add_argument("--game", type=Path, help="Reuse an assembled default game directory")
    args = parser.parse_args()
    assembler, emulator = (p.resolve(strict=True) for p in (args.assembler, args.emulator))
    with tempfile.TemporaryDirectory(prefix="blokius-sectors-") as tmp:
        root = Path(tmp)
        if args.game:
            game = args.game.resolve(strict=True)
        else:
            stock = root / "source"
            stock.mkdir()
            game = build(ARCHIVE, assembler, stock)
            install(game, assembler, live=True, luminance_logo=True)
        probe = root / "probe"
        make_probe(game, probe, assembler)
        bonus = root / "bonus"
        make_probe(game, bonus, assembler, bonus=True)
        catalog = root / "catalog"
        make_probe(game, catalog, assembler, bonus=True, catalog=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [pool.submit(verify, emulator, probe, model, n)
                    for n in range(1, 10) for model in MODELS]
            jobs.extend(pool.submit(verify, emulator, bonus, model, n, bonus=True)
                        for n in (1, 9) for model in MODELS)
            jobs.extend(pool.submit(verify, emulator, catalog, model, 9, bonus=True, catalog=True)
                        for model in MODELS)
            for job in jobs:
                job.result()


if __name__ == "__main__":
    main()
