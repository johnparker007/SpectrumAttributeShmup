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
from verify_zesarux_raster import HEIGHT, WIDTH, capture_video, paper_row, run


RIGHT, LEFT, UP, DOWN, FIRE = (1, 2, 4, 8, 16)
REPLAY = ([0] * 6 + [FIRE] * 37 + [LEFT | UP | FIRE] * 32 + [RIGHT | DOWN | FIRE] * 64
          + [LEFT | UP] * 18 + [LEFT | RIGHT | UP | DOWN] * 9 + [0] * 60)
IDLE = [0] * 120


def box_visible(point):
    return point[0] < 64


def packed(values):
    return int.from_bytes(bytes(values), "little")


def expected(inputs):
    player, enemy = (8, 21), (52, 21)
    health, kills, invulnerable, reload, respawn, cursor = 3, 0, 0, 0, 0, 0
    player_hit = enemy_hit = False
    incoming = [(DEAD, 0, 0)] * 32
    volleys = [(DEAD, 0, 0)] * 3
    results = []
    for tick, command in enumerate(inputs):
        if invulnerable:
            invulnerable -= 1
        elif player_hit and health:
            health -= 1
            invulnerable = 24
        if enemy_hit:
            kills += 1
            enemy = (96, enemy[1])
            respawn = 32
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
        ex, ey = enemy
        if box_visible(enemy):
            if tick % 4 == 0:
                enemy = (ex - 1, ey) if ex > 2 else (96, ey)
                if ex == 2:
                    respawn = 24
        else:
            respawn -= 1
            if respawn == 0:
                enemy = (52, ey ^ 8)
        incoming, volleys, shots = step(incoming, volleys)
        if box_visible(enemy) and incoming[cursor][0] == DEAD:
            incoming[cursor] = (enemy[0] - 1, enemy[1] + 2, 0)
            cursor = (cursor + 1) % len(incoming)
        player_hit = health > 0 and bool(hit(player, [(x, y) for x, y, _ in incoming], 1))
        enemy_hit = box_visible(enemy) and bool(hit(enemy, shots, 2))
        results.append({
            "header": packed(((tick + 1) % 256, command, health, kills)),
            "player": packed(player), "enemy": packed(enemy),
            "flags": packed((255 * enemy_hit, 255 * player_hit)),
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
        ("enemy", peek("enemyXY", 2)),
        ("flags", peek("collision_actual") + "+" + peek("player_hit") + "*256"),
    ]
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
        sample = [state[key] for key in ("header", "player", "enemy", "flags")]
        sample += state["volleys"]
        sample += [state["incoming"][slot] for slot in (0, 15, 31)]
        sample += [state["shots"][slot] for slot in (0, 1, 2, 8)]
        for (condition, value), (expected_condition, _), wanted, (field, _) in zip(row, points, sample, fields):
            if (condition, int(value)) != (expected_condition, wanted):
                raise ValueError(f"{model}: gameplay tick {tick + 1}, {field} yielded {value}, expected {wanted}")
    return {
        "ticks": len(oracle), "kills": max(state["header"] >> 24 for state in oracle),
        "minimum_health": min(state["header"] >> 16 & 255 for state in oracle),
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
        ex, ey = state["enemy"] % 256, state["enemy"] // 256
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
    spool.write_bytes(b"poq a" * 22)
    symbols = read_symbols(game / "main.sym")
    point = f"PC={symbols['controlsReady']:04X}H"
    log = breakpoint_log(emulator, game / "main.tap", model, 14, [(point, "A")],
                         fast_autoload=True, keyboard_spool=spool)
    hits = HIT.findall(log)
    seen = {int(mask) for condition, mask in hits if condition == point}
    if (len(hits) != log.count("Catch breakpoint:")
            or not {RIGHT, LEFT, UP, DOWN, FIRE} <= seen):
        raise ValueError(f"{model}: keyboard matrix test observed {sorted(seen)}")
    return sorted(seen)


def verify(emulator, stock, game, replay, model, seconds, audio):
    # Bound concurrent headless runs on the user's machine.
    with ThreadPoolExecutor(max_workers=3) as pool:
        reference = pool.submit(capture, emulator, stock, model, seconds, paging=True)
        raster = pool.submit(capture, emulator, replay, model, seconds, paging=True, scenery=True)
        live_raster = pool.submit(capture, emulator, game, model, seconds, paging=True, scenery=True)
        played = pool.submit(verify_logic, emulator, replay, model, REPLAY, 48)
        idle = pool.submit(verify_logic, emulator, game, model, IDLE, 32)
        art = pool.submit(verify_gameplay_video, emulator, replay, model)
        keyboard = pool.submit(verify_keyboard, emulator, game, model)
        dense_pool = pool.submit(verify_dense_pool, emulator, replay, model)
        music = pool.submit(verify_audio, emulator, game, model, audio, True)
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
        report["replay"].update(played.result())
        report["replay"]["simultaneous_shots_verified"] = dense_pool.result()
        report["keyboard_idle"].update(idle.result())
        return {"model": model, **report, "gameplay_video_scenes": art.result(),
                "keyboard_masks": keyboard.result(), **music.result()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "assembler", "emulator", "phrase-reference", "output-tap"):
        parser.add_argument(f"--{arg}", required=arg != "output-tap", type=Path)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--seconds", type=int, default=115, help="raster capture time per build")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
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
            models = (args.model,) if args.model else MODELS
            results = [verify(emulator, stock, game, replay, model, args.seconds, audio) for model in models]
            tap = game / "main.tap"
            digest = hashlib.sha256(tap.read_bytes()).hexdigest()
            if args.output_tap:
                shutil.copyfile(tap, args.output_tap)
    except (OSError, ValueError, IndexError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Gameplay check failed: {error}\n")
    print(json.dumps({"emulator": version, "tap_sha256": digest, "results": results, "passed": True}, indent=2))


if __name__ == "__main__":
    main()
