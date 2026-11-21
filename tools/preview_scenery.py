"""Render the editable TMX files to one PNG using ImageMagick. No assembler required."""

import argparse
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from build_art import ART, LEVEL_MAPS
from compose_scenery import LANDMARK_PARTS
from level_tiles import read_map


def render_map(source, cache, start, columns):
    cells, sheets = read_map(source)
    for sheet in sheets.values():
        if sheet.image not in cache:
            cache[sheet.image] = subprocess.check_output(["magick", sheet.image, "-depth", "8", "rgb:-"])
    pixels = bytearray()
    for y in range(46):  # last two dot rows sit underneath the HUD
        for x in range(start, start + columns):
            name, tile = cells[y//8 * 256 + x]
            sheet = sheets[name]
            width = sheet.size[0]
            row, col = divmod(tile, width//8)
            offset = ((row*8 + y%8)*width + col*8) * 3
            pixels.extend(cache[sheet.image][offset:offset+24])
    return f"P6\n{columns*8} 46\n255\n".encode("ascii") + pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--column", type=int, choices=range(249), metavar="0..248",
                        help="Show a playable screen from each route, starting at this tile column")
    view.add_argument("--landmarks", action="store_true", help="Show a two-screen landmark from each sector")
    args = parser.parse_args()
    atlases = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blokius-map-preview-") as tmp:
        rows = []
        for number, filename in enumerate(LEVEL_MAPS, 1):
            source = ART / "maps" / filename
            name = ET.parse(source).find("layer").get("name")
            overview = args.column is None and not args.landmarks
            if args.landmarks:
                start, columns, scale = 16 * LANDMARK_PARTS[number-1][0], 16, "384x138!"
            elif overview:
                start, columns, scale = 0, 256, "2048x46!"
            else:
                start, columns, scale = args.column, 8, "256x184!"
            pixels = render_map(source, atlases, start, columns)
            output = Path(tmp) / f"{number}.png"
            subprocess.run(["magick", "ppm:-", "-scale", scale, "-gravity", "northwest",
                            "-background", "#151821", "-splice", "0x24", "-fill", "white",
                            "-font", "Consolas", "-pointsize", "15", "-annotate", "+8+2",
                            f"{number}   {name}", output], input=pixels, check=True)
            rows.append(output)
        subprocess.run(["magick", "montage", *rows, "-tile", "1x9" if overview else "3x3",
                        "-geometry", "+2+2", "-background", "#202431", args.output], check=True)


if __name__ == "__main__":
    main()
