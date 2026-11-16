"""Run the plotted bullet load in the stock engine's Frame 2 game slot."""

import argparse
from collections import deque
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from benchmark_ay import capture as capture_ay
from benchmark_dots import positions
from moving_overlay import ENEMY_BOXES, PLAYER_BOX, hit, phases, prepare, verify_state
from profile_ringo8 import FRAME, MODELS, collect, summarise
from trace_zesarux import read_symbols
from verify_ay_phrases import pack, packets
from verify_ay_stream import loop_audio, register_pairs, verify_rows
from verify_sprite_slots import read_baseline, signature, stage_sample
from verify_zesarux_raster import CYAN, HEIGHT, WIDTH, capture_video, paper_row, run


TESTS = Path(__file__).resolve().parents[1] / "tests"
MARKERS = ("overlayBegin", "overlayEnemies", "overlayEnd", "overlayFailed")
COLLISION_MARKERS = ("collisionInit", "collisionPair")
AUDIO_MARKERS = ("soundTick", "soundTickEnd")
MOTION_MARKERS = ("motionBegin", "motionEnd")
YELLOW = b"\x00\xff\xff"  # BGR24


def install_audio(sample, audio, phrases, packed_audio=None):
    shutil.copyfile(TESTS / "audio" / "engine_stream.a80", sample / "engine_stream.a80")
    gfx = sample / "gfx"
    resources = gfx / "resources.a80"
    added = b'''
    page 0
    assert testSmallSprite+60 <= #cb00
    org #cb00
'''
    if phrases:
        shutil.copyfile(TESTS / "audio" / "engine_phrases.a80", sample / "engine_phrases.a80")
        if packed_audio is None:
            # Split the longer diagnostic tracks early to exercise both banks.
            initial, loop = loop_audio(audio)
            packed_audio = pack([initial, *packets(loop)], first_bank_limit=4096)
        recipe, bank_a, bank_b = packed_audio
        for name, blob in (("recipe.bin", recipe), ("literal0.bin", bank_a), ("literal1.bin", bank_b)):
            (gfx / name).write_bytes(blob)
        added += b'''
testAudioRecipe: incbin "gfx/recipe.bin"
testAudioRecipeEnd:
    assert $<#ffff
    page 1
    org #c000
    incbin "gfx/literal0.bin"
    page 3
    org #c000
    incbin "gfx/literal1.bin"
'''
    else:
        initial, loop = loop_audio(audio)
        (gfx / "sound_stream.bin").write_bytes(initial + loop)
        added += b'''
testAudioStream: incbin "gfx/sound_stream.bin"
testAudioStreamEnd:
    assert $<#ffff
''' + f"testAudioLoop equ testAudioStream+{len(initial)}\n".encode("ascii")
    resources.write_bytes(resources.read_bytes() + added)


def build_overlay(archive_path, assembler, directory, scheduled=False, audio=None, phrases=False, moving=False, fast=False):
    sample = stage_sample(archive_path, directory)
    source = sample / "main.asm"
    patched, count = re.subn(rb"(?m)^([ \t]*jp )mainLoop(?=\r?$)", rb"\1overlayEntry", source.read_bytes())
    marker = b"\tassert $<48830"
    if count != 1 or patched.count(marker) != 1:
        raise ValueError("Unexpected Frame 2 logic slot in the pinned sample")
    patched = patched.replace(marker, b'\tinclude "overlay.a80"\n' + marker)
    shutil.copyfile(TESTS / "raster" / "overlay.a80", sample / "overlay.a80")
    shutil.copyfile(TESTS / "dots" / "packed_plot.a80", sample / "packed_plot.a80")
    players, _ = positions(32, "odd")
    _, enemies = positions(32, "even")
    for name, points in (("player", players), ("enemy", enemies)):
        (sample / f"{name}_positions.bin").write_bytes(bytes(axis for point in points for axis in point))
    flags = []
    if moving:
        if patched.count(b"\tcall moveSprites") != 1:
            raise ValueError("Unexpected motion hook in the pinned example")
        patched = patched.replace(b"\tcall moveSprites", b"\tcall motionStep")
        shutil.copyfile(TESTS / "raster" / "moving_overlay.a80", sample / "moving_overlay.a80")
        shutil.copyfile(TESTS / "dots" / "motion_step.a80", sample / "motion_step.a80")
        prepare(sample)
        flags.append("-DOVERLAY_MOTION=1")
    if fast:
        flags.append("-DOVERLAY_FAST_PLOT=1")
    if scheduled:
        shutil.copyfile(TESTS / "raster" / "scheduled_collision.a80", sample.parent / "Engine" / "spritesRenderBIG.a80")
        shutil.copyfile(TESTS / "collision" / "fixed_collision.a80", sample / "fixed_collision.a80")
        boxes = ENEMY_BOXES if moving else [(59, 43), (0, 0)] + [((7 * i + 13) % 60, (11 * i + 9) % 44) for i in range(13)]
        player_box = PLAYER_BOX if moving else (59, 43)
        (sample / "enemy_boxes.bin").write_bytes(bytes(axis for box in boxes for axis in box))
        (sample / "player_box.bin").write_bytes(bytes(player_box))

        expected = phases()[0].hits if moving else bytes([hit(box, players, 2) for box in boxes] + [hit(player_box, enemies, 1)])
        if not moving and (expected[0] != 255 or expected[-1] != 255 or 0 not in expected):
            raise ValueError("The on-engine collision fixture must include an overlap, hits and misses")
        (sample / "collision_expected.bin").write_bytes(expected)
        flags.append("-DSCHEDULE_COLLISION=1")
    if audio is not None:
        if patched.count(b"\tcall doSinScroll") != 1:
            raise ValueError("Unexpected AY hook in the pinned example")
        patched = patched.replace(b"\tcall doSinScroll", b"\tcall soundScroll")
        install_audio(sample, audio, phrases)
        flags.append("-DOVERLAY_AUDIO=1")
        if phrases:
            flags.append("-DOVERLAY_PHRASES=1")
    source.write_bytes(patched)
    run([assembler, *flags, "--sym=main.sym", "main.asm"], sample)
    return sample


def verify_overlay_video(emulator, sample, model, moving=None):
    video = sample / f"overlay-{model}.raw"
    capture_video(emulator, model, ["--tape", sample / "main.tap", "--fastautoload", "--vofilefps", "10"], video, 8)
    frame_bytes = WIDTH * HEIGHT * 3
    with video.open("rb") as recording:
        last_frames = deque(iter(lambda: recording.read(frame_bytes), b""), maxlen=8)
    if len(last_frames) != 8 or any(len(frame) != frame_bytes for frame in last_frames):
        raise ValueError(f"{model}: truncated overlay video")
    witnesses = ((0, 0, YELLOW), (1, 0, CYAN), (2, 0, CYAN), (61, 47, CYAN), (62, 47, YELLOW))
    scenes = [witnesses] if moving is None else [
        [(x, y, CYAN if colour == 5 else YELLOW) for (x, y), colour in phase.dots.items()] for phase in moving
    ]
    observed = set()
    for frame in last_frames:
        paper = [paper_row(frame, row) for row in range(192)]
        for index, scene in enumerate(scenes):
            if all(all(paper[row][x * 12:(x + 1) * 12] in (colour * 4, bytes(c and 192 for c in colour) * 4)
                       for row in range(y * 4, (y + 1) * 4)) for x, y, colour in scene):
                observed.add(index)
                break
        else:
            raise ValueError(f"{model}: missing 4x4 bullet blocks in overlay video")
    if moving is not None and len(observed) < 3:
        raise ValueError(f"{model}: video did not show moving projectiles")
    return len(last_frames)


def verify_audio(emulator, sample, model, audio, phrases, whole_song=False, seconds=0, mix=None):
    result = {}
    symbols = read_symbols(sample / "main.sym")
    symbols.update(tick_begin=symbols["soundTick"], tick_end=symbols["soundTickEnd"])
    points = {
        f"PC={symbols['soundSelect']:04X}H AND BC=FFFDH": ("select", "TSTATES*256+A"),
        f"PC={symbols['soundWrite']:04X}H AND BC=BFFDH": ("data", "TSTATES*256+A"),
    }
    init, loop = loop_audio(audio)
    if phrases:
        for name in ("soundPageIn", "soundPageOut"):
            points[f"PC={symbols[name]:04X}H AND BC=7FFDH"] = ("page", "TSTATES*256+A")
        loop_packets = list(packets(loop))
        if whole_song:
            reference = [*audio, *audio[1:33]]
            expected_wire = init + loop + b"".join(loop_packets[:32])
        else:
            reference = audio[:1025]
            expected_wire = init + b"".join(loop_packets[:1024])
    else:
        reference = [audio[0], *audio[1:], *audio[1:]]
        expected_wire = init + loop * 2
    if mix is not None:
        expected_wire = mix(expected_wire)
        reference = [list(zip(packet[:-1:2], packet[1:-1:2], strict=True)) for packet in packets(expected_wire)]
        points.update({
            f"PC={symbols['soundEffectSelect']:04X}H AND BC=FFFDH": ("select", "TSTATES*256+A"),
            f"PC={symbols['soundEffectWrite']:04X}H AND BC=BFFDH": ("data", "TSTATES*256+E"),
        })
    audio_seconds = max(80, seconds, (len(reference) + 20) // 21) if whole_song else (65 if phrases else 40)
    capture = capture_ay(emulator, sample / "main.tap", symbols, model, audio_seconds,
                         points, len(reference) - 1)
    writes = [register_pairs(capture["initial_writes"])]
    writes.extend(register_pairs(tick["writes"]) for tick in capture["ticks"])
    verify_rows(writes, reference, model, expected_wire)
    if mix is not None:
        state = {}
        overlap = 0
        for tick in writes:
            state.update(tick)
            overlap += bool(state[10] and not (state[7] & 16))
        if not overlap:
            raise ValueError(f"{model}: shot and explosion were never active together")
        result["audio_overlapping_effect_ticks"] = overlap
    if phrases:
        page_map = (0x11, 0x13) if model == "128k" else (0x14, 0x16)
        recipe = (sample / "gfx" / "recipe.bin").read_bytes()
        loop_pages = [page_map[high >> 6] for high, count in zip(recipe[4::3], recipe[5::3], strict=True)
                      for _ in range(count)]
        visited = set()
        for index, tick in enumerate(capture["ticks"]):
            (start, selected), (end, restored) = tick["pages"]
            begin = tick["begin"] % FRAME
            if (selected != loop_pages[index % len(loop_pages)] or restored != 0x10
                    or not begin < start < end < begin + tick["cost"]):
                raise ValueError(f"{model}: AY paging escaped its game-logic tick")
            visited.add(selected)
        result["audio_physical_banks"] = sorted(value & 7 for value in visited)
    result["audio_ticks_verified"] = len(reference) - 1
    result["audio_tick_cost_range"] = [cost + 27 for cost in capture["tick_cost_range"]]
    return result


def check_overlay(emulator, sample, model, seconds, stock, scheduled, audio, phrases=False, moving=False, fast=False,
                  whole_song=False):
    markers = MARKERS + COLLISION_MARKERS if scheduled else MARKERS
    expected1 = list(AUDIO_MARKERS) if audio is not None else []
    expected2 = [*expected1, *MARKERS[:3]]
    if audio is not None:
        markers += AUDIO_MARKERS
    if moving:
        markers += MOTION_MARKERS
        expected1 += list(MOTION_MARKERS)
    if scheduled:
        expected2 = ["collisionInit", *(["collisionPair"] * 15), *expected2]
    plot_costs = (2276, 7276) if fast else (2478, 8112 if moving else 7792)
    frames = collect(emulator, sample / "main.tap", sample / "main.sym", model, seconds, markers)
    signatures = {signature(frame) for frame in stock}
    audio_costs = []
    motion_costs = []
    for index, frame in enumerate(frames[:-1]):
        if signature(frame) not in signatures:
            raise ValueError(f"{model}: changed paging schedule at frame {index}")
        events = [(name, clock) for name, clock in frame["events"] if name in markers]
        if [name for name, _ in events] != (expected2 if index % 2 else expected1):
            raise ValueError(f"{model}: projectile or AY markers out of order at frame {index}: {events}")
        if audio is not None:
            points = dict(events)
            audio_costs.append(points["soundTickEnd"] - points["soundTick"] + 27)
        if moving and index % 2 == 0:
            points = dict(events)
            motion_costs.append(points["motionEnd"] - points["motionBegin"] + 27)
        if index % 2 == 1:
            begin, enemies, end = (clock for _, clock in events[-3:])
            if (enemies - begin, end - enemies) != plot_costs:
                raise ValueError(f"{model}: overlay costs changed at frame {index}: {events}")
    if frames and any(name == "overlayFailed" for name, _ in frames[-1]["events"]):
        raise ValueError(f"{model}: on-engine overlay field check failed")
    report = summarise(frames, model, full=False)
    scenario = phases() if moving else None
    verified_video_frames = verify_overlay_video(emulator, sample, model, scenario)
    result = {"profile": report, "overlay_tstates": sum(plot_costs), "player_shots": 9, "enemy_dots": 32,
              "collision_boxes": 16 if scheduled else 0, "verified_video_frames": verified_video_frames}
    if audio is not None:
        result.update(verify_audio(emulator, sample, model, audio, phrases, whole_song, seconds))
        if not whole_song:
            result["audio_tick_cost_range"] = [min(audio_costs), max(audio_costs)]
    if moving:
        result["motion_tstate_range"] = [min(motion_costs), max(motion_costs)]
        result["projectile_motion_phases_verified"] = verify_state(emulator, sample, model, scenario)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, nargs="+", required=True)
    parser.add_argument("--model", choices=MODELS, help="default: check both models")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--collision", action="store_true", help="replace large sprites with fixed-time collision checks")
    parser.add_argument("--motion", action="store_true", help="advance a bounded moving fixture and verify its hit flags")
    parser.add_argument("--fast-plot", action="store_true", help="use the linear position iterator with --motion")
    parser.add_argument("--whole-song", action="store_true", help="trace all banked AY ticks and 32 ticks after wrap")
    parser.add_argument("--output-tap", type=Path, help="save the verified experimental TAP")
    audio_mode = parser.add_mutually_exclusive_group()
    audio_mode.add_argument("--audio-reference", type=Path, help="play the 256-tick prefix from the AY reference benchmark")
    audio_mode.add_argument("--phrase-reference", type=Path, help="load complete banked playback from benchmark_ay.py --through-loop")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    if args.motion and not args.collision:
        parser.error("--motion uses the scheduled collision checks, so it requires --collision")
    if args.fast_plot and not args.motion:
        parser.error("--fast-plot is measured with the moving fixture, so it requires --motion")
    if args.whole_song and args.phrase_reference is None:
        parser.error("--whole-song requires --phrase-reference")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        baselines = read_baseline(args.baseline, version)
        models = (args.model,) if args.model else MODELS
        audio = None
        audio_path = args.audio_reference or args.phrase_reference
        phrases = args.phrase_reference is not None
        if audio_path is not None:
            source = json.loads(audio_path.read_text(encoding="utf-8-sig"))
            if not source["passed"] or source["emulator"] != version:
                raise ValueError("Expected a verified AY reference from this emulator version")
            case = source["results"][0]
            minimum = 1024 if phrases else 256
            if args.whole_song and not source.get("through_loop"):
                raise ValueError("Whole-song verification needs a reference recorded with --through-loop")
            if len(case["ticks"]) < minimum:
                raise ValueError(f"The AY reference needs at least {minimum} ticks")
            audio = [register_pairs(case["initial_writes"])]
            ticks = case["ticks"] if phrases else case["ticks"][:256]
            audio.extend(register_pairs(tick["writes"]) for tick in ticks)
        with tempfile.TemporaryDirectory(prefix="ringo8-overlay-") as directory:
            sample = build_overlay(args.archive, assembler, Path(directory), scheduled=args.collision, audio=audio,
                                   phrases=phrases, moving=args.motion, fast=args.fast_plot)
            results = [check_overlay(emulator, sample, model, args.seconds, baselines[model], args.collision, audio,
                                     phrases=phrases, moving=args.motion, fast=args.fast_plot, whole_song=args.whole_song)
                       for model in models]
            if args.output_tap is not None:
                shutil.copyfile(sample / "main.tap", args.output_tap)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Bullet overlay failed: {error}\n")
    json.dump({"emulator": version, "results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
