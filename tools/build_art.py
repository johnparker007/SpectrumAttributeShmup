"""Convert the editable artwork into the engine's binary formats."""

import argparse
from pathlib import Path
import re
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET

from verify_zesarux_raster import run


ART = Path(__file__).resolve().parents[1] / "art"
ZX0 = ART.parent / "vendor" / "zx0"
LEVEL_MAPS = ("level.tmx", *(f"level-{number}.tmx" for number in range(2, 9)))
SCREEN_FONT = "font/arcade-8.bin"
SPRITES = {
    "player": "player_art.bin",
    "enemy_green_sine": "enemy_art.bin",
    "explosion_1": "explosion_1.bin",
    "explosion_2": "explosion_2.bin",
    "explosion_3": "explosion_3.bin",
}


def arcade_font(source):
    """Pack the native 8×8 BDF cells as eight Spectrum bitmap rows per glyph."""
    codes = range(32, 96)
    bdf = source.read_text(encoding="ascii")
    records = re.findall(
        r"^ENCODING (\d+)\nSWIDTH [^\n]+\nDWIDTH 8 0\nBBX ([^\n]+)\nBITMAP\n([0-9A-F\n]+)ENDCHAR$",
        bdf, re.MULTILINE,
    )
    glyphs = {}
    for encoding, bounds, bitmap in records:
        number = int(encoding)
        if number not in codes:
            continue
        width, height, x, y = map(int, bounds.split())
        rows = bytes.fromhex(bitmap)
        top = 8 - y - height
        if x < 0 or y < 0 or x + width > 8 or top < 0 or len(rows) != height:
            raise ValueError(f"Arcade font glyph {number} exceeds its 8×8 cell")
        glyphs[number] = bytes(top) + bytes(row >> x for row in rows) + bytes(y)
    if len(glyphs) != len(codes):
        raise ValueError("The arcade font must supply ASCII glyphs 32 through 95")
    return b"".join(glyphs[number] for number in codes)


def convert_image(source, converter, output, size):
    header = source.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != size:
        raise ValueError(f"{source} must be a {size[0]} by {size[1]} PNG")
    with tempfile.TemporaryDirectory(prefix="shmup-art-") as scratch:
        image = Path(scratch) / source.name
        shutil.copyfile(source, image)
        run([ART / "gfx" / converter, image], Path(scratch))
        data = image.with_suffix(".png.bin").read_bytes()
    output.write_bytes(data)
    return data


def map_bytes(source):
    root = ET.parse(source).getroot()
    layers = root.findall("layer")
    if (root.get("width"), root.get("height")) != ("256", "6") or len(layers) != 1:
        raise ValueError("The scenery map must have one 256 by 6 tile layer")
    layer = layers[0].find("data")
    if layer is None or layer.get("encoding") != "csv" or layer.get("compression"):
        raise ValueError("Save the scenery map with CSV layer data")
    tiles = [int(value.strip()) - 1 for value in layer.text.split(",") if value.strip()]
    if len(tiles) != 1536 or any(tile < 0 or tile >= 128 for tile in tiles):
        raise ValueError("Fill the map using tile IDs from the 128-tile sheet")
    # The barrel starts with nine complete columns, then streams six tiles
    # per incoming column. Preserve that layout when exporting from Tiled.
    opening = [tiles[y * 256 + x] for y in range(6) for x in range(9)]
    incoming = [tiles[y * 256 + x] for x in range(9, 256) for y in range(6)]
    return bytes(opening + incoming)


def map_output(number):
    return f"tilemap-{number}" if number > 1 else "tilemap"


def build_art(output, *, sprite_dir=None):
    output.mkdir(parents=True, exist_ok=True)
    font = output / SCREEN_FONT
    font.parent.mkdir(exist_ok=True)
    font.write_bytes(arcade_font(ART / "fonts/PressStart2P-8.bdf"))
    gfx = output / "gfx"
    gfx.mkdir(exist_ok=True)
    tiles = convert_image(ART / "gfx/tileSet.png", "converter-tiles.exe", gfx / "tileSet.png.bin", (128, 64))
    if len(tiles) != 6144:
        raise ValueError("The tile converter produced an unexpected sheet size")
    if sprite_dir is None:
        sprite_dir = ART / "sprites"
        sprites = {**SPRITES, "enemy_yellow_z": "yellow_art.bin"}
    else:
        sprites = SPRITES
    for name, filename in sprites.items():
        target = output / filename
        data = convert_image(sprite_dir / f"{name}.png", "converter-sprites.exe", target, (5, 5))
        if len(data) != 60:
            raise ValueError(f"The sprite converter produced an unexpected size for {name}")
        # The live compositor preserves the destination's bright/flash bits.
        target.write_bytes(bytes(value | 192 if index % 2 == 0 else value & 63
                                 for index, value in enumerate(data)))
    maps = output / "maps"
    maps.mkdir(exist_ok=True)
    for number, name in enumerate(LEVEL_MAPS, 1):
        unpacked = maps / f"{map_output(number)}.bin"
        unpacked.write_bytes(map_bytes(ART / "maps" / name))
        run([ZX0 / "zx0.exe", "-f", unpacked.resolve(), unpacked.with_suffix(".zx0").resolve()], maps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ART.parent / "build/art")
    args = parser.parse_args()
    try:
        build_art(args.output.resolve())
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f"Artwork conversion failed: {error}\n")
    print(f"Converted artwork to {args.output.resolve()}")


if __name__ == "__main__":
    main()
