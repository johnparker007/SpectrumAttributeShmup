"""Build the playable barrel-scroll TAP and verify gameplay on both Spectrum families."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from math import atan2, tau
from pathlib import Path
import shutil
import subprocess
import tempfile

from benchmark_motion import DEAD
from moving_overlay import hit
from profile_blokius import build, capture
from profile_ringo8 import HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols, trace
from verify_ay_stream import register_pairs
from verify_ay_phrases import unpack
from verify_blokius_integration import (
    SHIP_Y, SHOT_DIRECTIONS, SHOT_PERIOD, SHOT_VECTORS, examine, install, star_force_music,
)
from verify_dot_overlay import verify_audio
from verify_score_hud import (
    assemble_arithmetic_probe, check_arithmetic, check_game_over_video, check_hud_updates, check_hud_video,
)
from verify_zesarux_raster import HEIGHT, WIDTH, capture_video, paper_row, run


RIGHT, LEFT, UP, DOWN, FIRE, RESTART = (1, 2, 4, 8, 16, 32)
REPLAY = ([0] * 6 + [FIRE] * 37 + [LEFT | UP | FIRE] * 32 + [RIGHT | DOWN | FIRE] * 64
          + [LEFT | UP] * 18 + [LEFT | RIGHT | UP | DOWN] * 9 + [0] * 60
          + [RESTART] * 4 + [FIRE] * 43 + [0] * 492 + [RESTART | FIRE] * 4 + [FIRE] * 46)
IDLE = [0] * 370
ENEMY_SHIPS = 12
PLAYER_PAIRS = 5
EXPLOSION_TICKS = 6
HIDDEN = (96, 0)
PLAYER_START = (8, 21)
RESPAWN_TICKS = 12
INVINCIBLE_TICKS = 75


def box_visible(point):
    return -4 <= point[0] < 64


def visible_enemy(xy):
    x = xy % 256
    return x < 64 or x >= 252


def packed(values):
    return int.from_bytes(bytes(values), "little")


def aim(x, y, player):
    dx, dy = player[0] + 2 - x, player[1] + 2 - y
    bearing = round(atan2(-dy, -dx) / tau * SHOT_DIRECTIONS) if dx or dy else SHOT_DIRECTIONS // 2
    return (bearing % SHOT_DIRECTIONS) * SHOT_PERIOD


def move_dots(records):
    moved = []
    for x, y, path in records:
        if x == DEAD:
            moved.append((x, y, path))
            continue
        phase = path & 7
        dx, dy = ((-1 if total < 0 else 1) * ((phase + 1) * abs(total) // 8 - phase * abs(total) // 8)
                  for total in SHOT_VECTORS[path >> 3])
        if not 0 <= x + dx < 64:
            moved.append((DEAD, y, path))
            continue
        next_y = y + dy
        path = path & ~7 | ((phase + 1) & 7)
        moved.append((x + dx, next_y, path) if 0 <= next_y < 48 else (DEAD, y, path))
    return moved


def pair_shots(x, y):
    return ((x, y), (x, y + 4))


def expected(inputs):
    restart_held = False
    message_rows = 0
    results = []
    for index, command in enumerate(inputs):
        emitted = []
        restart = bool(command & RESTART) and not restart_held
        restart_held = bool(command & RESTART)
        if index == 0 or restart:
            player = PLAYER_START
            lives, kills, invulnerable, respawn_wait, reload, cursor = 3, 0, 0, 0, 0, 0
            tick = wave = emitter = spawn_wait = spawn_slot = player_explosion = spread_wait = 0
            remaining = ENEMY_SHIPS
            enemies = [HIDDEN] * ENEMY_SHIPS
            profiles = [0] * ENEMY_SHIPS
            explosions = [0] * ENEMY_SHIPS
            enemy_hits = [False] * ENEMY_SHIPS
            player_hit = False
            incoming = [(DEAD, 0, 0)] * 32
            pairs = [(DEAD, 0)] * PLAYER_PAIRS
        if not restart:
            player_explosion = max(0, player_explosion - 1)
            if respawn_wait:
                respawn_wait -= 1
                if respawn_wait == 0:
                    player = PLAYER_START
                    reload = 0
                    invulnerable = INVINCIBLE_TICKS
            elif invulnerable:
                invulnerable -= 1
            elif player_hit and lives:
                lives -= 1
                respawn_wait = RESPAWN_TICKS if lives else 0
                player_explosion = EXPLOSION_TICKS
            if lives and not respawn_wait and invulnerable != INVINCIBLE_TICKS:
                x, y = player
                dx = bool(command & RIGHT) - bool(command & LEFT)
                dy = bool(command & DOWN) - bool(command & UP)
                player = (max(2, min(59, x + dx)), max(0, min(43, y + dy)))
                if reload:
                    reload -= 1
                elif command & FIRE and player[0] <= 57:
                    free = next((n for n, (x, _) in enumerate(pairs) if x == DEAD), None)
                    if free is not None:
                        pairs[free] = (player[0] + 2, player[1])
                        reload = 3
            expired = set()
            for slot, (x, y) in enumerate(enemies):
                if x == HIDDEN[0]:
                    if explosions[slot] == 1:
                        expired.add(slot)
                    explosions[slot] = max(0, explosions[slot] - 1)
                elif enemy_hits[slot]:
                    kills += bool(lives)
                    explosions[slot] = EXPLOSION_TICKS
                    enemies[slot] = (HIDDEN[0], y)
                elif tick % 2:
                    continue
                elif x == -4:
                    enemies[slot] = (HIDDEN[0], y)
                else:
                    enemies[slot] = (x - 1, SHIP_Y[profiles[slot]][(x - 1) % 64])
            if spawn_wait:
                spawn_wait -= 1
            elif enemies[spawn_slot][0] == HIDDEN[0] and not explosions[spawn_slot] and spawn_slot not in expired:
                spawn_wait = 9
                enemies[spawn_slot] = (67, 21)
                profiles[spawn_slot] = wave
                spawn_slot = (spawn_slot + 1) % ENEMY_SHIPS
                remaining -= 1
                if not remaining:
                    remaining = ENEMY_SHIPS
                    wave = (wave + 1) % len(SHIP_Y)
            pairs = [(x + 3 if x + 3 < 63 else DEAD, y) for x, y in pairs]
            incoming = move_dots(incoming)
            if tick % 8 == 0:
                spread_wait = max(0, spread_wait - 1)
                x, y = enemies[emitter]
                spread = profiles[emitter] % 2
                emitter = (emitter + 1) % ENEMY_SHIPS
                if 0 <= x < 64 and (not spread or not spread_wait):
                    if spread:
                        spread_wait = 2
                    path = aim(x, y + 2, player) if lives and not respawn_wait else 0
                    offsets = (0, -16, 16) if spread else (0,)
                    for offset in offsets:
                        if incoming[cursor][0] != DEAD:
                            break
                        bearing = (path + offset) % 256
                        incoming[cursor] = (x, y + 2, bearing)
                        emitted.append((x, y + 2, bearing, wave, tick))
                        cursor = (cursor + 1) % len(incoming)
            tick = (tick + 1) % 256
        alive = lives > 0 and not respawn_wait
        visible = alive and (not invulnerable or invulnerable % 2)
        displayed = visible or player_explosion > 0
        bullet_hit = alive and bool(hit(player, [(x, y) for x, y, _ in incoming], 1))
        contact_slot = next((n for n, enemy in enumerate(enemies) if alive and box_visible(enemy)
                             and abs(enemy[0] - player[0]) < 5 and abs(enemy[1] - player[1]) < 5), None)
        contact = contact_slot is not None
        player_hit = bullet_hit or contact
        enemy_hits = [False] * ENEMY_SHIPS
        for slot, enemy in enumerate(enemies):
            if box_visible(enemy):
                for n, (x, y) in enumerate(pairs):
                    if x != DEAD and hit(enemy, pair_shots(x, y), 2):
                        pairs[n] = (DEAD, y)
                        enemy_hits[slot] = True
        if contact and not invulnerable:
            enemy_hits[contact_slot] = True
        # The observation point precedes both scanline writes in the Frame 2 slot.
        panel_delta = -1 if lives else 0 if player_explosion else 1
        results.append({
            "header": packed((tick, command, lives, kills)),
            "player": packed(player), "enemies": [packed((x % 256, y)) for x, y in enemies],
            "enemy_motion": [packed((profile * 64, blast)) for profile, blast in zip(profiles, explosions)],
            "enemy_hits": enemy_hits, "player_explosion": player_explosion,
            "wave": wave, "restart": restart, "emitted": emitted,
            "respawn_wait": respawn_wait, "invincible": invulnerable, "visible": bool(visible),
            "message_rows": message_rows,
            "player_box": packed((player[0] if alive else HIDDEN[0], player[1])),
            "sprite_xy": packed((player[0] + 12 if displayed else HIDDEN[0] + 12, player[1] + 12)),
            "flags": [packed(255 * flag for flag in enemy_hits[:2]),
                      packed((255 * enemy_hits[2], 255 * player_hit))],
            "contact": contact,
            "contact_slot": contact_slot,
            "bullet_hit": bullet_hit,
            "pairs": [packed(pair) for pair in pairs],
            "incoming": [packed(dot) for dot in incoming],
            "shots": [packed(shot) for pair in pairs for shot in pair_shots(*pair)],
        })
        message_rows = max(0, min(16, message_rows + 2 * panel_delta))
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
                            enumerate(("gameTick", "lastControls", "playerLives", "enemyKills")))),
        ("player", peek("playerXY", 2)),
        ("wave", peek("waveIndex")),
        ("score", peek("hudScore", 2)),
        ("message_rows", peek("gameOverRows")),
        ("timers", peek("respawnWait", 2)),
        ("player_box", peek("player_box", 2)),
        ("sprite_xy", peek("sprite08", 2, 4)),
        ("player_explosion", peek("playerExplosion")),
        ("player_image", peek("sprite08", 2)),
        ("flags", peek("collision_actual", 2)),
        ("flags", peek("collision_actual", offset=2) + "+" + peek("player_hit") + "*256"),
    ]
    samples = (0, 5, 11)
    for slot in samples:
        fields.extend((("enemies", peek("enemy_boxes", 2, 2 * slot)),
                       ("enemy_motion", peek("enemyMotion", 2, 2 * slot)),
                       ("enemy_image", peek(f"sprite{slot + 9:02d}", 2))))
    fields += [("pairs", peek("player_pairs", 2, 2 * slot)) for slot in range(PLAYER_PAIRS)]
    incoming_samples = (0, 4, 31)   # Opening shots and the end of the pool.
    fields += [("incoming", peek("enemy_records", 3, 3 * slot)) for slot in incoming_samples]
    shot_samples = (0, 1, 8, 9)
    fields += [("shots", peek("player_shots", 2, 2 * slot)) for slot in shot_samples]
    points = [(f"{point} AND {n}={n}", expression) for n, (_, expression) in enumerate(fields, 1)]
    oracle = expected(inputs)
    log = breakpoint_log(emulator, game / "main.tap", model, seconds, points, fast_autoload=True)
    hits = HIT.findall(log)
    if len(hits) != log.count("Catch breakpoint:") or len(hits) // len(points) < len(oracle):
        raise ValueError(f"{model}: captured {len(hits) // len(points)} of {len(oracle)} gameplay ticks")
    for tick, state in enumerate(oracle):
        row = hits[tick * len(points):(tick + 1) * len(points)]
        sample = [state[key] for key in ("header", "player", "wave")]
        sample += [int(str(state["header"] >> 24), 16), state["message_rows"],
                   packed((state["respawn_wait"], state["invincible"])),
                   state["player_box"], state["sprite_xy"], state["player_explosion"]]
        blast = state["player_explosion"]
        sample.append(symbols[f"explosion{4 - (blast + 1) // 2}" if blast else "playerArt"])
        sample += state["flags"]
        for slot in samples:
            motion = state["enemy_motion"][slot]
            blast = motion >> 8
            sample.extend((state["enemies"][slot], motion,
                           symbols[f"explosion{4 - (blast + 1) // 2}" if blast else "enemyArt"]))
        sample += state["pairs"]
        sample += [state["incoming"][slot] for slot in incoming_samples]
        sample += [state["shots"][slot] for slot in shot_samples]
        for (condition, value), (expected_condition, _), wanted, (field, _) in zip(row, points, sample, fields):
            if (condition, int(value)) != (expected_condition, wanted):
                raise ValueError(f"{model}: gameplay tick {tick + 1}, {field} yielded {value}, expected {wanted}")
    return {
        "ticks": len(oracle), "kills": max(state["header"] >> 24 for state in oracle),
        "minimum_lives": min(state["header"] >> 16 & 255 for state in oracle),
        "waves_verified": sorted({state["wave"] + 1 for state in oracle}),
        "restarts_verified": sum(state["restart"] for state in oracle),
        "peak_enemy_dots": max(sum(dot % 256 != DEAD for dot in state["incoming"]) for state in oracle),
        "peak_player_dots": max(sum(dot % 256 != DEAD for dot in state["shots"]) for state in oracle),
        "peak_visible_ships": max(sum(map(visible_enemy, state["enemies"])) for state in oracle),
        "player_explosions": sum(state["player_explosion"] == EXPLOSION_TICKS for state in oracle),
        "mutual_ram_destructions": sum(
            previous["contact"] and not previous["bullet_hit"]
            and state["player_explosion"] == EXPLOSION_TICKS
            and state["enemy_motion"][previous["contact_slot"]] >> 8 == EXPLOSION_TICKS
            for previous, state in zip(oracle, oracle[1:])
        ),
        "protected_contact_ticks": sum(state["contact"] and not state["bullet_hit"] and state["invincible"] > 0
                                       for state in oracle),
    }


def verify_life_cycle(emulator, game, model):
    result = verify_logic(emulator, game, model, IDLE, 120)
    reference = expected(IDLE)

    def lives(state):
        return state["header"] >> 16 & 255

    deaths = [index for index in range(1, len(reference))
              if lives(reference[index - 1]) > lives(reference[index])]
    if len(deaths) != 3 or lives(reference[-1]) != 0:
        raise ValueError(f"{model}: idle replay did not lose all three ships")
    for death in deaths[:-1]:
        spawn = death + RESPAWN_TICKS
        absent = reference[death:spawn]
        protected = reference[spawn:spawn + INVINCIBLE_TICKS]
        if (any(row["visible"] or row["player_box"] % 256 != HIDDEN[0] for row in absent)
                or [row["player_explosion"] for row in absent[:EXPLOSION_TICKS]] != list(range(EXPLOSION_TICKS, 0, -1))
                or protected[0]["player"] != packed(PLAYER_START)
                or [row["invincible"] for row in protected] != list(range(INVINCIBLE_TICKS, 0, -1))
                or [row["visible"] for row in protected] != [index % 2 == 0 for index in range(INVINCIBLE_TICKS)]
                or any(lives(row) != lives(reference[death]) for row in protected)
                or not any(row["flags"][1] >> 8 for row in protected)):
            raise ValueError(f"{model}: idle replay did not exercise absence, blinking and protected overlaps")
    game_over = reference[deaths[-1]:]
    if any(row["visible"] or row["respawn_wait"] or row["invincible"] for row in game_over):
        raise ValueError(f"{model}: player returned after the final life")
    return {**result, "ships_destroyed": len(deaths), "respawns": len(deaths) - 1,
            "protected_game_frames_per_respawn": INVINCIBLE_TICKS}


def verify_respawn_video(emulator, game, model):
    video = game / f"respawn-{model}.raw"
    capture_video(emulator, model, ["--tape", game / "main.tap", "--fastautoload", "--vofilefps", "25"], video, 20)
    # With no input the ship stays at (8, 21). Skip its centre row, which
    # the incoming stream can cover. The trace verifies the exact cadence.
    shape = {0: " #   ", 1: " ### ", 3: " ### ", 4: " #   "}
    ship_colours = ({bytes((0, level, 0)) * 4 for level in (192, 255)},
                    {bytes([level]) * 12 for level in (192, 255)})
    size = WIDTH * HEIGHT * 3
    x, y = PLAYER_START
    edges = []
    with video.open("rb") as recording:
        while frame := recording.read(size):
            if len(frame) != size:
                raise ValueError(f"{model}: truncated respawn video")
            seen = any(all(all(paper_row(frame, (y + row) * 4 + line)[(x + col) * 12:(x + col + 1) * 12] in colour
                               for line in range(4)) == (pixel == "#")
                           for row, pattern in shape.items() for col, pixel in enumerate(pattern))
                       for colour in ship_colours)
            if (not edges and seen) or (edges and seen != edges[-1]):
                edges.append(seen)
                if len(edges) == 5:
                    return True
    raise ValueError(f"{model}: respawn video did not show the ship repeatedly disappearing and returning")


def verify_gameplay_video(emulator, replay, model):
    video = replay / f"gameplay-{model}.raw"
    capture_video(emulator, model, ["--tape", replay / "main.tap", "--fastautoload", "--vofilefps", "25"], video, 23)
    colours = {"magenta": (1, 0, 1), "cyan": (1, 1, 0), "yellow": (0, 1, 1), "white": (1, 1, 1)}
    pixels = {name: tuple(bytes(component * brightness for component in rgb) * 4 for brightness in (192, 255))
              for name, rgb in colours.items()}
    sights = {name: set() for name in ("magenta", "shot_even", "shot_odd", "yellow", "white")}
    reference = expected(REPLAY[:200])
    for state in reference:
        for xy in state["enemies"]:
            x, y = xy % 256, xy // 256
            if x <= 59:
                sights["magenta"].add(((x + 3, y, "magenta"), (x + 1, y + 1, "magenta")))
        for shot in state["shots"]:
            x, y = shot % 256, shot >> 8
            if x != DEAD:
                sights["shot_odd" if x % 2 else "shot_even"].add(((x, y, "cyan"), (x + 1, y, "white")))
        for dot in state["incoming"]:
            x, y = dot % 256, dot >> 8 & 255
            if x != DEAD:
                sights["yellow"].add(((x, y, "yellow"),))
    # At the start of an explosion its sprite holds the previous coordinates.
    for previous, state in zip(reference, reference[1:]):
        for slot, motion in enumerate(state["enemy_motion"]):
            if motion >> 8 == EXPLOSION_TICKS:
                xy = previous["enemies"][slot]
                x, y = xy % 256, xy // 256
                if x <= 59:
                    sights["white"].add(tuple((x + dx, y + dy, "white")
                                              for dx, dy in ((0, 0), (2, 0), (4, 0), (2, 4))))
    observed = set()
    with video.open("rb") as recording:
        while frame := recording.read(WIDTH * HEIGHT * 3):
            if len(frame) != WIDTH * HEIGHT * 3:
                raise ValueError(f"{model}: truncated gameplay video")
            for name in sights.keys() - observed:
                if any(all(all(paper_row(frame, y * 4 + line)[x * 12:(x + 1) * 12] in pixels[colour]
                               for line in range(4)) for x, y, colour in witness) for witness in sights[name]):
                    observed.add(name)
            if observed == sights.keys():
                break
    if observed != sights.keys():
        raise ValueError(f"{model}: video missed {sorted(sights.keys() - observed)}")
    return sorted(observed)


def verify_formation(emulator, game, model):
    # Check every slot during the idle run and again after game over.
    reference = expected(IDLE)
    symbols = read_symbols(game / "main.sym")
    point = f"PC={symbols['overlayEnd']:04X}H"
    tick_address = symbols['gameTick']
    lives_address = symbols['playerLives']
    candidates = []
    for current_lives in (2, 0):
        state = next(row for row in reference if (row["header"] >> 16 & 255) == current_lives
                     and all(map(visible_enemy, row["enemies"])))
        tick = state['header'] & 255
        candidates.append((f"{point} AND PEEK({tick_address:04X}H)={tick} AND PEEK({lives_address:04X}H)={current_lives}", state))
    points = []
    values = {}
    for cond, state in candidates:
        for slot, packed_xy in enumerate(state['enemies']):
            box = symbols['enemy_boxes'] + slot * 2
            sprite = symbols[f'sprite{9 + slot:02d}'] + 4
            y, x = divmod(packed_xy, 256)
            draw_xy = packed(((x + 12) % 256, y + 12))
            index = len(points) + 1
            key = f"{cond} AND {index}={index}"
            points.append((key, f"PEEKW({box:04X}H)+PEEKW({sprite:04X}H)*65536"))
            values[key] = packed_xy + draw_xy * 65536
    log = breakpoint_log(emulator, game / "main.tap", model, 160, points, fast_autoload=True)
    hits = HIT.findall(log)
    observed = {}
    for key, value in hits:
        observed.setdefault(key, int(value))
    if observed != values or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: captured {len(observed)} of {len(values)} twelve-ship formation fields")
    return ENEMY_SHIPS


def verify_left_exit(emulator, game, model):
    symbols = read_symbols(game / "main.sym")
    frame = f"PC={symbols['overlayEnd']:04X}H"
    tick = f"PEEK({symbols['gameTick']:04X}H)"
    point = f"{frame} AND {tick}>=135 AND {tick}<=145"
    viewport = f"PEEKW({symbols['attrPointer']:04X}H)"
    top = 21 * symbols["attrBufferWidth"]
    centre = 23 * symbols["attrBufferWidth"]
    expressions = (f"PEEKW({symbols['enemy_boxes']:04X}H)",
                   f"PEEKW({symbols['sprite09'] + 4:04X}H)",
                   f"PEEK({viewport}+{top})+PEEK({viewport}+{top + 1})*256+PEEK({viewport}+{centre})*65536")
    checks = [(f"{point} AND {n}={n}", expression) for n, expression in enumerate(expressions, 1)]
    log = breakpoint_log(emulator, game / "main.tap", model, 26, checks, fast_autoload=True)
    hits = HIT.findall(log)
    columns = [[int(raw) for marker, raw in hits if marker == condition][:11:2] for condition, _ in checks]
    x_positions = (0, -1, -2, -3, -4, 67)
    if (len(hits) != log.count("Catch breakpoint:")
            or columns[:2] != [[packed((x % 256, 21)) for x in x_positions],
                               [packed((x + 12, 33)) for x in x_positions]]
            or len(columns[2]) != len(x_positions)):
        raise ValueError(f"{model}: incorrect enemy coordinates during left-edge exit")
    for x, attributes in zip(x_positions[:5], columns[2]):
        # The silhouette has a single top-row dot at X+3, then its centre
        # row shows the final dot once the top has passed the left edge.
        dot = x + 3
        shift = (dot // 2) * 8 + (dot % 2) * 3 if dot >= 0 else 16
        if (attributes >> shift) & 7 != 3:
            raise ValueError(f"{model}: missing visible portion of the enemy at X={x}")
    return len(x_positions) - 1


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
    animation_start = len(expressions)
    for tile in (3, 12, 13, 28, 29):
        expressions.append(f"PEEKW({symbols['tilesLUT'] + 2 * tile:04X}H)")
    points = [(f"{point} AND {n}={n}", expression) for n, expression in enumerate(expressions, 1)]
    log = breakpoint_log(emulator, replay / "main.tap", model, 120, points, fast_autoload=True)
    hits = HIT.findall(log)
    windows = [n for n, row in enumerate(expected(REPLAY)) if row["restart"]]
    span = 36
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
    scroll_period = (width - symbols["SCREEN_TILE_WIDTH"]) * symbols["TILE_SIZE"]
    if [row[0] % 256 for row in groups[:span]] != [(tick // 2 + 1) % scroll_period for tick in range(span)]:
        raise ValueError(f"{model}: scenery did not advance every other game tick")
    for column in range(animation_start, len(expressions)):
        sequence = [row[column] for row in groups[:span]]
        frames = sequence[::4]
        if any(frame != frames[tick // 4] for tick, frame in enumerate(sequence)) or any(
                first == second for first, second in zip(frames, frames[1:])):
            raise ValueError(f"{model}: animated tile did not hold each frame for four game ticks")
    parallax_frames = [row[animation_start] for row in groups[:span:4]]
    if len(set(parallax_frames[:8])) != 8 or parallax_frames[8] != parallax_frames[0]:
        raise ValueError(f"{model}: preshifted parallax tile did not cycle through eight frames")
    return {"restarts": len(windows), "matching_scrolled_ticks_per_restart": span,
            "parallax_frames": 8, "game_ticks_per_animation_frame": 4}


def verify_wave_fire(emulator, replay, model):
    symbols = read_symbols(replay / "main.sym")
    wave, tick = symbols["waveIndex"], symbols["gameTick"]
    point = f"PC={symbols['enemyShotEmitted']:04X}H"
    # B/C are the emitted X/Y, D is the trajectory index before its first step.
    expression = f"B+C*64+D*4096+PEEK({tick:04X}H)*1048576+PEEK({wave:04X}H)*268435456"
    emissions = [row["emitted"] for row in expected(REPLAY)]
    shots = [shot for volley in emissions for shot in volley]
    spreads = sum(len(volley) == 3 for volley in emissions)
    if not spreads or not any(len(volley) == 1 for volley in emissions):
        raise ValueError("Replay must exercise single shots and three-way spreads")
    wanted = [(point, str(x + 64 * y + 4096 * path + 1048576 * t + 268435456 * w)) for x, y, path, w, t in shots]
    log = breakpoint_log(emulator, replay / "main.tap", model, 65, [(point, expression)], fast_autoload=True)
    hits = HIT.findall(log)
    if hits[:len(wanted)] != wanted or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: wave fire trace differs from the reference, captured {len(hits)} emissions")
    return {"emissions_verified": len(wanted), "spreads_verified": spreads,
            "bearing_codes_seen": sorted({path for _, _, path, _, _ in shots})}


def verify(emulator, stock, game, replay, model, seconds, replay_seconds, audio, whole_song_audio=False):
    # Bound concurrent headless runs on the user's machine.
    with ThreadPoolExecutor(max_workers=3) as pool:
        reference = pool.submit(capture, emulator, stock, model, seconds, paging=True)
        raster = pool.submit(capture, emulator, replay, model, replay_seconds, paging=True, scenery=True)
        live_raster = pool.submit(capture, emulator, game, model, seconds, paging=True, scenery=True)
        played = pool.submit(verify_logic, emulator, replay, model, REPLAY, 200)
        idle = pool.submit(verify_life_cycle, emulator, game, model)
        art = pool.submit(verify_gameplay_video, emulator, replay, model)
        keyboard = pool.submit(verify_keyboard, emulator, game, model)
        formation = pool.submit(verify_formation, emulator, game, model)
        left_exit = pool.submit(verify_left_exit, emulator, game, model)
        music = pool.submit(verify_audio, emulator, replay, model, audio, True, whole_song=whole_song_audio)
        scenery = pool.submit(verify_rewind, emulator, replay, model)
        wave_fire = pool.submit(verify_wave_fire, emulator, replay, model)
        targets = [(state["header"] >> 24, state["header"] >> 16 & 255) for state in expected(REPLAY)]
        hud_updates = pool.submit(check_hud_updates, emulator, replay, model, targets)
        hud_video = pool.submit(check_hud_video, emulator, replay, model, targets[:200])
        final_run = [state for state in expected(REPLAY) if state["header"] >> 16 & 255 == 0]
        final_score = final_run[0]["header"] >> 24
        if not final_score or any(state["header"] >> 24 != final_score for state in final_run):
            raise ValueError("Replay needs a nonzero final score which stays fixed after game over")
        game_over = pool.submit(check_game_over_video, emulator, replay, model, final_score)
        blink = pool.submit(verify_respawn_video, emulator, game, model)
        _, baseline = examine(reference.result(), model)
        report = {}
        for label, frames in (("replay", raster.result()), ("keyboard_idle", live_raster.result())):
            margins, cases = examine(frames, model)
            for phase, signatures in cases.items():
                match = set(baseline[phase])
                if any(signature not in match for signature in signatures):
                    raise ValueError(f"{model}: {label} Frame {phase} differs from the stock paging trace")
            report[label] = {"pairs": min(map(len, cases.values())),
                             "minimum_headroom": [min(margins[phase]) for phase in (1, 2)]}
        if report["replay"]["pairs"] < len(REPLAY):
            raise ValueError(f"{model}: replay paging trace ended before tick {len(REPLAY)}. Increase --replay-seconds.")
        report["replay"].update(played.result())
        if report["replay"]["peak_player_dots"] != PLAYER_PAIRS * 2:
            raise ValueError(f"{model}: replay did not exercise all five player pairs")
        if not report["replay"]["mutual_ram_destructions"] or not report["replay"]["protected_contact_ticks"]:
            raise ValueError(f"{model}: replay did not exercise mutual destruction and protected ship contact")
        report["keyboard_idle"]["simultaneous_enemy_ships_verified"] = formation.result()
        report["keyboard_idle"]["left_exit_positions_verified"] = left_exit.result()
        report["keyboard_idle"].update(idle.result())
        check_arithmetic(emulator, replay, model)
        aiming = trace(emulator, replay / "aim.sna", replay / "aim.sym", ["passed", "failed"], model, 1)
        if [event["labels"] for event in aiming["events"]] != [["passed"]]:
            raise ValueError(f"{model}: the bearing probe failed")
        paired = trace(emulator, replay / "player_pairs.sna", replay / "player_pairs.sym", ["passed", "failed"], model, 1)
        if [event["labels"] for event in paired["events"]] != [["passed"]]:
            raise ValueError(f"{model}: the paired-shot collision probe failed")
        hud = {**hud_updates.result(), **hud_video.result()}
        return {"model": model, **report, "gameplay_video_scenes": art.result(),
                "keyboard_masks": keyboard.result(), "scenery_rewind": scenery.result(),
                "wave_fire": wave_fire.result(), "score_hud": hud, "game_over": game_over.result(),
                "aim_directions_verified": SHOT_DIRECTIONS, "respawn_blink_seen": blink.result(), **music.result()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "assembler", "emulator", "output-tap"):
        parser.add_argument(f"--{arg}", required=arg != "output-tap", type=Path)
    parser.add_argument("--phrase-reference", type=Path, help="use an alternate full-song capture instead of Star Force")
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--seconds", type=int, default=155, help="raster capture time per build")
    parser.add_argument("--replay-seconds", type=int, default=290, help="raster capture time for the longer replay")
    args = parser.parse_args()
    if min(args.seconds, args.replay_seconds) < 1:
        parser.error("Capture times must be positive")
    try:
        emulator, assembler = (path.resolve(strict=True) for path in (args.emulator, args.assembler))
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        if args.phrase_reference:
            reference = json.loads(args.phrase_reference.read_text(encoding="utf-8-sig"))
            if not reference["passed"] or not reference.get("through_loop") or reference["emulator"] != version:
                raise ValueError("Expected the verified full-song AY reference")
            tune = reference["results"][0]
            audio = [register_pairs(tune["initial_writes"]), *(register_pairs(tick["writes"]) for tick in tune["ticks"])]
            build_audio = audio
        else:
            recipe, *banks = star_force_music()
            audio = [list(zip(packet[:-1:2], packet[1:-1:2], strict=True)) for packet in unpack(recipe, banks)]
            build_audio = None
        with tempfile.TemporaryDirectory(prefix="blokius-gameplay-") as scratch:
            root = Path(scratch)
            (root / "stock").mkdir()
            stock = build(args.archive, assembler, root / "stock")
            game = Path(shutil.copytree(stock, root / "game"))
            replay = Path(shutil.copytree(stock, root / "replay"))
            install(game, assembler, build_audio, live=True)
            install(replay, assembler, build_audio, live=True, replay=REPLAY)
            assemble_arithmetic_probe(assembler, replay)
            aim_probe = Path(__file__).resolve().parents[1] / "tests" / "enemies" / "aim.asm"
            run([assembler, "--sym=aim.sym", aim_probe], replay)
            pair_probe = Path(__file__).resolve().parents[1] / "tests" / "collision" / "player_pairs.asm"
            run([assembler, "--sym=player_pairs.sym", pair_probe], replay)
            models = (args.model,) if args.model else MODELS
            results = [verify(emulator, stock, game, replay, model, args.seconds, args.replay_seconds, audio,
                              whole_song_audio=build_audio is None)
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
