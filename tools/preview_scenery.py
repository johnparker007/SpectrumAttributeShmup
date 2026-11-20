"""Render the editable TMX files to one PNG using ImageMagick. No assembler required."""

import argparse
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from build_art import ART, LEVEL_MAPS, map_bytes


def read_atlas(name):
    return subprocess.check_output(["magick", ART / "gfx" / name, "-depth", "8", "rgb:-"])


def render_map(source, scenery, fixtures, start, columns):
    data = map_bytes(source)
    pixels = bytearray()
    for y in range(46):  # last two dot rows sit underneath the HUD
        for x in range(start, start + columns):
            index = y//8 * 9 + x if x < 9 else 54 + 6 * (x-9) + y//8
            tile = data[index]
            if tile >= 124:
                atlas = fixtures
                offset = ((y % 8) * 56 + (tile-124) * 8) * 3
            else:
                atlas = scenery
                offset = (((tile//16)*8 + y%8)*128 + (tile%16)*8) * 3
            pixels.extend(atlas[offset:offset+24])
    return f"P6\n{columns*8} 46\n255\n".encode("ascii") + pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--column", type=int, choices=range(249), metavar="0..248",
                        help="Show a playable screen from each route, starting at this tile column")
    args = parser.parse_args()
    scenery, fixtures = (read_atlas(n) for n in ("tileSet.png", "destructible.png"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blokius-map-preview-") as tmp:
        rows = []
        for number, filename in enumerate(LEVEL_MAPS, 1):
            source = ART / "maps" / filename
            name = ET.parse(source).find("layer").get("name")
            overview = args.column is None
            pixels = render_map(source, scenery, fixtures, args.column or 0, 256 if overview else 8)
            output = Path(tmp) / f"{number}.png"
            scale = "2048x46!" if overview else "256x184!"
            subprocess.run(["magick", "ppm:-", "-scale", scale, "-gravity", "northwest",
                            "-background", "#151821", "-splice", "0x24", "-fill", "white",
                            "-font", "Consolas", "-pointsize", "15", "-annotate", "+8+2",
                            f"{number}   {name}", output], input=pixels, check=True)
            rows.append(output)
        subprocess.run(["magick", "montage", *rows, "-tile", "1x9" if overview else "3x3",
                        "-geometry", "+2+2", "-background", "#202431", args.output], check=True)


if __name__ == "__main__":
    main()
