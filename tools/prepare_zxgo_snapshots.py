"""Prepare model-specific stock snapshots for the independent zx_go probe."""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

from profile_ringo8 import TAP_SHA256
from verify_sprite_slots import stage_sample
from verify_zesarux_raster import PROBE, run


def build(archive, assembler, output):
    with tempfile.TemporaryDirectory(prefix="ringo8-zxgo-") as directory:
        scratch = Path(directory)
        sample = stage_sample(archive, scratch)
        source = sample / "main.asm"
        start_loader = b'\tinclude "../engine/loader.a80"'
        data = source.read_bytes()
        if data.count(start_loader) != 1:
            raise ValueError("Unexpected stock sample loader")
        source.write_bytes(data.replace(start_loader, b'\tSAVESNA "independent.sna",start\n' + start_loader))
        run([assembler, "main.asm"], sample)
        if hashlib.sha256((sample / "main.tap").read_bytes()).hexdigest() != TAP_SHA256:
            raise ValueError("Adding a snapshot directive changed the stock TAP")
        snapshot = (sample / "independent.sna").read_bytes()
        bank_size = 0x4000
        extra_banks = 27 + 3 * bank_size + 4
        if len(snapshot) != extra_banks + 5 * bank_size or snapshot[extra_banks - 2] != 0x10:
            raise ValueError("Expected a 128K SNA with bank 0 mapped and the loader's ROM bit")
        output.mkdir(parents=True, exist_ok=True)
        (output / "engine-128k.sna").write_bytes(snapshot)
        # The TAP loader swaps logical pages 1/4 and 3/6 on +2A. Match it
        # for the SNA, whose five trailing pages are in order 1,3,4,6,7.
        pages = [snapshot[extra_banks + index * bank_size:extra_banks + (index + 1) * bank_size]
                 for index in (2, 3, 0, 1, 4)]
        (output / "engine-plus2a.sna").write_bytes(snapshot[:extra_banks] + b"".join(pages))
        for loops in (1079, 1080):
            run([assembler, f"-DDELAY_LOOPS={loops}", PROBE], scratch)
            shutil.copyfile(scratch / "shadow_screen.sna", output / f"probe-{loops}.sna")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.archive, args.assembler.resolve(strict=True), args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Independent snapshot build failed: {error}\n")


if __name__ == "__main__":
    main()
