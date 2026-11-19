"""Verify the playable menu and time ZX0 on both hardware families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import tempfile

from build_art import LEVEL_MAPS, MENU_LOGO, SCREEN_FONT, logo_bands, map_output
from menu_luminance import COPPER_BANDS, COPPER_MENU_TEXT, LUMINANCE_BANDS
from profile_blokius import ARCHIVE, build
from profile_ringo8 import FRAME, HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_blokius_integration import (
    GREEN_FAST_FROM, GREEN_FIRE_COLUMNS, GREEN_SHIP_Y, SHOT_VECTORS, YELLOW_FIRE_COUNTS, install,
)
from verify_gameplay import DOWN, LEFT, PLAYER_START, RESTART, UP, aim, packed
from verify_luminance_writes import verify_luminance_writes
from verify_zesarux_raster import HEIGHT, PAPER_WIDTH, WIDTH, capture_video, paper_row


def verify_logo_video(emulator, game, model, frames_to_check=32):
    s = read_symbols(game / "main.sym")
    width, rows, left, top = (s["MENU_LOGO_" + name] for name in ("WIDTH", "ROWS", "LEFT", "TOP"))
    bitmap = (game / MENU_LOGO).read_bytes()
    bands = LUMINANCE_BANDS if "luminance128" in s else logo_bands()
    if len(bands) != s["MENU_LOGO_PHASES"]:
        raise ValueError("The menu must scroll through the complete colour ribbon")
    if any(bands[i] == bands[i - 1] for i in range(len(bands))):
        raise ValueError("Adjacent logo bands must have distinct colours")
    if any(bands == bands[lag:] + bands[:lag] for lag in range(1, len(bands))):
        raise ValueError("The ribbon repeats before completing its full cycle")

    def ink(attr):
        intensity = 255 if attr & 64 else 192
        return bytes(intensity if attr & channel else 0 for channel in (1, 4, 2))

    cells = {(colour, mask): b"".join(ink(colour) if mask & (1 << bit) else bytes(3)
                                      for bit in range(7, -1, -1))
             for colour in set(bands) for mask in set(bitmap)}

    def logo_rows(phase):
        for y in range(rows * 8):
            character_row, scan = divmod(y, 8)
            start = (scan * rows + character_row) * width
            pixels = bytearray(3 * left * 8)
            for column, value in enumerate(bitmap[start:start + width]):
                colour = bands[(phase + y + column) % len(bands)]
                pixels += cells[colour, value]
            yield bytes(pixels).ljust(3 * PAPER_WIDTH, b"\0")

    phases = {b"".join(logo_rows(phase)): phase for phase in range(s["MENU_LOGO_PHASES"])}
    copper_rows = {}
    if "menuCopperRows" in s:
        # Include the infrequent high-cost music ticks at steady state.
        frames_to_check = max(frames_to_check, 360)
        font = (game / SCREEN_FONT).read_bytes()
        for row, line in COPPER_MENU_TEXT.items():
            for y, colour in enumerate(COPPER_BANDS):
                attributes = (font[8 * (ord(char) - 32) + y] for char in line.ljust(32))
                copper_rows[8 * row + y] = b"".join(ink(colour) if mask & (128 >> bit) else bytes(3)
                                                    for mask in attributes for bit in range(8))
    video = game / f"menu-logo-{model}.raw"
    capture_video(emulator, model, ["--tape", game / "main.tap", "--fastautoload",
                                    "--frameskip", "0", "--disable-autoframeskip", "--vofilefps", "50"],
                  video, 8 + frames_to_check // 25)
    frame_bytes = WIDTH * HEIGHT * 3
    previous = None
    with video.open("rb") as recording:
        recording.seek(-frames_to_check * frame_bytes, 2)
        for _ in range(frames_to_check):
            frame = recording.read(frame_bytes)
            logo = b"".join(paper_row(frame, y) for y in range(top * 8, (top + rows) * 8))
            phase = phases.get(logo)
            if phase is None:
                raise ValueError(f"{model}: menu logo bands are misaligned")
            if previous is not None and phase != (previous + 1) % len(bands):
                raise ValueError(f"{model}: expected one scanline per frame, got phases {previous}, {phase}")
            for y, expected in copper_rows.items():
                if paper_row(frame, y) != expected:
                    raise ValueError(f"{model}: menu text shading or glyph mismatch on scanline {y}")
            previous = phase
    video.unlink()


def verify_choice(emulator, game, model, choice):
    s = read_symbols(game / "main.sym")
    if (s["PLAYFIELD_HEIGHT"], s["ENEMY_COUNT"], s["WAVE_ENEMIES"]) != (46, 24, 15):
        raise ValueError("Expected the bottom HUD, 24 projectile slots and fifteen enemy slots")
    points = {name: f"PC={s[name]:04X}H" for name in (
        "menuWait", "levelUnpackBegin", "levelUnpackEnd", "levelPageRestored",
        "enableRender", "renderFrame1", "firstFrameLogic", "halt2",
    )}
    watch = [(point, "TSTATESP") for point in points.values()]
    checks = {}

    def expect_at(name, expression, value):
        point = points.get(name, name)
        condition = f"{point} AND {len(watch)}={len(watch)}"
        watch.append((condition, expression))
        checks[condition] = value

    def peek(address):
        return f"PEEK({address:04X}H)"

    input_page = 0x11 if model == "128k" else 0x14
    controls, reader = {
        2: ("j" * 8, "readKempston"),
        3: ("s" * 8, "readSinclair"),
        4: ("s" * 4 + "k" * 4, "readControls"),
    }.get(choice, ("", "readControls"))
    expect_at("menuWait", f"PEEKW({s['intProc'] + 1:04X}H)", s["nullProc"])
    expect_at("firstFrameLogic", f"PEEKW({s['controlReader'] + 1:04X}H)", s[reader])
    expect_at("levelUnpackBegin", f"PEEKW({s['intProc'] + 1:04X}H)", s["nullProc"])
    expect_at("levelUnpackBegin", "HL", s[f"packedLevel{choice}"])
    expect_at("levelUnpackBegin", peek(s["pageTable"] + 1), input_page)
    expect_at("levelUnpackBegin", peek(s["currentPage"]), 1)
    expect_at("levelPageRestored", peek(s["currentPage"]), 0)
    expect_at("firstFrameLogic", f"PEEKW({s['intProc'] + 1:04X}H)", s["renderFrame2"])

    font = (game / SCREEN_FONT).read_bytes()
    if any(font[::8]):
        raise ValueError("Every glyph must begin with a blank scanline")
    # The first gameplay frame has already drawn the level, lives and score.
    for column in range(0, 32, 2):
        expect_at("firstFrameLogic", f"PEEKW({0x50E0 + column:04X}H)", 0)
    for name, address, char in (("menuWait", 0x4846, "1"), ("levelUnpackBegin", 0x4897, str(choice))):
        for row in range(8):
            expect_at(name, peek(address + row * 256), font[(ord(char) - 32) * 8 + row])
    for address in (0x50E0, 0xD0E0):
        hud = f"PC={s['hudLevelDrawn']:04X}H AND D={address >> 8:02X}H"
        for column, char in ((0, "L"), (6, str(choice))):
            for row in range(8):
                expect_at(hud, peek(address + row * 256 + column), font[(ord(char) - 32) * 8 + row])
        for column in (0, 31):
            expect_at(hud, peek(address + 0xA00 + column), 0x47)
    level = game / "maps" / f"{map_output(choice)}.bin"
    expected = level.read_bytes()
    for offset in (0, 8, 9, 27, 53, 54, 72, 130, 580, 999, 1534):
        address = s["sourceTileMap"] + offset
        expect_at("levelUnpackEnd", f"PEEKW({address:04X}H)", int.from_bytes(expected[offset:offset + 2], "little"))
    expect_at("levelUnpackEnd", "DE", s["sourceTileMap"] + len(expected))
    spool = game / f"menu-{model}-{choice}.txt"
    spool.write_text(controls + str(choice) * 80, encoding="ascii")
    boot_log = breakpoint_log(emulator, game / "main.tap", model, 20, watch,
                              fast_autoload=True, keyboard_spool=spool)
    hits = {}
    for condition, value in HIT.findall(boot_log):
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

    # Use a sparse trace for sustained gameplay. The emulator tests every
    # breakpoint at each instruction, even after the startup probes pass.
    spool.write_text(str(choice) * 80, encoding="ascii")
    frame2_halt = f"PC={s['halt1']:04X}H"
    watch = [(points["halt2"], "TSTATESP"), (frame2_halt, "TSTATESP")]
    wave_probe = f"PC={s['stepWave.saveSlot']:04X}H"
    queue_probe = f"PC={s['queueGreenShot']:04X}H"
    shot_probe = f"PC={s['enemyShotEmitted']:04X}H"
    motion_probe = f"{points['halt2']} AND 1=1"
    yellow_probe = f"{points['halt2']} AND 2=2"
    wave_clock_probe = f"{wave_probe} AND 1=1"
    watch.extend(((wave_probe, "PEEK(HL)+PEEK(IX)*256"), (wave_clock_probe, "TSTATESP"),
                  (queue_probe, "PEEKW(HL)"),
                  (shot_probe, "B+C*256+D*65536"),
                  (motion_probe, f"PEEKW({s['enemy_records']:04X}H)"),
                  (yellow_probe, f"PEEKW({s['enemy_boxes'] + 16:04X}H)"
                   f"+PEEK({s['enemyMotion'] + 16:04X}H)*65536")))
    yellow_queue = f"PC={s['moveYellow.shotQueued']:04X}H"
    yellow_queue_clock = yellow_queue + " AND 1=1"
    watch.extend(((yellow_queue, "A"), (yellow_queue_clock, "TSTATESP")))
    log = breakpoint_log(emulator, game / "main.tap", model, 50 if 4 <= choice <= 5 else 32, watch,
                         fast_autoload=True, keyboard_spool=spool)
    rows = [(condition, int(value)) for condition, value in HIT.findall(log)]
    halts = {points["halt2"]: 0, frame2_halt: 1}
    timing = [(halts[condition], value) for condition, value in rows if condition in halts]
    frame_pairs = len(timing) // 2
    if frame_pairs < 150 or any(phase == other or second // FRAME - first // FRAME != 1
                               for (phase, first), (other, second) in zip(timing, timing[1:])):
        raise ValueError(f"{model} map {choice}: irregular gameplay across {frame_pairs} frame pairs")
    headroom = [min(FRAME - value % FRAME for phase, value in timing if phase == slot) for slot in (0, 1)]
    entrances = [value for condition, value in rows if condition == wave_probe]
    yellow_count = YELLOW_FIRE_COUNTS[choice - 1]
    opening = [GREEN_SHIP_Y[0][3]] * 8
    yellow_spawns = []
    if yellow_count != 255:
        opening.extend(128 * 256 + y for y in (8, 35, 15, 39, 19, 28, 4, 24))
        clocks = [v // FRAME for condition, v in rows if condition == wave_clock_probe]
        yellow_spawns = clocks[8:16]
        green_to_yellow = (clocks[8] - clocks[7]) // 2
        if (choice <= 5 and green_to_yellow < 144) or (choice >= 7 and green_to_yellow >= 144):
            raise ValueError(f"{model} map {choice}: unexpected spacing between waves")
        gaps = [b - a for a, b in zip(yellow_spawns, yellow_spawns[1:])]
        if len(gaps) != 7 or min(gaps) != 10 or (choice <= 5 and max(gaps) != 10):
            raise ValueError(f"{model} map {choice}: incorrect yellow entry intervals {gaps}")
    opening.append(64 * 256 + GREEN_SHIP_Y[1][3])
    if entrances[:len(opening)] != opening:
        raise ValueError(f"{model} map {choice}: expected entrances {opening}, saw {entrances[:len(opening)]}")
    queued = [value for condition, value in rows if condition == queue_probe]
    shots = [value for condition, value in rows if condition == shot_probe]
    yellow_shots = [shot for shot in shots if shot & 255 in (38, 50)]
    shots = [shot for shot in shots if shot & 255 not in (38, 50)]
    yellow_origins = [value for condition, value in rows if condition == yellow_queue]
    yellow_clocks = [v // FRAME for condition, v in rows if condition == yellow_queue_clock]
    check_yellow_path(rows, yellow_probe, yellow_count, yellow_spawns,
                      list(zip(yellow_clocks, yellow_origins, strict=True)), yellow_shots)
    column = GREEN_FIRE_COLUMNS[choice - 1]
    if column == 96:
        if queued or shots:
            raise ValueError(f"{model} map {choice}: an unarmed ship fired")
    else:
        expected_origin = packed((column, GREEN_SHIP_Y[0][column] + 2))
        first_bearing = aim(column, expected_origin >> 8, PLAYER_START)
        minimum_shots = 12 if yellow_count == 255 else 8
        if (len(shots) < minimum_shots or len(shots) != len(queued)
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
            "unpack_tstates": stop - start, "gameplay_frame_pairs": frame_pairs, "minimum_headroom": headroom,
            "green_shots": len(shots), "yellow_shots": len(yellow_shots)}


def check_yellow_path(rows, probe, fire_count, spawns, queued, shots):
    states = [(v & 255, v >> 8 & 255, v >> 16) for condition, v in rows if condition == probe]
    if fire_count == 255:
        if any(state & 128 for _, _, state in states) or queued or shots:
            raise ValueError("Yellow ships appeared on a green-only level")
        return
    first = states.index((67, 8, 128))
    turn = states.index((26, 8, 129), first)
    approach = states[first:turn]
    if [x for x, _, _ in approach] != list(range(67, 26, -1)) or any(y != 8 for _, y, _ in approach):
        raise ValueError("Yellow flier's approach was not straight")
    retreat = states[turn + 1:turn + 13]
    if ([x for x, _, _ in retreat] != list(range(28, 51, 2))
            or [y for _, y, _ in retreat] != [8 + step * 13 // 12 for step in range(1, 13)]
            or retreat[-1][2] != 192
            or [x for x, _, _ in states[turn + 13:turn + 16]] != [49, 48, 47]):
        raise ValueError(f"Incorrect yellow retreat or exit {retreat}")
    firing = ((), ((53, 50),), ((47, 38), (53, 50)))[fire_count]
    expected = sorted((spawn + 2 * delay, column) for spawn in spawns for delay, column in firing)
    if (sorted(queued[:len(expected)]) != expected
            or sorted(shot & 255 for shot in shots) != sorted(column for _, column in queued)):
        raise ValueError("Yellow shot count or firing positions differ from the level profile")


def verify_green_corners(emulator, game, model):
    """Park at the top left, restart, then park at the bottom left on level 8."""
    s = read_symbols(game / "main.sym")
    player, shot, contact, restart = (f"PC={s[name]:04X}H" for name in (
        "updatePlayerLife.checkPlayer", "enemyShotEmitted", "checkPlayerContact.hit", "restartGame",
    ))
    spool = game / f"green-corners-{model}.txt"
    spool.write_text("8" * 80, encoding="ascii")
    watch = [(player, f"PEEKW({s['playerXY']:04X}H)+PEEK({s['player_hit']:04X}H)*65536"),
             (shot, "B+C*256+D*65536"), (contact, "A"), (restart, "A")]
    log = breakpoint_log(emulator, game / "main.tap", model, 24, watch, fast_autoload=True, keyboard_spool=spool)
    runs = [[]]
    for point, value in HIT.findall(log):
        if point == restart:
            runs.append([])
        else:
            runs[-1].append((point, int(value)))
    if len(runs) != 2:
        raise ValueError(f"{model}: expected an Enter restart between green wave entrances")
    for y, events in zip((0, s["PLAYER_BOTTOM"]), runs):
        corner = packed((0, y))
        entry_shot = packed((63, y + 2))  # bearing zero means straight left
        fired_at_corner = False
        position = None
        for point, value in events:
            if point == player:
                position = value & 65535
                if value >> 16:
                    if fired_at_corner and position == corner:
                        break
                    raise ValueError(f"{model}: first hit missed the expected corner at Y={y}")
            elif point == shot and value == entry_shot and position == corner:
                fired_at_corner = True
            elif point == contact or (point == shot and value & 255 != 63):
                raise ValueError(f"{model}: another attack reached the corner test at Y={y}")
        else:
            raise ValueError(f"{model}: green shots failed to hit the corner at Y={y}")


def verify_redefined_keys(emulator, game, model):
    s = read_symbols(game / "main.sym")
    capture, apply, select, controls, restart, halt1, halt2 = (
        f"PC={s[name]:04X}H" for name in (
            "redefineKeys.save", "applyCustomKeys", "menuSelected", "controlsReady",
            "restartGame", "halt1", "halt2",
        )
    )
    reader = select + " AND 1=1"
    code = s["customKeyCode"]
    cached = select + " AND 2=2"
    # Enter/L, S/A and Z/X share three separate matrix rows.
    row_reloads = "+".join(f"PEEK({code + offset:04X}H)*{256 ** index}"
                           for index, offset in enumerate((11, 29, 47)))
    watch = [(capture, "C"), (apply, "TSTATESP"), (select, "A"), (controls, "A"),
             (restart, "TSTATESP"), (halt1, "TSTATESP"), (halt2, "TSTATESP"),
             (reader, f"PEEKW({s['controlReader'] + 1:04X}H)+PEEK({s['menuControl']:04X}H)*65536"),
             (cached, row_reloads)]
    spool = game / f"redefine-{model}.txt"
    # Ignore M and a second Z, then cancel a second definition after pressing A.
    spool.write_bytes(b"n" * 45 + b"srmzzxasl" + b"b" * 5 + b"ra\r" + b"b" * 5 + b"sk8"
                      + b"b" * 12 + b"".join(bytes((key,)) * 6 for key in b"zxasl")
                      + b"\r" + b"b" * 3 + b"z" * 6 + b"b" * 55)
    log = breakpoint_log(emulator, game / "main.tap", model, 44, watch,
                         fast_autoload=True, keyboard_spool=spool)
    rows = [(point, int(value)) for point, value in HIT.findall(log)]

    def values(point):
        return [value for label, value in rows if label == point]

    if (values(capture) != [1, 2, 5, 6, 31, 5] or len(values(apply)) != 1
            or values(select) != [ord("8")] or values(reader) != [s["readCustomControls"]]):
        raise ValueError(f"{model}: key capture, cancellation or control selection failed")
    if values(cached) != [0x7D7C7A]:  # LD A,D / LD A,H / LD A,L
        raise ValueError(f"{model}: the generated reader did not reuse the three shared rows")
    if set(values(controls)) != {0, 1, 2, 4, 8, 16, 32} or len(values(restart)) != 1:
        raise ValueError(f"{model}: redefined controls or Enter restart failed")
    after_restart = rows.index((restart, values(restart)[0]))
    if (controls, 2) not in rows[after_restart:]:
        raise ValueError(f"{model}: the Left binding was lost after restart")
    timing = [(point, value) for point, value in rows if point in (halt1, halt2)]
    if len(timing) < 150 or any(p == q or end // FRAME - start // FRAME != 1
                               for (p, start), (q, end) in zip(timing, timing[1:])):
        raise ValueError(f"{model}: irregular frame cadence with redefined keys")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("assembler", "emulator", "output-tap"):
        parser.add_argument(f"--{arg}", type=Path, required=arg != "output-tap")
    parser.add_argument("--luminance-logo", action="store_true")
    args = parser.parse_args()
    assembler, emulator = (p.resolve(strict=True) for p in (args.assembler, args.emulator))
    with tempfile.TemporaryDirectory(prefix="shmup-levels-") as scratch:
        game = build(ARCHIVE, assembler, Path(scratch))
        install(game, assembler, live=True, luminance_logo=args.luminance_logo)
        if args.luminance_logo:
            verify_luminance_writes(game / "gfx", (game / MENU_LOGO).read_bytes())
        corner_scratch = Path(scratch) / "corner-test"
        corner_scratch.mkdir()
        corner_game = build(ARCHIVE, assembler, corner_scratch)
        replay = [LEFT | UP] * 24 + [0] * 96 + [RESTART] + [LEFT | DOWN] * 24 + [0] * 115
        install(corner_game, assembler, live=True, replay=replay, solid_menu_logo=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            logos = [pool.submit(verify_logo_video, emulator, build_game, model)
                     for build_game in (game, corner_game) for model in MODELS]
            for check in logos:
                check.result()
            corners = [pool.submit(verify_green_corners, emulator, corner_game, model) for model in MODELS]
            keys = [pool.submit(verify_redefined_keys, emulator, game, model) for model in MODELS]
            checks = [pool.submit(verify_choice, emulator, game, model, choice)
                      for choice in range(1, len(LEVEL_MAPS) + 1) for model in MODELS]
            for check in (*corners, *keys):
                check.result()
            results = [check.result() for check in checks]
        if args.output_tap:
            args.output_tap.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(game / "main.tap", args.output_tap)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
