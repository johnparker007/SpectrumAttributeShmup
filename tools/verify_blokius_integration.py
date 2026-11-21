"""Build and check the Blokius barrel-scroll scenery with the projectile workload."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import groupby
import json
from math import cos, sin, tan, tau
from pathlib import Path
import shutil
from struct import unpack_from
import subprocess
import tempfile

from moving_overlay import ENEMY_BOXES, PLAYER_BOX, phases, prepare, verify_state
from build_art import (
    BLAST_TILE, DESTRUCTIBLE_TILE, LEVEL_MAPS, MENU_LOGO, SCENERY_MOUNT,
    SCREEN_FONT, ZX0, build_art, map_output,
)
from bottom_hud import install_bottom_raster
from bonus_chime import bake_bonus, tag_music_bank
from extract_ay_effects import bake_noise_sample
from menu_luminance import build_luminance
from profile_blokius import build, capture
from profile_ringo8 import FRAME, HIT, MODELS
from trace_zesarux import breakpoint_log, read_symbols
from verify_ay_stream import register_pairs
from verify_dot_overlay import TESTS, install_audio, verify_audio, verify_overlay_video
from verify_zesarux_raster import run


GAME_OVER_TEXT = ("GAME OVER".center(16), "ENTER TO RESTART")
MUSIC = TESTS.parent / "game" / "music"
SHIP_PATTERNS = ((21, 0, 64), (13, 5, 64), (29, 7, 32), (22, 11, 64))
SHIP_Y = tuple(tuple(round(centre + amplitude * sin(tau * x / period)) for x in range(64))
               for centre, amplitude, period in SHIP_PATTERNS)
# The five-dot ships travel from Y=0 to Y=41 in the 46-dot playfield.
# Put a crest at X=63 so a shot at entry lines up with a ship at either edge.
GREEN_TRAVEL_Y = 46 - 5
GREEN_TOP_Y = tuple(round(GREEN_TRAVEL_Y * (1 - cos(tau * (x - 63) / 64)) / 2) for x in range(64))
GREEN_SHIP_Y = (GREEN_TOP_Y, tuple(GREEN_TRAVEL_Y - y for y in GREEN_TOP_Y))
# Every green member takes the former level 4 shot at the first visible column.
GREEN_FIRE_COLUMNS = (63,) * 9
GREEN_FAST_FROM = 6
YELLOW_FIRE_COUNTS = (1, 1, 1, 1, 1, 2, 2, 2, 2)
# Last spawn to first spawn, minus the tick that actually spawns the ship.
# The first value applies before a yellow wave, the second before other types.
WAVE_GAPS = ((2, 2), (19, 15), (17, 13), (15, 11), (13, 10), (11, 9), (9, 8), (7, 6), (5, 5))
CATALOG_VOLLEY_TICKS = (64, 64, 64, 56, 52, 48, 46, 43, 40)
# Fraction of wave firing opportunities withheld, in 256ths. The boss has its own guns.
WAVE_SHOT_SKIP = (85, 72, 60, 48, 36, 24, 16, 8, 0)
YELLOW_RETREAT_TICKS = 12
YELLOW_MAX_Y = 43
SHOT_DIRECTIONS = 32
SHOT_PERIOD = 8
SHOT_VECTORS = tuple((-round(12 * cos(tau * bearing / SHOT_DIRECTIONS)),
                      -round(12 * sin(tau * bearing / SHOT_DIRECTIONS)))
                     for bearing in range(SHOT_DIRECTIONS))


def shot_steps(axis, slow=False):
    # The table is indexed by the arrival phase, with phase 0 wrapping.
    for vector in SHOT_VECTORS:
        total = round(vector[axis] * 2 / 3) if slow else vector[axis]
        sign = -1 if total < 0 else 1
        positions = [abs(total) * step // SHOT_PERIOD for step in range(SHOT_PERIOD + 1)]
        steps = [(sign * (end - start)) % 256 for start, end in zip(positions, positions[1:])]
        yield steps[-1]
        yield from steps[:-1]


def star_force_music():
    return (MUSIC.joinpath("star-force-recipe.bin").read_bytes(),
            MUSIC.joinpath("star-force-literal.bin").read_bytes(), b"")


def add_boss_music(game, wave_literals):
    data = (MUSIC / "aircraft-carrier.ayp").read_bytes()
    size, loop = unpack_from("<HH", data)
    if size % 3 or loop % 3 or not 0 <= loop < size < len(data) - 4:
        raise ValueError("Invalid boss music recipe or loop offset")
    literals = data[4 + size:]
    if len(wave_literals) + len(literals) > 16384:
        raise ValueError("Gameplay and boss music exceed the first AY literal bank")
    lines = ["bossMusicRecipe:"]
    for i in range(0, size, 3):
        if i == loop:
            lines.append("bossMusicLoop:")
        offset, count = unpack_from("<HB", data, 4 + i)
        if offset >= len(literals) or count == 0:
            raise ValueError("Invalid boss music phrase")
        lines.extend((f"    dw {len(wave_literals) + offset}", f"    db {count}"))
    lines.append("bossMusicEnd:")
    (game / "boss_recipe.a80").write_text("\n".join(lines) + "\n", encoding="ascii")
    return wave_literals + literals


def install(game, assembler, audio=None, live=False, replay=None, menu=True, *, sprite_dir=None,
            prototype_waves=False, solid_menu_logo=False, luminance_logo=False):
    if luminance_logo and (audio is not None or solid_menu_logo):
        raise ValueError("The luminance raster needs the gameplay soundtrack and the logo bitmap")
    source = game / "main.asm"
    prefix, separator, rest = source.read_bytes().partition(b'\tinclude "hud.asm"')
    _, tail_start, tail = rest.partition(b"\tassert $<48830")
    if not separator or not tail_start:
        raise ValueError("Unexpected Blokius scenery include or vector assertion")
    if live:
        if not prototype_waves:
            prefix = prefix.replace(b"call initTiles", b"call fillPixels", 1)
        prefix = prefix.replace(b'incbin "maps/tilemap.bin"', b"""defs SOURCE_TILEMAP_WIDTH*SOURCE_TILEMAP_HEIGHT,0
    include "level_loader.a80"
    ifdef LEVEL_MENU
        include "level_menu.a80"
    endif
    include "screen_text.a80"
    ifdef BOTTOM_HUD
        include "bottom_hud.a80"
    endif""")
        # Finish the menu in the bootstrap so the raster loop keeps its
        # original entry point and layout on both hardware families.
        prefix = prefix.replace(b"jp startGame", b"""ifdef LEVEL_MENU
        call showLevelMenu
    else
        xor a
        call loadLevel
    endif
    jp startGame""")
    source.write_bytes(prefix + b'''
    include "Z80-Optimized-Routines-master/math/multiplication/DE_Times_A.z80"

startGame:
    call barrelScroll_Init
levelPrepared:
    ifdef LIVE_SHMUP
        ifdef BOTTOM_HUD
            di                 ; keep the shadow bank mapped through HUD setup
            call gameInit
        else
            call gameInit
            di
        endif
startLevelRenderer:
        call enableRender
        ei
        halt
        ld hl,renderFrame2
        ld (intProc+1),hl
        jr firstFrameLogic
    else
        call enableRender
    endif
mainLoop:
halt1 equ $+7
    SET_RENDER_FRAME renderFrame2
firstFrameLogic:
    call soundScroll
    call motionStep
    ifdef LIVE_SHMUP
        ifdef BOTTOM_HUD
        nop : nop : nop        ; retain the raster entry addresses
        else
        call hudStep
        endif
hudFrame1Done:
    endif
halt2 equ $+7
    SET_RENDER_FRAME renderFrame1
    jp overlayEntry

    ifdef LIVE_SHMUP
doSinScroll equ scrollScenery
    else
doSinScroll equ barrelScroll_Update
    endif
    include "overlay.a80"
    ifdef BOTTOM_HUD
        include "bottom_hud_timing.a80"
    endif
''' + tail_start + tail.replace(b'\tinclude "music/resources.a80"', b''))
    defines_source = game / "defines.asm"
    defines_source.write_bytes(defines_source.read_bytes().replace(b"define DRAW_SCORE", b"; define DRAW_SCORE"))
    for folder, name in (("raster", "overlay"), ("raster", "moving_overlay"), ("dots", "motion_step"),
                         ("dots", "packed_plot"), ("collision", "fixed_collision")):
        shutil.copyfile(TESTS / folder / f"{name}.a80", game / f"{name}.a80")
    shutil.copyfile(TESTS / "raster" / "scheduled_collision.a80", game / "engine" / "spritesRenderBIG.a80")
    defines = ["OVERLAY_MOTION", "OVERLAY_FAST_PLOT", "SCHEDULE_COLLISION", "OVERLAY_AUDIO", "OVERLAY_PHRASES",
               "BARREL_SCENERY"]
    game_over_resource = b""
    if live:
        # Read the freshly updated positions directly in the small-sprite
        # renderer. Both IX offsets have the same instruction timing.
        macros = game / "engine" / "macros.a80"
        code = macros.read_bytes()
        before, marker, small = code.partition(b"MACRO CALC_DISPLACEMENT_SMALL")
        if not marker or small.count(b"SPRITE.DRAWX") != 1 or small.count(b"SPRITE.DRAWY") != 1:
            raise ValueError("Unexpected small-sprite position loader")
        macros.write_bytes(before + marker + small.replace(b"SPRITE.DRAWX", b"SPRITE.X").replace(b"SPRITE.DRAWY", b"SPRITE.Y"))
        for source_name in ("gameplay.a80", "score_hud.a80", "game_over_hud.a80", "enemy_runtime.a80",
                            "aim_incoming.a80", "level_loader.a80", "level_menu.a80", "screen_text.a80",
                            "yellow_z.a80"):
            shutil.copyfile(TESTS.parent / "game" / source_name, game / source_name)
        shutil.copyfile(ZX0 / "dzx0_standard.asm", game / "dzx0_standard.asm")
        build_art(game, sprite_dir=sprite_dir)
        if solid_menu_logo:
            bitmap = game / MENU_LOGO
            bitmap.write_bytes(b"\xff" * bitmap.stat().st_size)
        font = (game / SCREEN_FONT).read_bytes()
        digits = "0123456789"
        game_over_text = GAME_OVER_TEXT + (("M TO MAIN MENU".center(16),) if menu else ())
        glyphs = {char: font[8 * (ord(char) - 32):8 * (ord(char) - 31)]
                  for char in set(digits + "".join(game_over_text))}
        if any(len(glyph) != 8 for glyph in glyphs.values()):
            raise ValueError("The screen font is incomplete")
        (game / "score_digits.bin").write_bytes(b"".join(glyphs[char] for char in digits))
        (game / "game_over.bin").write_bytes(bytes(glyphs[char][row] for line in game_over_text
                                                 for row in range(8) for char in line))
        icon = (game / "hud_life_icon.bin").read_bytes()
        (game / "hud_initial.bin").write_bytes(b"".join(bytes((ship, ship, ship, 0)) + bytes((digit,)) * 6
                                                       for ship, digit in zip(icon, glyphs["0"])))
        # The life queue uses a blank cell, one centred ship, and the three
        # cells of a tightly spaced four-ship group for overflow.
        packed_rows = []
        for ship in icon:
            shape = ship >> 2
            strip = (shape << 19) | (shape << 13) | (shape << 7) | (shape << 1)
            packed_rows.append(strip.to_bytes(3, "big"))
        packed_cells = b"".join(bytes(column) for column in zip(*packed_rows))
        (game / "hud_life_cells.bin").write_bytes(bytes(8) + icon + packed_cells)
        (game / "hud_initial_bottom.bin").write_bytes(
            b"".join(bytes((ship, ship, 0, zero)) for ship, zero in zip(icon, glyphs["0"])))
        (game / "incoming_x.bin").write_bytes(bytes(shot_steps(0)))
        (game / "incoming_y.bin").write_bytes(bytes(shot_steps(1)))
        # Minimum minor-axis distance to cross each of the four angular
        # midpoints within the first octant, for every major-axis distance.
        (game / "aim_thresholds.bin").write_bytes(bytes(
            int(major * tan(tau * (bearing + 0.5) / SHOT_DIRECTIONS)) + 1
            for major in range(64) for bearing in range(4)))
        paths = SHIP_Y if prototype_waves else GREEN_SHIP_Y
        (game / "ship_trajectories.bin").write_bytes(bytes(y for path in paths for y in path))
        defines.append("LIVE_SHMUP")
        if not prototype_waves:
            defines.extend(("LEVEL_WAVES", "BOTTOM_HUD"))
            for filename in ("bottom_hud.a80", "bottom_hud_updates.a80", "bottom_hud_timing.a80",
                             "sky_stars.a80", "scenery_stream.a80", "enemy_catalog.a80", "level_tiles.a80",
                             "boss.a80", "boss_transition.a80", "boss_music.a80"):
                shutil.copyfile(TESTS.parent / "game" / filename, game / filename)
            shutil.copyfile(TESTS.parent / "game" / "destructible.a80", game / "destructible.a80")
            install_bottom_raster(game)
            # The live compositor reads X/Y directly. Reuse its obsolete DRAWX/Y
            # copy pass after the last beam-timed write, at the same address.
            renderer = game / "engine" / "spritesRender.a80"
            code = renderer.read_bytes()
            begin = code.index(b"N=0", code.index(b";patch small sprites here"))
            end = code.index(b"    edup", begin) + len(b"    edup")
            renderer.write_bytes(code[:begin] + b'    include "flight_animation.a80"' + code[end:])
            shutil.copyfile(TESTS.parent / "game/flight_animation.a80", game / "flight_animation.a80")
            (game / "yellow_retreat.bin").write_bytes(bytes(
                ((step * delta // YELLOW_RETREAT_TICKS)
                 - ((step - 1) * delta // YELLOW_RETREAT_TICKS)) & 255
                for delta in range(-YELLOW_MAX_Y, YELLOW_MAX_Y + 1)
                for step in range(1, YELLOW_RETREAT_TICKS + 1)))
            (game / "level_fire.bin").write_bytes(bytes(
                value for level, column in enumerate(GREEN_FIRE_COLUMNS, 1)
                for value in (column, int(level >= GREEN_FAST_FROM), YELLOW_FIRE_COUNTS[level - 1],
                              *WAVE_GAPS[level - 1], CATALOG_VOLLEY_TICKS[level - 1], WAVE_SHOT_SKIP[level - 1])))
            for axis, name in enumerate(("x", "y")):
                (game / f"incoming_slow_{name}.bin").write_bytes(bytes(shot_steps(axis, slow=True)))
        if menu:
            defines.append("LEVEL_MENU")
            if not prototype_waves:
                shutil.copyfile(MUSIC.parent / "game_over_music.a80", game / "game_over_music.a80")
                track = MUSIC / "name-regist.pt3"
                run([ZX0 / "zx0.exe", "-f", track, game / "music/name-regist.zx0"], game)
                game_over_resource = ('gameOverTrack: incbin "music/name-regist.zx0"\n'
                                      f'    assert {track.stat().st_size} <= renderTilesList-attrBuffer\n').encode("ascii")
            for name in ("joystick.a80", "redefine_keys.a80", "menu_logo.a80", "menu_logo_setup.a80"):
                shutil.copyfile(TESTS.parent / "game" / name, game / name)
            if luminance_logo:
                defines.append("LUMINANCE_LOGO")
                build_luminance(game / "gfx", (game / MENU_LOGO).read_bytes())
                shutil.copyfile(TESTS.parent / "game" / "menu_logo_luminance.a80", game / "menu_logo_luminance.a80")
                shutil.copyfile(TESTS.parent / "game" / "menu_stars.a80", game / "menu_stars.a80")
        if audio is None:
            defines.append("LIVE_SFX")
            shutil.copyfile(TESTS.parent / "game" / "sound_effects.a80", game / "sound_effects.a80")
            for effect in ("shot-sound.bin", "explosion-noise.bin"):
                shutil.copyfile(MUSIC / effect, game / "gfx" / effect)
            if not prototype_waves:
                (game / "gfx/extra-ship.bin").write_bytes(bake_bonus(MUSIC / "extra-ship.vt2"))
                (game / "gfx/armour-hit.bin").write_bytes(bake_noise_sample(MUSIC / "armour-hit.vt2"))
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
    packed_audio = star_force_music() if audio is None else None
    if live and not prototype_waves and packed_audio is not None:
        recipe, first, second = packed_audio
        packed_audio = (recipe, tag_music_bank(add_boss_music(game, first)), tag_music_bank(second))
    install_audio(game, audio, phrases=True, packed_audio=packed_audio)
    if live:
        data = game / "data.asm"
        code = data.read_bytes()
        sine_start = code.index(b"\nsin:")
        frames_start = code.index(b"\ntileFrames:", sine_start)
        # The menu raster runs in fast RAM without moving the tile animation tables.
        data.write_bytes(code[:sine_start] + b"""
    ifdef LEVEL_MENU
        ifdef LUMINANCE_LOGO
            include "menu_logo_luminance.a80"
        else
            include "menu_logo.a80"
        endif
        assert $ <= #8300
    endif
    org #8300
""" + code[frames_start:])

        resources = game / "gfx" / "resources.a80"
        code = resources.read_bytes()
        test_art = code.index(b"testSprite:")
        tiles = code.index(b";page with tiles", test_art)
        # Leave bank 0 space after the renderer, with the AY recipe still at #cb00.
        scenery_source = f"""    ifdef LEVEL_WAVES
DESTRUCTIBLE_TILE equ {DESTRUCTIBLE_TILE}
BLAST_TILE equ {BLAST_TILE}
SCENERY_MOUNT equ {SCENERY_MOUNT}
        include "destructible.a80"
        include "bottom_hud_updates.a80"
bossArt:
        incbin "boss_nw.bin"
        incbin "boss_ne.bin"
        incbin "boss_sw.bin"
        incbin "boss_se.bin"
        ifdef BONUS_AUDIO
            include "boss_music.a80"
        endif
    endif
    assert $ <= #cb00

""".encode("ascii")
        code = code[:test_art] + scenery_source + code[tiles:]
        if not prototype_waves:
            code = code.replace(b'incbin "tileSet.png.bin"', b'defs 128*48,0', 1)
        code = code.replace(b"    assert testSmallSprite+60 <= #cb00\n", b"", 1)

        levels = "".join(f'packedLevel{n}: incbin "maps/{map_output(n)}.zx0"\n'
                         for n in range(1, len(LEVEL_MAPS) + 1))
        pointers = ",".join(f"packedLevel{n}" for n in range(1, len(LEVEL_MAPS) + 1))
        resources.write_bytes(code + b'''
    page 1
    org audioLiteral0End
''' + f"packedLevels: dw {pointers}\n{levels}".encode("ascii") + b'''
    ifdef LUMINANCE_LOGO
        if MENU_LOGO_PHASES>5
luminance128Extra: incbin "gfx/luminance-128k-extra.bin"
        endif
    endif
''' + game_over_resource + b'''
tileStore1 equ $
    assert $ <= #10000
    ifdef LEVEL_MENU
        page 3
        ifdef LUMINANCE_LOGO
            org #c000
luminance128: incbin "gfx/luminance-128k.bin"
            assert $<=55000
        endif
        org 55000
menuTrackInit:
        incbin "music/player_55000.bin"
menuTrackInitHL equ menuTrackInit+3
menuTrackTick equ menuTrackInit+5
menuTrackMute equ menuTrackInit+8
menuTrackSetup equ menuTrackInit+10
        assert $ <= 57158
        org 57158
        incbin "music/song_57158.bin"
        ifdef LUMINANCE_LOGO
luminancePlus: incbin "gfx/luminance-plus.bin"
        endif
        assert $ <= #10000
        ifdef LUMINANCE_LOGO
            if MENU_LOGO_PHASES>6
                page 7
                org #e000   ; Above the shadow bitmap and attributes.
luminancePlusExtra: incbin "gfx/luminance-plus-extra.bin"
                assert $ <= #10000
            endif
        endif
    endif
    ifdef LEVEL_WAVES
        page 4
        org _tileSetEnd
        include "level_tiles.a80"
        include "tile_lists.a80"
        assert $<=#10000
tileNext4 = $
tileNext1 = tileStore1
tileNext7 = #db00
        include "tile_packets.a80"
        page 6
        org tileSetEnd
        include "enemy_packets.a80"
        assert $<=#10000
    endif
    page 0
    assert testAudioRecipeEnd <= #e000
    ifdef LEVEL_WAVES
        org testAudioRecipeEnd
        align 512
enemyArt: defs 8*256             ; four poses per resident species
yellowArt equ enemyArt+256
catalogPaths: defs 6*256         ; mirrored flight samples and gun gates
        assert (high catalogPaths)*2%256>=#a0 && ((high catalogPaths)+5)*2%256<#c0
        include "enemy_catalog.a80"
        include "boss_transition.a80"
        assert $<=#e000
    endif
    org #e000
    include "enemy_runtime.a80"
    ifdef LIVE_SFX
        include "sound_effects.a80"
    endif
    ifdef LEVEL_MENU
        include "joystick.a80"
    endif
    ifdef LEVEL_WAVES
        include "sky_stars.a80"
        include "scenery_stream.a80"
        DRAW_INCOMING_POOL
        include "boss.a80"
    endif
    assert $ <= #10000
''')
    run([assembler, *(f"-D{name}=1" for name in defines), "--sym=main.sym", "main.asm"], game)


def examine(frames, model):
    margins = {1: [], 2: []}
    signatures = {1: [], 2: []}
    for index, (frame, following) in enumerate(zip(frames, frames[1:])):
        phase = index % 2 + 1
        halt = frame.get(f"halt{3 - phase}", FRAME)
        if (following["start"] != frame["start"] + 1
                or not frame["irq"] < frame.get(f"frame{phase}", FRAME) < frame.get("render_return", FRAME) < halt < FRAME):
            raise ValueError(f"{model}: irregular frame or game-slot overrun at frame {index} (phase {phase})")
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
