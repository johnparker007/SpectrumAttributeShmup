"""Build and check the Blokius barrel-scroll scenery with the projectile workload."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import groupby
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from moving_overlay import ENEMY_BOXES, PLAYER_BOX, phases, prepare, verify_state
from benchmark_motion import STEPS
from profile_blokius import build, capture
from profile_ringo8 import FRAME, HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_ay_stream import register_pairs
from verify_dot_overlay import TESTS, install_audio, verify_audio, verify_overlay_video
from verify_zesarux_raster import run


GAME_OVER_TEXT = ("GAME OVER".center(16), "ENTER TO RESTART")


def ship_art(rows, colour):
    data = bytearray()
    for shift in (0, 1):
        for row in rows:
            pixels = (" " * shift + row).ljust(6)
            for offset in range(0, 6, 2):
                mask, ink = 255, 0
                for lane, pixel in enumerate(pixels[offset:offset + 2]):
                    if pixel != " ":
                        mask &= ~(7 << (3 * lane))
                        ink |= colour << (3 * lane)
                data.extend((mask, ink))
    return data


def install(game, assembler, audio, live=False, replay=None):
    source = game / "main.asm"
    prefix, separator, rest = source.read_bytes().partition(b'\tinclude "hud.asm"')
    _, tail_start, tail = rest.partition(b"\tassert $<48830")
    if not separator or not tail_start:
        raise ValueError("Unexpected Blokius scenery include or vector assertion")
    source.write_bytes(prefix + b'''
    include "Z80-Optimized-Routines-master/math/multiplication/DE_Times_A.z80"

startGame:
    call barrelScroll_Init
    ifdef LIVE_SHMUP
        call gameInit
    endif
    call enableRender
mainLoop:
halt1 equ $+7
    SET_RENDER_FRAME renderFrame2
    call soundScroll
    call motionStep
    ifdef LIVE_SHMUP
        call hudStep
hudFrame1Done:
        call gameOverStep
    endif
halt2 equ $+7
    SET_RENDER_FRAME renderFrame1
    jp overlayEntry

doSinScroll equ barrelScroll_Update
    include "overlay.a80"
''' + tail_start + tail.replace(b'\tinclude "music/resources.a80"', b''))
    defines_source = game / "defines.asm"
    defines_source.write_bytes(defines_source.read_bytes().replace(b"define DRAW_SCORE", b"; define DRAW_SCORE"))
    for folder, name in (("raster", "overlay"), ("raster", "moving_overlay"), ("dots", "motion_step"),
                         ("dots", "packed_plot"), ("collision", "fixed_collision")):
        shutil.copyfile(TESTS / folder / f"{name}.a80", game / f"{name}.a80")
    shutil.copyfile(TESTS / "raster" / "scheduled_collision.a80", game / "engine" / "spritesRenderBIG.a80")
    defines = ["OVERLAY_MOTION", "OVERLAY_FAST_PLOT", "SCHEDULE_COLLISION", "OVERLAY_AUDIO", "OVERLAY_PHRASES",
               "BARREL_SCENERY"]
    if live:
        for source_name in ("gameplay.a80", "score_hud.a80", "game_over_hud.a80"):
            shutil.copyfile(TESTS.parent / "game" / source_name, game / source_name)
        font = (game / "font" / "n13.bin").read_bytes()
        digits = "0123456789"
        glyphs = {char: font[8 * (ord(char) - 32):8 * (ord(char) - 31)]
                  for char in set(digits + "".join(GAME_OVER_TEXT))}
        if any(len(glyph) != 8 for glyph in glyphs.values()):
            raise ValueError("The archived score font is incomplete")
        (game / "score_digits.bin").write_bytes(b"".join(glyphs[char] for char in digits))
        (game / "game_over.bin").write_bytes(bytes(glyphs[char][row] for line in GAME_OVER_TEXT
                                                 for row in range(8) for char in line))
        icon = bytes((0, 0x20, 0x38, 0x7C, 0x38, 0x20, 0, 0))
        (game / "hud_life_icon.bin").write_bytes(icon)
        (game / "hud_initial.bin").write_bytes(b"".join(bytes((ship, ship, ship, 0)) + bytes((digit,)) * 6
                                                       for ship, digit in zip(icon, glyphs["0"])))
        (game / "trajectories.bin").write_bytes(bytes(delta % 256 for path in STEPS for delta in path))
        player_shape = (" #   ", " ### ", "#####", " ### ", " #   ")
        (game / "player_art.bin").write_bytes(ship_art(player_shape, 4))
        (game / "enemy_art.bin").write_bytes(ship_art(("   # ", " ### ", "#####", " ### ", "   # "), 3))
        defines.append("LIVE_SHMUP")
        if replay is not None:
            controls = bytearray()
            for command, group in groupby(replay):
                count = sum(1 for _ in group)
                while count:
                    length = min(count, 255)
                    controls.extend((length, command))
                    count -= length
            (game / "controls.bin").write_bytes(controls + b"\x00")
            defines.append("REPLAY_CONTROLS")
    else:
        prepare(game)
        (game / "enemy_boxes.bin").write_bytes(bytes(axis for box in ENEMY_BOXES for axis in box))
        (game / "player_box.bin").write_bytes(bytes(PLAYER_BOX))
        (game / "collision_expected.bin").write_bytes(phases()[0].hits)
    install_audio(game, audio, phrases=True)
    run([assembler, *(f"-D{name}=1" for name in defines), "--sym=main.sym", "main.asm"], game)


def examine(frames, model):
    margins = {1: [], 2: []}
    signatures = {1: [], 2: []}
    for index, (frame, following) in enumerate(zip(frames, frames[1:])):
        phase = index % 2 + 1
        halt = frame[f"halt{3 - phase}"]
        if (following["start"] != frame["start"] + 1
                or not frame["irq"] < frame[f"frame{phase}"] < frame["render_return"] < halt < FRAME):
            raise ValueError(f"{model}: irregular frame or game-slot overrun at {index}")
        writes = []
        pending = None
        for condition, value in frame["paging"]:
            pc = int(condition[3:7], 16)
            if "PEEKW" in condition:
                if pending is not None:
                    raise ValueError(f"{model}: missing end of OUT at frame {index}")
                before, byte = divmod(value, 256)
                pending = (pc, byte, before)
            elif pending is not None and pc == pending[0] + 2:
                writes.append((*pending, value))
                pending = None
        if pending is not None or len(writes) != 25 + phase:
            raise ValueError(f"{model}: incomplete paging trace at {index}")
        margins[phase].append(FRAME - halt)
        signatures[phase].append(tuple(writes))
    if min(map(len, margins.values())) < 256:
        raise ValueError(f"{model}: fewer than 256 complete frame pairs. Increase --seconds.")
    return margins, signatures


def trace_scroll(emulator, game, model, seconds, scenery):
    symbols = read_symbols(game / "main.sym")
    halt2 = symbols["halt2"] if scenery else symbols["mainLoop"] + 0x2C
    index, scroll, complete = (symbols[name] for name in
                               ("sourceTileMapReadIndex", "tileMapScroll_H", "barrelScrollComplete"))
    tile_map, width = symbols["tileMap"], symbols["tileMapWidth"]
    points = [(f"PC={halt2:04X}H", f"PEEKW({index:04X}H)*65536+PEEK({scroll:04X}H)*256+PEEK({complete:04X}H)"),
              (f"PC={halt2:04X}H AND 1=1", f"PEEKW({symbols['tilesLUT'] + 6:04X}H)")]
    for group in range(2):
        # Sample one cell in each row, alternating the two copies of the barrel.
        cells = [tile_map + width * row + (width // 2 if row % 2 else 0) for row in range(3 * group, 3 * group + 3)]
        expression = "+".join(f"PEEK({cell:04X}H)*{256**n}" for n, cell in enumerate(cells))
        points.append((f"PC={halt2:04X}H AND {group + 2}={group + 2}", expression))
    log = breakpoint_log(emulator, game / "main.tap", model, seconds, points, fast_autoload=True)
    hits = HIT.findall(log)
    if len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: incomplete barrel scroll trace")
    width = len(points)
    groups = []
    for start in range(0, len(hits) - width + 1, width):
        group = hits[start:start + width]
        if [condition for condition, _ in group] != [condition for condition, _ in points]:
            raise ValueError(f"{model}: barrel scroll samples are out of order")
        values = tuple(int(value) for _, value in group)
        groups.append(values)
        if values[0] % 256:
            return groups
    build_name = "scenery" if scenery else "archive"
    raise ValueError(f"{model}: {build_name} captured {len(groups)} scroll ticks without completing the map. "
                     "Increase --scroll-seconds.")


def verify(emulator, stock, game, model, seconds, scroll_seconds, audio):
    scenario = phases()
    with ThreadPoolExecutor(max_workers=3) as pool:
        stock_scroll = pool.submit(trace_scroll, emulator, stock, model, scroll_seconds, False)
        moving_scroll = pool.submit(trace_scroll, emulator, game, model, scroll_seconds, True)
        stock_run = pool.submit(capture, emulator, stock, model, seconds, paging=True)
        moving_run = pool.submit(capture, emulator, game, model, seconds, paging=True, scenery=True)
        state = pool.submit(verify_state, emulator, game, model, scenario)
        video = pool.submit(verify_overlay_video, emulator, game, model, scenario)
        ay = pool.submit(verify_audio, emulator, game, model, audio, True)
        _, reference = examine(stock_run.result(), model)
        margins, candidate = examine(moving_run.result(), model)
        for phase in (1, 2):
            stock_signatures = set(reference[phase])
            for index, signature in enumerate(candidate[phase]):
                if signature not in stock_signatures:
                    raise ValueError(f"{model}: Frame {phase} paging differs from stock at pair {index}")
        reference_scroll, candidate_scroll = stock_scroll.result(), moving_scroll.result()
        if reference_scroll != candidate_scroll:
            raise ValueError(f"{model}: barrel scroll state differs from the archived build")
        return {"model": model, "frames_matching_stock_paging": [len(margins[phase]) for phase in (1, 2)],
                "minimum_headroom": [min(margins[phase]) for phase in (1, 2)],
                "scroll_ticks_verified": len(candidate_scroll),
                "projectile_phases": state.result(), "video_frames": video.result(), **ay.result()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "assembler", "emulator", "phrase-reference", "output-tap"):
        parser.add_argument(f"--{arg}", type=Path, required=arg != "output-tap")
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--seconds", type=int, default=100)
    parser.add_argument("--scroll-seconds", type=int, default=205)
    args = parser.parse_args()
    if min(args.seconds, args.scroll_seconds) < 1:
        parser.error("Capture lengths must be positive")
    try:
        assembler = args.assembler.resolve(strict=True)
        emulator = args.emulator.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        source = json.loads(args.phrase_reference.read_text(encoding="utf-8-sig"))
        track = source["results"][0]
        if not source["passed"] or source["emulator"] != version or not source.get("through_loop"):
            raise ValueError("Expected the verified full-song AY reference")
        audio = [register_pairs(track["initial_writes"])]
        audio.extend(register_pairs(tick["writes"]) for tick in track["ticks"])
        with tempfile.TemporaryDirectory(prefix="blokius-overlay-") as scratch:
            root = Path(scratch)
            stock_root = root / "stock"
            stock_root.mkdir()
            stock = build(args.archive, assembler, stock_root)
            game = root / "moving"
            shutil.copytree(stock, game)
            install(game, assembler, audio)
            results = [verify(emulator, stock, game, model, args.seconds, args.scroll_seconds, audio) for model in
                       ((args.model,) if args.model else MODELS)]
            tap = game / "main.tap"
            digest = hashlib.sha256(tap.read_bytes()).hexdigest()
            if args.output_tap:
                shutil.copyfile(tap, args.output_tap)
    except (OSError, ValueError, IndexError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Blokius integration failed: {error}\n")
    print(json.dumps({"emulator": version, "tap_sha256": digest, "input": "none",
                      "results": results, "passed": True}, indent=2))


if __name__ == "__main__":
    main()
