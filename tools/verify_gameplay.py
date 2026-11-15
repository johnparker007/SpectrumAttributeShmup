"""Build the playable barrel-scroll TAP and verify gameplay on both Spectrum families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from benchmark_motion import DEAD, step
from moving_overlay import hit
from profile_blokius import build, capture
from profile_ringo8 import HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_ay_stream import register_pairs
from verify_blokius_integration import examine, install
from verify_dot_overlay import verify_audio
from verify_score_hud import assemble_arithmetic_probe, check_arithmetic, check_hud_updates, check_hud_video
from verify_zesarux_raster import HEIGHT, WIDTH, capture_video, paper_row, run


RIGHT, LEFT, UP, DOWN, FIRE, RESTART = (1, 2, 4, 8, 16, 32)
REPLAY = ([0] * 6 + [FIRE] * 37 + [LEFT | UP | FIRE] * 32 + [RIGHT | DOWN | FIRE] * 64
          + [LEFT | UP] * 18 + [LEFT | RIGHT | UP | DOWN] * 9 + [0] * 60
          + [RESTART] * 4 + [0] * 535 + [RESTART | FIRE] * 4 + [FIRE] * 46)
IDLE = [0] * 120
WAVES = (
    (0, ((52, 21, 0, 0),)),
    (1, ((54, 12, 16, 16), (57, 31, 8, 8))),
    (0, ((52, 15, 24, 16), (57, 23, 40, 48), (59, 33, 32, 8))),
)
HIDDEN = (96, 0)


def box_visible(point):
    return point[0] < 64


def packed(values):
    return int.from_bytes(bytes(values), "little")


def expected(inputs):
    restart_held = False
    results = []
    for index, command in enumerate(inputs):
        emitted = None
        restart = bool(command & RESTART) and not restart_held
        restart_held = bool(command & RESTART)
        if index == 0 or restart:
            player = (8, 21)
            health, kills, invulnerable, reload, respawn, cursor = 3, 0, 0, 0, 0, 0
            tick = wave = emitter = 0
            enemies = [(52, 21), HIDDEN, HIDDEN]
            enemy_hits = [False] * 3
            player_hit = False
            incoming = [(DEAD, 0, 0)] * 32
            volleys = [(DEAD, 0, 0)] * 3
            shots = [(DEAD, 0)] * 9
        if not restart:
            if invulnerable:
                invulnerable -= 1
            elif player_hit and health:
                health -= 1
                invulnerable = 24
            if health:
                x, y = player
                dx = bool(command & RIGHT) - bool(command & LEFT)
                dy = bool(command & DOWN) - bool(command & UP)
                player = (max(2, min(59, x + dx)), max(0, min(43, y + dy)))
                if reload:
                    reload -= 1
                elif command & FIRE and player[0] <= 57:
                    free = next((n for n, (x, _, _) in enumerate(volleys) if x == DEAD), None)
                    if free is not None:
                        volleys[free] = (player[0] + 4, player[1] + 2, -1)
                        reload = 8
            if any(map(box_visible, enemies)):
                for slot, (x, y) in enumerate(enemies):
                    if x >= 64:
                        continue
                    if enemy_hits[slot]:
                        kills += 1
                        enemies[slot] = (96, y)
                    elif tick % 4 == 0:
                        enemies[slot] = (x - 1 if x > 2 else 96, y)
                if not any(map(box_visible, enemies)):
                    respawn = 28
            else:
                respawn -= 1
                if respawn == 0:
                    wave = (wave + 1) % len(WAVES)
                    enemies = [(x, y) for x, y, _, _ in WAVES[wave][1]]
                    enemies += [HIDDEN] * (3 - len(enemies))
                    emitter = 0
            incoming, volleys, shots = step(incoming, volleys)
            cadence, ships = WAVES[wave]
            if not (tick & cadence):
                slot = emitter
                emitter = (emitter + 1) % len(ships)
                x, y = enemies[slot]
                if x < 64 and incoming[cursor][0] == DEAD:
                    path = ships[slot][3 if tick & 4 else 2]
                    incoming[cursor] = (x - 1, y + 2, path)
                    emitted = (x - 1, y + 2, path, wave, tick)
                    cursor = (cursor + 1) % len(incoming)
            tick = (tick + 1) % 256
        player_hit = health > 0 and bool(hit(player, [(x, y) for x, y, _ in incoming], 1))
        enemy_hits = [box_visible(enemy) and bool(hit(enemy, shots, 2)) for enemy in enemies]
        results.append({
            "header": packed((tick, command, health, kills)),
            "player": packed(player), "enemies": [packed(enemy) for enemy in enemies],
            "wave": wave, "restart": restart, "emitted": emitted,
            "flags": [packed(255 * flag for flag in enemy_hits[:2]),
                      packed((255 * enemy_hits[2], 255 * player_hit))],
            "volleys": [packed(volley) for volley in volleys],
            "incoming": [packed(dot) for dot in incoming],
            "shots": [packed(shot) for shot in shots],
        })
    return results


def verify_logic(emulator, game, model, inputs, seconds):
    symbols = read_symbols(game / "main.sym")

    def peek(label, length=1, offset=0):
        address = symbols[label] + offset
        prefix = f"PEEKW({address:04X}H)" if length > 1 else f"PEEK({address:04X}H)"
        if length == 3:
            return prefix + f"+PEEK({address + 2:04X}H)*65536"
        return prefix

    # Collision flags describe the layout just plotted in Frame 2.
    point = f"PC={symbols['overlayEnd']:04X}H"
    fields = [
        ("header", "+".join(f"{peek(label)}*{256**n}" for n, label in
                            enumerate(("gameTick", "lastControls", "playerHealth", "enemyKills")))),
        ("player", peek("playerXY", 2)),
        ("wave", peek("waveIndex")),
        ("score", peek("hudScore", 2)),
        ("flags", peek("collision_actual", 2)),
        ("flags", peek("collision_actual", offset=2) + "+" + peek("player_hit") + "*256"),
    ]
    fields += [("enemies", peek("enemy_boxes", 2, 2 * slot)) for slot in range(3)]
    fields += [("volleys", peek("volleys", 3, 3 * slot)) for slot in range(3)]
    fields += [("incoming", peek("enemy_records", 3, 3 * slot)) for slot in (0, 15, 31)]
    fields += [("shots", peek("player_shots", 2, 2 * slot)) for slot in (0, 1, 2, 8)]
    points = [(f"{point} AND {n}={n}", expression) for n, (_, expression) in enumerate(fields, 1)]
    oracle = expected(inputs)
    log = breakpoint_log(emulator, game / "main.tap", model, seconds, points, fast_autoload=True)
    hits = HIT.findall(log)
    if len(hits) != log.count("Catch breakpoint:") or len(hits) // len(points) < len(oracle):
        raise ValueError(f"{model}: captured {len(hits) // len(points)} of {len(oracle)} gameplay ticks")
    for tick, state in enumerate(oracle):
        row = hits[tick * len(points):(tick + 1) * len(points)]
        sample = [state[key] for key in ("header", "player", "wave")]
        sample.append(int(str(state["header"] >> 24), 16))
        sample += state["flags"] + state["enemies"]
        sample += state["volleys"]
        sample += [state["incoming"][slot] for slot in (0, 15, 31)]
        sample += [state["shots"][slot] for slot in (0, 1, 2, 8)]
        for (condition, value), (expected_condition, _), wanted, (field, _) in zip(row, points, sample, fields):
            if (condition, int(value)) != (expected_condition, wanted):
                raise ValueError(f"{model}: gameplay tick {tick + 1}, {field} yielded {value}, expected {wanted}")
    return {
        "ticks": len(oracle), "kills": max(state["header"] >> 24 for state in oracle),
        "minimum_health": min(state["header"] >> 16 & 255 for state in oracle),
        "waves_verified": sorted({state["wave"] + 1 for state in oracle}),
        "restarts_verified": sum(state["restart"] for state in oracle),
        "peak_enemy_dots": max(sum(dot % 256 != DEAD for dot in state["incoming"]) for state in oracle),
    }


def verify_gameplay_video(emulator, replay, model):
    video = replay / f"gameplay-{model}.raw"
    capture_video(emulator, model, ["--tape", replay / "main.tap", "--fastautoload", "--vofilefps", "25"], video, 10)
    colours = {"green": (0, 1, 0), "magenta": (1, 0, 1), "cyan": (1, 1, 0), "yellow": (0, 1, 1)}
    pixels = {name: tuple(bytes(component * brightness for component in rgb) * 4 for brightness in (192, 255))
              for name, rgb in colours.items()}
    scenes = []
    # Match sampled frames against the first encounter, before the player
    # starts to move. The ships and bullets must appear in the same frame.
    for state in expected(REPLAY)[6:43]:
        px, py = state["player"] % 256, state["player"] // 256
        ex, ey = state["enemies"][0] % 256, state["enemies"][0] // 256
        cyan_x, cyan_y = state["shots"][0] % 256, state["shots"][0] // 256
        yellow_x, yellow_y = state["incoming"][0] % 256, (state["incoming"][0] >> 8) & 255
        if ex >= 64 or cyan_x == DEAD or yellow_x == DEAD:
            continue
        scenes.append(((px + 1, py, "green"), (px + 4, py + 2, "green"),
                       (ex + 3, ey, "magenta"),
                       (cyan_x, cyan_y, "cyan"), (cyan_x + 1, cyan_y, "cyan"),
                       (yellow_x, yellow_y, "yellow")))
    observed = set()
    with video.open("rb") as recording:
        while frame := recording.read(WIDTH * HEIGHT * 3):
            if len(frame) != WIDTH * HEIGHT * 3:
                raise ValueError(f"{model}: truncated gameplay video")
            for index, scene in enumerate(scenes):
                if all(all(paper_row(frame, y * 4 + line)[x * 12:(x + 1) * 12] in pixels[colour]
                           for line in range(4)) for x, y, colour in scene):
                    observed.add(index)
    if len(observed) < 2:
        raise ValueError(f"{model}: captured {len(observed)} scenes with both ships and both projectile colours")
    return len(observed)


def verify_dense_pool(emulator, game, model):
    oracle = expected(REPLAY)
    tick, state = next((n, state) for n, state in enumerate(oracle, 1)
                       if all(dot % 256 != DEAD for dot in (*state["incoming"], *state["shots"])))
    symbols = read_symbols(game / "main.sym")
    marker = f"PC={symbols['overlayEnd']:04X}H AND PEEK({symbols['gameTick']:04X}H)={tick}"
    points = []
    values = []
    for label, key, stride in (("enemy_records", "incoming", 3), ("player_shots", "shots", 2)):
        for slot, value in enumerate(state[key]):
            address = symbols[label] + stride * slot
            expression = f"PEEKW({address:04X}H)"
            if stride == 3:
                expression += f"+PEEK({address + 2:04X}H)*65536"
            n = len(points) + 1
            points.append((f"{marker} AND {n}={n}", expression))
            values.append(value)
    log = breakpoint_log(emulator, game / "main.tap", model, 46, points, fast_autoload=True)
    hits = HIT.findall(log)
    wanted = [(point, str(value)) for (point, _), value in zip(points, values)]
    if hits[:len(wanted)] != wanted or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: full projectile-pool state differs at tick {tick}, captured {len(hits)} fields")
    return len(values)


def verify_keyboard(emulator, game, model):
    # ZEsarUX feeds these as real matrix presses through its null driver.
    spool = game / f"keyboard-{model}.txt"
    spool.write_bytes(b"poq a\r" * 22)
    symbols = read_symbols(game / "main.sym")
    point = f"PC={symbols['controlsReady']:04X}H"
    reset = f"PC={symbols['restartGame']:04X}H"
    log = breakpoint_log(emulator, game / "main.tap", model, 14, [(point, "A"), (reset, "A")],
                         fast_autoload=True, keyboard_spool=spool)
    hits = HIT.findall(log)
    seen = {int(mask) for condition, mask in hits if condition == point}
    if (len(hits) != log.count("Catch breakpoint:")
            or not {RIGHT, LEFT, UP, DOWN, FIRE, RESTART} <= seen
            or not any(condition == reset for condition, _ in hits)):
        raise ValueError(f"{model}: keyboard matrix test observed {sorted(seen)}")
    return sorted(seen)


def verify_rewind(emulator, replay, model):
    symbols = read_symbols(replay / "main.sym")
    point = f"PC={symbols['halt2']:04X}H"
    index = symbols["sourceTileMapReadIndex"]
    scroll = symbols["tileMapScroll_H"]
    expressions = [f"PEEKW({index:04X}H)*256+PEEK({scroll:04X}H)"]
    width = symbols["tileMapWidth"]
    for column in (0, width // 2):
        for first in (0, 3):
            cells = [symbols["tileMap"] + width * row + column for row in range(first, first + 3)]
            expressions.append("+".join(f"PEEK({cell:04X}H)*{256**n}" for n, cell in enumerate(cells)))
    for tile in (3, 12, 13, 28, 29):
        expressions.append(f"PEEKW({symbols['tilesLUT'] + 2 * tile:04X}H)")
    points = [(f"{point} AND {n}={n}", expression) for n, expression in enumerate(expressions, 1)]
    log = breakpoint_log(emulator, replay / "main.tap", model, 120, points, fast_autoload=True)
    hits = HIT.findall(log)
    windows = [n for n, row in enumerate(expected(REPLAY)) if row["restart"]]
    span = 24
    if len(hits) != log.count("Catch breakpoint:") or len(hits) // len(points) < windows[-1] + span + 1:
        raise ValueError(f"{model}: rewind trace captured only {len(hits) // len(points)} game ticks")
    groups = []
    for start in range(0, len(hits) - len(points) + 1, len(points)):
        row = hits[start:start + len(points)]
        if any(observed != wanted for (observed, _), (wanted, _) in zip(row, points)):
            raise ValueError(f"{model}: rewind trace markers are out of order")
        groups.append(tuple(int(value) for _, value in row))
    for tick in windows:
        if groups[tick][0] % 256 != 0 or groups[tick + 1:tick + span + 1] != groups[:span]:
            raise ValueError(f"{model}: restart at tick {tick + 1} did not rewind the barrel scroll and tile animation")
    return {"restarts": len(windows), "matching_scrolled_ticks_per_restart": span}


def verify_wave_fire(emulator, replay, model):
    symbols = read_symbols(replay / "main.sym")
    wave, tick = symbols["waveIndex"], symbols["gameTick"]
    point = f"PC={symbols['enemyShotEmitted']:04X}H"
    # B/C are the emitted X/Y, D is the trajectory index before its first step.
    expression = f"B+C*64+D*512+PEEK({wave:04X}H)*32768+PEEK({tick:04X}H)*131072"
    shots = [row["emitted"] for row in expected(REPLAY) if row["emitted"] is not None]
    wanted = [(point, str(x + 64 * y + 512 * path + 32768 * w + 131072 * t)) for x, y, path, w, t in shots]
    log = breakpoint_log(emulator, replay / "main.tap", model, 65, [(point, expression)], fast_autoload=True)
    hits = HIT.findall(log)
    if hits[:len(wanted)] != wanted or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: wave fire trace differs from the reference, captured {len(hits)} emissions")
    return {"emissions_verified": len(wanted), "trajectories_verified": sorted({path // 8 for _, _, path, _, _ in shots})}


def verify(emulator, stock, game, replay, model, seconds, replay_seconds, audio):
    # Bound concurrent headless runs on the user's machine.
    with ThreadPoolExecutor(max_workers=3) as pool:
        reference = pool.submit(capture, emulator, stock, model, seconds, paging=True)
        raster = pool.submit(capture, emulator, replay, model, replay_seconds, paging=True, scenery=True)
        live_raster = pool.submit(capture, emulator, game, model, seconds, paging=True, scenery=True)
        played = pool.submit(verify_logic, emulator, replay, model, REPLAY, 135)
        idle = pool.submit(verify_logic, emulator, game, model, IDLE, 32)
        art = pool.submit(verify_gameplay_video, emulator, replay, model)
        keyboard = pool.submit(verify_keyboard, emulator, game, model)
        dense_pool = pool.submit(verify_dense_pool, emulator, replay, model)
        music = pool.submit(verify_audio, emulator, replay, model, audio, True)
        scenery = pool.submit(verify_rewind, emulator, replay, model)
        wave_fire = pool.submit(verify_wave_fire, emulator, replay, model)
        scores = [state["header"] >> 24 for state in expected(REPLAY)]
        hud_updates = pool.submit(check_hud_updates, emulator, replay, model, scores)
        hud_video = pool.submit(check_hud_video, emulator, replay, model)
        _, baseline = examine(reference.result(), model)
        report = {}
        for label, trace in (("replay", raster.result()), ("keyboard_idle", live_raster.result())):
            margins, cases = examine(trace, model)
            for phase, signatures in cases.items():
                match = set(baseline[phase])
                if any(signature not in match for signature in signatures):
                    raise ValueError(f"{model}: {label} Frame {phase} differs from the stock paging trace")
            report[label] = {"pairs": min(map(len, cases.values())),
                             "minimum_headroom": [min(margins[phase]) for phase in (1, 2)]}
        if report["replay"]["pairs"] < len(REPLAY):
            raise ValueError(f"{model}: replay paging trace ended before tick {len(REPLAY)}. Increase --replay-seconds.")
        report["replay"].update(played.result())
        report["replay"]["simultaneous_shots_verified"] = dense_pool.result()
        report["keyboard_idle"].update(idle.result())
        check_arithmetic(emulator, replay, model)
        hud = {**hud_updates.result(), "scores_seen_in_video": hud_video.result()}
        return {"model": model, **report, "gameplay_video_scenes": art.result(),
                "keyboard_masks": keyboard.result(), "scenery_rewind": scenery.result(),
                "wave_fire": wave_fire.result(), "score_hud": hud, **music.result()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "assembler", "emulator", "phrase-reference", "output-tap"):
        parser.add_argument(f"--{arg}", required=arg != "output-tap", type=Path)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--seconds", type=int, default=115, help="raster capture time per build")
    parser.add_argument("--replay-seconds", type=int, default=290, help="raster capture time for the longer replay")
    args = parser.parse_args()
    if min(args.seconds, args.replay_seconds) < 1:
        parser.error("Capture times must be positive")
    try:
        emulator, assembler = (path.resolve(strict=True) for path in (args.emulator, args.assembler))
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        reference = json.loads(args.phrase_reference.read_text(encoding="utf-8-sig"))
        if not reference["passed"] or not reference.get("through_loop") or reference["emulator"] != version:
            raise ValueError("Expected the verified full-song AY reference")
        tune = reference["results"][0]
        audio = [register_pairs(tune["initial_writes"]), *(register_pairs(tick["writes"]) for tick in tune["ticks"])]
        with tempfile.TemporaryDirectory(prefix="blokius-gameplay-") as scratch:
            root = Path(scratch)
            (root / "stock").mkdir()
            stock = build(args.archive, assembler, root / "stock")
            game = Path(shutil.copytree(stock, root / "game"))
            replay = Path(shutil.copytree(stock, root / "replay"))
            install(game, assembler, audio, live=True)
            install(replay, assembler, audio, live=True, replay=REPLAY)
            assemble_arithmetic_probe(assembler, replay)
            models = (args.model,) if args.model else MODELS
            results = [verify(emulator, stock, game, replay, model, args.seconds, args.replay_seconds, audio)
                       for model in models]
            tap = game / "main.tap"
            digest = hashlib.sha256(tap.read_bytes()).hexdigest()
            if args.output_tap:
                shutil.copyfile(tap, args.output_tap)
    except (OSError, ValueError, IndexError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Gameplay check failed: {error}\n")
    print(json.dumps({"emulator": version, "tap_sha256": digest, "results": results, "passed": True}, indent=2))


if __name__ == "__main__":
    main()
