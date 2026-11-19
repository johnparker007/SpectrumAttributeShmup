"""Convert the editable artwork into the engine's binary formats."""

import argparse
from math import floor, sin, tau
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
MENU_LOGO = "gfx/blokius-logo.bin"
MENU_LOGO_PALETTES = "gfx/blokius-logo-palettes.bin"
DESTRUCTIBLE_TILE = 124
DESTRUCTIBLE_TILESET = "destructible.tsx"
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


def logo_bitmap(source):
    """Pack a black and white 224×32 PBM in Spectrum screen order."""
    data = source.read_bytes()
    header = re.match(rb"P4\s+(?:#[^\n]*\n\s*)*224\s+32\r?\n", data)
    if header is None or len(data) - header.end() != 28 * 32:
        raise ValueError(f"{source} must be a 224 by 32 binary PBM")
    rows = data[header.end():]
    # PBM uses 1 for black. Set the Spectrum's ink bits for the white logo.
    return bytes(value ^ 255 for scan in range(8) for y in range(scan, 32, 8)
                 for value in rows[y * 28:(y + 1) * 28])


def logo_palettes():
    """Bake four independently moving colour pairs for 256 shimmer steps."""
    rainbow = (0x41, 0x41, 0x45, 0x45, 0x44, 0x44, 0x46, 0x47,
               0x46, 0x46, 0x42, 0x42, 0x43, 0x43, 0x43, 0x01)
    rows = bytearray()
    for frame in range(256):
        turn = frame / 256
        for pair in range(4):
            wave = 2 * sin(tau * ((pair + 1) * turn + pair / 7))
            shade = floor(16 * (3 + 2 * pair) * turn + pair * 4 + wave)
            rows.extend((rainbow[shade % 16], rainbow[(shade + 1) % 16]))
    return bytes(rows)


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
    base = root.find("tileset[@source='tileSet.tsx']")
    target = root.find(f"tileset[@source='{DESTRUCTIBLE_TILESET}']")
    if base is None or base.get("firstgid") != "1":
        raise ValueError("Use the Blokius base tileset with firstgid 1")
    target_gid = None
    if target is not None:
        target_gid = int(target.get("firstgid"))
        tileset = ET.parse(source.parent / DESTRUCTIBLE_TILESET).getroot()
        marker = tileset.find("tile[@id='0']/properties/property[@name='destructible']")
        if target_gid <= 128 or marker is None or marker.get("value") != "true":
            raise ValueError("Place the marked destructible tileset after the 128 base tiles")
    gids = [int(value.strip()) for value in layer.text.split(",") if value.strip()]
    if len(gids) != 1536 or any(not 1 <= gid <= DESTRUCTIBLE_TILE and gid != target_gid for gid in gids):
        raise ValueError("Fill the map with base tiles 0–123 or the intact destructible tile")
    tiles = [DESTRUCTIBLE_TILE if gid == target_gid else gid - 1 for gid in gids]
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
    (output / MENU_LOGO).write_bytes(logo_bitmap(ART / "gfx/blokius-logo.pbm"))
    (output / MENU_LOGO_PALETTES).write_bytes(logo_palettes())
    tiles = convert_image(ART / "gfx/tileSet.png", "converter-tiles.exe", gfx / "tileSet.png.bin", (128, 64))
    if len(tiles) != 6144:
        raise ValueError("The tile converter produced an unexpected sheet size")
    blast_tiles = convert_image(ART / "gfx/destructible.png", "converter-tiles.exe", gfx / "destructible.bin", (32, 8))
    if len(blast_tiles) != 4 * 48:
        raise ValueError("Expected the intact target and three explosion frames")
    (gfx / "tileSet.png.bin").write_bytes(tiles[:DESTRUCTIBLE_TILE * 48] + blast_tiles)
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
    level_targets = bytearray()
    for number, name in enumerate(LEVEL_MAPS, 1):
        unpacked = maps / f"{map_output(number)}.bin"
        data = map_bytes(ART / "maps" / name)
        unpacked.write_bytes(data)
        level_targets.append(DESTRUCTIBLE_TILE in data)
        run([ZX0 / "zx0.exe", "-f", unpacked.resolve(), unpacked.with_suffix(".zx0").resolve()], maps)
    (output / "level_targets.bin").write_bytes(level_targets)


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
