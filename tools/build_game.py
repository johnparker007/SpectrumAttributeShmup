"""Build a keyboard-controlled TAP using the artwork in this checkout."""

import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile

from profile_blokius import ARCHIVE, build
from verify_blokius_integration import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output-tap", type=Path, default=ARCHIVE.parent.parent / "build/game.tap")
    logo = parser.add_mutually_exclusive_group()
    logo.add_argument("--solid-menu-logo", dest="luminance_logo", action="store_false",
                      help="Fill the logo rectangle to inspect all 28 raster cells")
    logo.add_argument("--luminance-logo", action="store_true",
                      help="Use the 50 Hz luminance logo and cyan copper text (default)")
    parser.set_defaults(luminance_logo=True)
    args = parser.parse_args()
    try:
        assembler = args.assembler.resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="shmup-build-") as scratch:
            game = build(args.archive.resolve(strict=True), assembler, Path(scratch))
            install(game, assembler, live=True, solid_menu_logo=not args.luminance_logo,
                    luminance_logo=args.luminance_logo)
            args.output_tap.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(game / "main.tap", args.output_tap)
        print(f"Built {args.output_tap.resolve()}")
        print(f"SHA-256 {hashlib.sha256(args.output_tap.read_bytes()).hexdigest()}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Game build failed: {error}\n")


if __name__ == "__main__":
    main()
