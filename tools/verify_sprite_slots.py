"""Verify that bounded work can replace large-sprite drawing at the stock paging cadence."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from build_ringo8 import LAUNCH, REVISION
from profile_ringo8 import MODELS, TAP_SHA256, collect, summarise
from verify_zesarux_raster import run


REPLACEMENT = Path(__file__).resolve().parents[1] / "tests" / "raster" / "large_sprite_slots.a80"
SLICE_MARKERS = ("rasterWork", "rasterWorkEnd")
EXPECTED_SLICES = [996, *([1464] * 15), 281]


def build_experiment(archive_path, assembler, directory):
    with ZipFile(archive_path) as archive:
        if archive.comment != REVISION.encode("ascii"):
            raise ValueError(f"Expected the pinned Ringo-8 ZIP at {REVISION}")
        archive.extractall(directory)
    root, = directory.iterdir()
    sample = root / "05_EXAMPLE_ALL_SPRITES"
    tap = sample / "main.tap"
    if hashlib.sha256(tap.read_bytes()).hexdigest() != TAP_SHA256:
        raise ValueError("The archive does not contain the verified stock TAP")
    source = sample / "main.asm"
    data, patches = LAUNCH.subn(rb"\1; \2", source.read_bytes())
    if patches != 1:
        raise ValueError("Unexpected sample launcher")
    source.write_bytes(data)
    shutil.copyfile(REPLACEMENT, root / "Engine" / "spritesRenderBIG.a80")
    tap.unlink()
    run([assembler, "--sym=main.sym", "main.asm"], sample)
    return sample


def read_baseline(paths, version):
    cases = {}
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        if (report.get("upstream_revision") != REVISION or report.get("tap_sha256") != TAP_SHA256
                or not report.get("passed") or report.get("emulator") != version):
            raise ValueError(f"{path}: expected the verified stock profile from this emulator version")
        for case in report["models"]:
            if not case.get("frames") or case["motion_phases"] != 256:
                raise ValueError(f"{path}: use --full and cover all 256 stock motion phases")
            cases[case["model"]] = case["frames"]
    return cases


def signature(frame):
    return tuple((write["pc"], write["value"], write["latch"]) for write in frame["writes"])


def check_experiment(emulator, sample, model, seconds, stock_frames):
    frames = collect(emulator, sample / "main.tap", sample / "main.sym", model, seconds, SLICE_MARKERS)
    stock_signatures = {signature(frame) for frame in stock_frames}
    saved_slices = []
    for index, frame in enumerate(frames[:-1]):
        if signature(frame) not in stock_signatures:
            raise ValueError(f"{model}: frame {index} changed the stock paging schedule")
        if index % 2 == 0:
            continue
        boundaries = dict(frame["events"])
        markers = [(name, when) for name, when in frame["events"]
                   if name in SLICE_MARKERS and boundaries["large_begin"] < when < boundaries["large_end"]]
        if [name for name, _ in markers] != list(SLICE_MARKERS) * len(EXPECTED_SLICES):
            raise ValueError(f"{model}: frame {index} missed a workload slice")
        slices = [end[1] - begin[1] for begin, end in zip(markers[::2], markers[1::2])]
        if slices != EXPECTED_SLICES:
            raise ValueError(f"{model}: frame {index} executed unexpected workload timings: {slices}")
        if not saved_slices:
            saved_slices = [(begin[1], end[1]) for begin, end in zip(markers[::2], markers[1::2])]
    report = summarise(frames, model, full=False)
    return {"profile": report, "first_workload_slices": saved_slices, "workload_body_tstates": sum(EXPECTED_SLICES),
            "workload_with_calls_tstates": sum(EXPECTED_SLICES) + 34 * len(EXPECTED_SLICES)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, nargs="+", required=True, help="stock JSON report(s) from profile_ringo8.py --full")
    parser.add_argument("--model", choices=MODELS, help="default: check both models")
    parser.add_argument("--seconds", type=int, default=90, help="wall-clock capture length per model")
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
        with tempfile.TemporaryDirectory(prefix="ringo8-large-slots-") as directory:
            sample = build_experiment(args.archive, assembler, Path(directory))
            tap_hash = hashlib.sha256((sample / "main.tap").read_bytes()).hexdigest()
            results = [check_experiment(emulator, sample, model, args.seconds, baselines[model])
                       for model in models]
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Large sprite slot verification failed: {error}\n")
    json.dump({"emulator": version, "upstream_revision": REVISION, "tap_sha256": tap_hash,
               "results": results, "passed": True}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
