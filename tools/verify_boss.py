"""Exercise the sector boss on both machines and optionally export the short playtest TAP."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from build_art import LEVEL_MAPS, ZX0, map_output
from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_gameplay import aim
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run


def assemble(game, assembler):
    for name in ("main.tap", "main.sna"):
        (game / name).unlink()
    run([assembler, *("-D" + flag + "=1" for flag in FLAGS), "--sym=main.sym", "main.asm"], game)


def make_trial(game, dest, assembler):
    shutil.copytree(game, dest)
    # Present columns 243..251 in the opening viewport and stream 252..255.
    # The normal column counter, end padding, last wave and boss all still run.
    for level in range(1, len(LEVEL_MAPS) + 1):
        path = dest / "maps" / (map_output(level) + ".bin")
        original = path.read_bytes()
        opening = bytes(original[x * 6 + y] for y in range(6) for x in range(243, 252))
        trial_map = opening + original[252 * 6:]
        path.write_bytes(trial_map.ljust(len(original), b"\0"))
        run([ZX0 / "zx0.exe", "-f", path, path.with_suffix(".zx0")], dest)
    barrel = dest / "barrelScroll.asm"
    source = barrel.read_text()
    select = "ld (sourceTileMapReadColumn), a"
    assert source.count(select) == 1
    barrel.write_text(source.replace(select, f"ld a,252\n    {select}\n    ld a,SCREEN_TILE_WIDTH+1"))
    assemble(dest, assembler)


def make_pilot(trial, pilot, assembler):
    shutil.copytree(trial, pilot)
    path = pilot / "gameplay.a80"
    src = path.read_text()
    marker = "    call readControls\n"
    assert src.count(marker) == 1
    path.write_text(src.replace(marker, "    call bossTestPilot\n"))

    # Exercise a bonus threshold during the boss explosion. Two surviving
    # ships at the handoff distinguish a carry from the default three.
    path = pilot / "boss.a80"
    src = path.read_text()
    marker = "\nbossEnter:\n"
    assert src.count(marker) == 1
    src = src.replace(marker, marker + "    ld a,1 : ld (playerLives),a\n"
                      "    ld hl,#0195 : ld (hudScore),hl\n")
    path.write_text(src + """
bossTestPilot:
    ld a,65 : ld (invincibleTicks),a
    ld a,(bossXY+1) : add a,2 : ld b,a
    ld a,(playerXY+1) : cp b : ld a,16 : jr z,1f
    ld a,20 : jr nc,1f : ld a,24
1:  ret
""")
    assemble(pilot, assembler)


def verify(trial, emulator, model, level, pilot=False):
    s = read_symbols(trial / "main.sym")
    def pc(label):
        return f"PC={s[label]:04X}H"

    def peek(label):
        return f"PEEK({s[label]:04X}H)"

    def word(label):
        return f"PEEKW({s[label]:04X}H)"

    gate, enter, tick, volley = map(pc, ("finishLastWave", "bossEnter", "gameplayComplete", "bossFire.volley"))
    commit, play = map(pc, ("bossSectorCleared", "firstFrameLogic"))
    emitted = pc("enemyShotEmitted")
    death = pc("bossDestroyed")
    ay_write = pc("soundEffectWrite")
    # Banked data and code can alias PCs before entering gameplay. Analyse
    # only the observed encounter, starting at the first real gameplay frame.
    watches = [(play, peek("selectedLevel")), (pc("writeSpawnArt"), "B"),
               (gate, peek("barrelScrollComplete")), (enter, "TSTATESP"),
               (tick, word("enemy_boxes")), (pc("showGameOver"), "TSTATESP"),
               (tick+" AND 2=2", word("bossXY")), (tick+" AND 3=3", peek("bossHealth")),
               (volley, word("playerXY")), (emitted, "B+256*C+65536*D"), (death, word("hudScore")),
               (commit, peek("playerLives")+"+256*"+word("hudScore")),
               (pc("startLevelRenderer"), peek("playerLives")+"+256*"+word("hudScore")),
               (pc("bossVictory"), word("hudScore")), (pc("menuWait"), "TSTATESP"),
               (pc("halt1"), "TSTATESP"), (pc("halt2"), "TSTATESP")]
    if pilot:
        watches.append((ay_write, "A+256*E"))
    for part in range(1, 4):
        watches.append((tick+f" AND {part+3}={part+3}", f"PEEKW({s['enemy_boxes']+part*2:04X}H)"))
    for part in range(4):
        watches.append((tick+f" AND {part+7}={part+7}", f"PEEKW({s['sprite09']+part*9:04X}H)"))
    keys = trial / f"boss-{model}-{level}.keys"
    keys.write_bytes(str(level).encode() * 12 + b'n' * 150)
    log = breakpoint_log(emulator, trial / "main.tap", model, 60 if pilot else 48, watches, True, keys)
    events = [(k, int(v)) for k, v in HIT.findall(log)]
    first = events.index((play, level-1))
    events = events[first:]
    def values(rows, key):
        return [v for k, v in rows if k == key]

    entrance = next(i for i, (k, _) in enumerate(events) if k == enter)
    opening = events[:entrance]
    spawns = values(opening, pc("writeSpawnArt"))
    assert spawns and len(spawns) % 7 == 0 and set(values(opening, gate)) == {1}, (model, level, spawns)
    assert all(len(set(spawns[i:i+7])) == 1 for i in range(0, len(spawns), 7))
    events = events[entrance:]
    ends = (death, pc("showGameOver"), pc("menuWait"))
    fight_end = next((i for i, (k, _) in enumerate(events) if k in ends), len(events))
    fight = events[:fight_end]
    assert not values(fight, pc("writeSpawnArt"))
    positions = values(fight, tick+" AND 2=2")
    assert positions and positions[0] == 63+18*256
    assert min(pos%256 for pos in positions) == 46
    assert len(set(pos//256 for pos in positions)) >= 6
    for part, key in enumerate((tick, *(tick+f" AND {i}={i}" for i in range(4,7)))):
        offset = 5*(part%2) + 1280*(part//2)
        assert values(fight,key) == [pos+offset for pos in positions], (model,level,"torn boss",part)
        art = values(fight,tick+f" AND {part+7}={part+7}")
        assert art[0] == s["bossArt"]+part*60 and set(art) <= {art[0],s["explosion1"]}
    health = values(fight,tick+" AND 3=3")
    assert health[0] == 8+2*(level-1)
    wings = (level - 1) // 3
    shots = []
    targets = []
    shot_ticks = []
    ticks = 0
    for point, value in fight:
        if point == volley:
            targets.append(value)
        elif point == emitted:
            shots.append(value)
        elif point == tick:
            if targets:
                assert len(targets) == len(shots) == 1 + 2 * wings
                assert len(set(targets)) == len({shot & 65535 for shot in shots}) == 1
                player = (targets[0] % 256, targets[0] // 256)
                origin = shots[0] & 65535
                centre = aim(origin % 256, origin // 256, player)
                expected = [(centre + angle * 8) % 256 for angle in range(-wings, wings + 1)]
                assert [shot >> 16 for shot in shots] == expected, (model, level, shots)
                shot_ticks.append(ticks)
                shots.clear()
                targets.clear()
            ticks += 1
    assert shot_ticks
    period = (36,32,28,32,28,24,24,20,16)[level-1]
    assert all((b-a)%period == 0 for a,b in zip(shot_ticks,shot_ticks[1:]))
    halts = [(k,v) for k,v in fight if k in (pc("halt1"),pc("halt2"))]
    assert len(halts)>64 and all(k!=j and w//FRAME==v//FRAME+1 for (k,v),(j,w) in zip(halts,halts[1:]))
    margin = min(FRAME-v%FRAME for _,v in halts)
    if pilot:
        assert values(events,death) and min(health) <= 2
        carry = values(events, commit)[0]
        handoff = events[next(i for i, (k, _) in enumerate(events) if k == commit):]
        assert values(handoff, ay_write)[:3] == [8, 9, 10]
        # The HUD stores packed BCD hundreds. The boss awards ten of them.
        before = int(f"{values(events, death)[0]:04x}")
        after = int(f"{carry // 256:04x}")
        assert before == 195 and after == before + 10 and carry % 256 == 2
        if level < 9:
            assert values(events,pc("startLevelRenderer"))[0] == carry and level in values(events,play)
        else:
            assert values(events,pc("bossVictory")) == [carry//256] and values(events,pc("menuWait"))
    print(f"{model} level {level}: {len(spawns)//7} complete waves, four joined sprites, {len(shot_ticks)} volleys of {1+2*wings}, "
          f"{margin} T minimum; {'cleared' if pilot else 'playtest TAP'}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "assembler", "emulator"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("--trial-tap", type=Path)
    args = p.parse_args()
    with TemporaryDirectory(prefix="blokius-boss-") as tmp:
        trial = Path(tmp) / "trial"
        assembler = args.assembler.resolve()
        make_trial(args.game.resolve(), trial, assembler)
        if args.trial_tap:
            shutil.copyfile(trial / "main.tap", args.trial_tap)
        pilot = Path(tmp) / "pilot"
        make_pilot(trial, pilot, assembler)
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(verify,game,args.emulator.resolve(),model,level,game==pilot)
                    for game,levels in ((trial,(1,5,9)),(pilot,(1,9))) for level in levels for model in MODELS]
            for job in jobs:
                job.result()
