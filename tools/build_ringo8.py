"""Rebuild and verify the published Ringo-8 TAPs without opening an emulator."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile


REVISION = "452fcc86d4ed72574a5cced6e8e5d9184d44c0e7"
SAMPLE_COUNT = 12
LAUNCH = re.compile(rb'(?m)^([ \t]*)(SHELLEXEC[ \t]+"main\.tap"[ \t]*)(?=\r?$)')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build(archive_path, assembler, output):
    version = subprocess.run(
        [assembler, "--help"], capture_output=True, text=True, check=True, timeout=10
    )
    banner = next(
        line for line in (version.stdout + version.stderr).splitlines()
        if line.startswith("SjASMPlus Z80 Cross-Assembler")
    )

    with tempfile.TemporaryDirectory(prefix="ringo8-build-") as staging:
        with ZipFile(archive_path) as archive:
            if archive.comment != REVISION.encode("ascii"):
                raise ValueError(f"Expected a GitHub source ZIP for Ringo-8 {REVISION}")
            archive.extractall(staging)

        root, = Path(staging).iterdir()
        samples = sorted(root.glob("[0-9][0-9]_*/main.asm"))
        if len(samples) != SAMPLE_COUNT or not (root / "Engine" / "core.a80").is_file():
            raise ValueError("Unexpected Ringo-8 source layout")

        results = []
        for source in samples:
            sample = source.parent
            tap = sample / "main.tap"
            expected = tap.read_bytes()
            tap.unlink()

            # Disable the upstream post-build launcher in the disposable copy.
            source_bytes, replacements = LAUNCH.subn(rb"\1; \2", source.read_bytes())
            if replacements != 1:
                raise ValueError(f"Unexpected launcher in {sample.name}")
            source.write_bytes(source_bytes)
            assembled = subprocess.run(
                [assembler, "--sym=main.sym", source.name], cwd=sample,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            if assembled.returncode:
                raise ValueError(f"{sample.name} assembly failed:\n{assembled.stdout}{assembled.stderr}")
            actual = tap.read_bytes()
            if actual != expected:
                raise ValueError(
                    f"{sample.name} TAP differs from upstream: "
                    f"expected {sha256(expected)}, got {sha256(actual)}"
                )
            results.append({"sample": sample.name, "bytes": len(actual), "sha256": sha256(actual)})

        for source in samples:
            destination = output / source.parent.name
            destination.mkdir(parents=True, exist_ok=True)
            for artifact in ("main.tap", "main.sym"):
                shutil.copyfile(source.parent / artifact, destination / artifact)

    return {"upstream_revision": REVISION, "assembler": banner, "samples": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--assembler", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = build(args.archive, args.assembler.resolve(strict=True), args.output)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        parser.exit(1, f"Build verification failed: {error}\n")
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
