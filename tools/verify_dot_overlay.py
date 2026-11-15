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

from benchmark_dots import positions
from profile_ringo8 import MODELS, collect, summarise
from verify_sprite_slots import read_baseline, signature, stage_sample
from verify_zesarux_raster import CYAN, HEIGHT, WIDTH, capture_video, paper_row, run


TESTS = Path(__file__).resolve().parents[1] / "tests"
MARKERS = ("overlayBegin", "overlayEnemies", "overlayEnd", "overlayFailed")
COLLISION_MARKERS = ("collisionInit", "collisionPair")
YELLOW = b"\x00\xff\xff"  # BGR24


def build_overlay(archive_path, assembler, directory, scheduled=False):
    sample = stage_sample(archive_path, directory)
    source = sample / "main.asm"
    patched, count = re.subn(rb"(?m)^(\s*jp )mainLoop(?=\r?$)", rb"\1overlayBegin", source.read_bytes())
    marker = b"\tassert $<48830"
    if count != 1 or patched.count(marker) != 1:
        raise ValueError("Unexpected Frame 2 logic slot in the pinned sample")
    source.write_bytes(patched.replace(marker, b'\tinclude "overlay.a80"\n' + marker))
    shutil.copyfile(TESTS / "raster" / "overlay.a80", sample / "overlay.a80")
    shutil.copyfile(TESTS / "dots" / "packed_plot.a80", sample / "packed_plot.a80")
    players, _ = positions(32, "odd")
    _, enemies = positions(32, "even")
    for name, points in (("player", players), ("enemy", enemies)):
        (sample / f"{name}_positions.bin").write_bytes(bytes(axis for point in points for axis in point))
    flags = []
    if scheduled:
        shutil.copyfile(TESTS / "raster" / "scheduled_collision.a80", sample.parent / "Engine" / "spritesRenderBIG.a80")
        shutil.copyfile(TESTS / "collision" / "fixed_collision.a80", sample / "fixed_collision.a80")
        boxes = [(59, 43), (0, 0)] + [((7 * i + 13) % 60, (11 * i + 9) % 44) for i in range(13)]
        player_box = (59, 43)
        (sample / "enemy_boxes.bin").write_bytes(bytes(axis for box in boxes for axis in box))
        (sample / "player_box.bin").write_bytes(bytes(player_box))

        def hit(box, shots, width):
            x, y = box
            return 255 * any(x <= sx + width - 1 and sx < x + 5 and y <= sy < y + 5 for sx, sy in shots)

        expected = bytes([hit(box, players, 2) for box in boxes] + [hit(player_box, enemies, 1)])
        if expected[0] != 255 or expected[-1] != 255 or 0 not in expected:
            raise ValueError("The on-engine collision fixture must include an overlap, hits and misses")
        (sample / "collision_expected.bin").write_bytes(expected)
        flags.append("-DSCHEDULE_COLLISION=1")
    run([assembler, *flags, "--sym=main.sym", "main.asm"], sample)
    return sample


def verify_overlay_video(emulator, sample, model):
    video = sample / f"overlay-{model}.raw"
    capture_video(emulator, model, ["--tape", sample / "main.tap", "--fastautoload", "--vofilefps", "10"], video, 8)
    frame_bytes = WIDTH * HEIGHT * 3
    with video.open("rb") as recording:
        last_frames = deque(iter(lambda: recording.read(frame_bytes), b""), maxlen=8)
    if len(last_frames) != 8 or any(len(frame) != frame_bytes for frame in last_frames):
        raise ValueError(f"{model}: truncated overlay video")
    witnesses = ((0, 0, YELLOW), (1, 0, CYAN), (2, 0, CYAN), (61, 47, CYAN), (62, 47, YELLOW))
    for frame in last_frames:
        for x, y, colour in witnesses:
            if any(paper_row(frame, row)[x * 12:(x + 1) * 12] != colour * 4 for row in range(y * 4, (y + 1) * 4)):
                raise ValueError(f"{model}: missing 4x4 bullet block at ({x},{y})")
    return len(last_frames)


def check_overlay(emulator, sample, model, seconds, stock, scheduled):
    markers = MARKERS + COLLISION_MARKERS if scheduled else MARKERS
    expected = list(MARKERS[:3])
    if scheduled:
        expected = ["collisionInit", *(["collisionPair"] * 15), *expected]
    frames = collect(emulator, sample / "main.tap", sample / "main.sym", model, seconds, markers)
    signatures = {signature(frame) for frame in stock}
    for index, frame in enumerate(frames[:-1]):
        if signature(frame) not in signatures:
            raise ValueError(f"{model}: changed paging schedule at frame {index}")
        events = [(name, clock) for name, clock in frame["events"] if name in markers]
        if index % 2 == 1:
            if [name for name, _ in events] != expected:
                raise ValueError(f"{model}: overlay markers out of order at frame {index}: {events}")
            begin, enemies, end = (clock for _, clock in events[-3:])
            if (enemies - begin, end - enemies) != (2478, 7792):
                raise ValueError(f"{model}: overlay costs changed at frame {index}: {events}")
        elif events:
            raise ValueError(f"{model}: overlay ran during Frame 1")
    if frames and any(name == "overlayFailed" for name, _ in frames[-1]["events"]):
        raise ValueError(f"{model}: on-engine overlay field check failed")
    report = summarise(frames, model, full=False)
    verified_video_frames = verify_overlay_video(emulator, sample, model)
    return {"profile": report, "overlay_tstates": 10270, "player_shots": 9, "enemy_dots": 32,
            "collision_boxes": 16 if scheduled else 0, "verified_video_frames": verified_video_frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, nargs="+", required=True)
    parser.add_argument("--model", choices=MODELS, help="default: check both models")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--collision", action="store_true", help="replace large sprites with fixed-time collision checks")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    try:
        emulator = args.emulator.resolve(strict=True)
        assembler = args.assembler.resolve(strict=True)
        version = next(line for line in run([emulator, "--version"], emulator.parent).splitlines()
                       if line.startswith("ZEsarUX v"))
        baselines = read_baseline(args.baseline, version)
        models = (args.model,) if args.model else MODELS
        with tempfile.TemporaryDirectory(prefix="ringo8-overlay-") as directory:
            sample = build_overlay(args.archive, assembler, Path(directory), args.collision)
            results = [check_overlay(emulator, sample, model, args.seconds, baselines[model], args.collision)
                       for model in models]
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Bullet overlay failed: {error}\n")
    json.dump({"emulator": version, "results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
