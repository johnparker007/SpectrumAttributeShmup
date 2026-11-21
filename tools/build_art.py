"""Convert the editable artwork into the engine's binary formats."""

import argparse
from pathlib import Path
import re
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET

from verify_zesarux_raster import run
from enemy_catalog import FLIERS, pack_catalog
from level_tiles import BASE, TARGETS, layout, pack_tiles, read_map, read_sheet
from level_tiles import BLAST as BLAST_TILE, MOUNT as SCENERY_MOUNT, TARGET as DESTRUCTIBLE_TILE


ART = Path(__file__).resolve().parents[1] / "art"
ZX0 = ART.parent / "vendor" / "zx0"
LEVEL_MAPS = ("level.tmx", *(f"level-{number}.tmx" for number in range(2, 10)))
SCREEN_FONT = "font/arcade-8.bin"
MENU_LOGO = "gfx/blokius-logo.bin"
MENU_LOGO_RASTER = "gfx/blokius-logo-raster.bin"
# Both four-band runs return to green. Red and magenta are always separated.
MENU_LOGO_WARM = (0x44, 0x46, 0x42, 0x47)  # Green, yellow, red, white.
MENU_LOGO_COOL = (0x44, 0x45, 0x41, 0x43)  # Green, cyan, blue, magenta.
# Each six-bit window in this circular order is unique, so nearby sections
# of the ribbon keep changing even when only part of the strip is visible.
MENU_LOGO_RUN_ORDER = bytes.fromhex("69 cb 66 24 28 fd 5d e0")
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


def logo_bands():
    """Build a 512-band ring with equal warm and cool runs."""
    runs = (MENU_LOGO_WARM + MENU_LOGO_COOL, MENU_LOGO_COOL + MENU_LOGO_WARM)
    return b"".join(bytes(runs[(order >> bit) & 1])
                    for order in MENU_LOGO_RUN_ORDER for bit in range(7, -1, -1))


def logo_raster():
    """Pack the palette words followed by the right-to-left PUSH tables."""
    bands = logo_bands()
    # Each parity has four distinct ink pairs, one per PUSH register.
    palette = []
    opcodes = []
    for parity in range(2):
        pairs = dict.fromkeys((bands[x], bands[(x + 1) % len(bands)])
                              for x in range(parity, len(bands), 2))
        opcodes.append(dict(zip(pairs, (0xC5, 0xD5, 0xE5, 0xF5), strict=True)))
        palette.append(bytes(ink for pair in pairs for ink in pair))
    even, odd = palette
    tables = bytearray(odd + even + odd)
    for parity in range(2):
        page = bytearray()
        for pair in range(256):
            x = (parity - 2 * pair) % len(bands)
            pair_inks = (bands[x], bands[(x + 1) % len(bands)])
            page.append(opcodes[parity][pair_inks])
        # A run of LDI instructions may cross the end of the page.
        tables.extend(page * 2)
    return bytes(tables)


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


def map_output(number):
    return f"tilemap-{number}" if number > 1 else "tilemap"


def hud_life_icon(sprite):
    """Make a monochrome ship, retaining the wing tips and a cut-out cyan cockpit."""
    hull = [0] * 8
    canopy = [0] * 8
    # The digits occupy scanlines 1-7. Centre the five sprite rows on 2-6.
    # Each mask/colour pair in the even-X sprite holds two three-bit dots.
    for y in range(5):
        for x in range(5):
            offset = 6 * y + 2 * (x // 2)
            mask, colours = sprite[offset:offset + 2]
            shift = 3 * (x % 2)
            bit = 0x40 >> x
            if ((mask >> shift) & 7) == 0:
                hull[y + 2] |= bit
                if ((colours >> shift) & 7) == 5:
                    canopy[y + 2] |= bit
    icon = hull.copy()
    for y in range(2, 7):
        interior = hull[y - 1] & hull[y + 1] & (hull[y] << 1) & (hull[y] >> 1)
        icon[y] &= ~(interior & canopy[y])
    return bytes(icon)


def build_art(output, *, sprite_dir=None):
    output.mkdir(parents=True, exist_ok=True)
    font = output / SCREEN_FONT
    font.parent.mkdir(exist_ok=True)
    font.write_bytes(arcade_font(ART / "fonts/Blokius-Arcade-8.bdf"))
    gfx = output / "gfx"
    gfx.mkdir(exist_ok=True)
    (output / MENU_LOGO).write_bytes(logo_bitmap(ART / "gfx/blokius-logo.pbm"))
    (output / MENU_LOGO_RASTER).write_bytes(logo_raster())
    levels = []
    sheets = {}
    for filename in LEVEL_MAPS:
        cells, used_sheets = read_map(ART / "maps" / filename)
        try:
            levels.append(layout(cells, used_sheets))
        except ValueError as error:
            raise ValueError(f"{filename}: {error}") from error
        sheets.update(used_sheets)
    if TARGETS not in sheets:
        sheets[TARGETS] = read_sheet(ART / "maps" / TARGETS)
    raw = {name: convert_image(sheet.image, "converter-tiles.exe", gfx / (sheet.image.stem + ".bin"), sheet.size)
           for name, sheet in sheets.items()}
    if any(len(raw[name]) != sheet.count * 48 for name, sheet in sheets.items()):
        raise ValueError("The tile converter returned an incomplete atlas")
    tiles, targets = raw[BASE], raw[TARGETS]
    mount = tiles[SCENERY_MOUNT * 48:(SCENERY_MOUNT + 1) * 48]
    blasts = bytearray(targets[4 * 48:])
    for i, attribute in enumerate(blasts):
        for mask in (0x07, 0x38):
            if (attribute & mask) == 0:
                blasts[i] |= mount[i % len(mount)] & mask
    raw[BASE] = tiles[:BLAST_TILE * 48] + blasts + targets[:4 * 48]
    # Retain the first level as a static atlas for the archived prototype probes.
    for number, (_, resident) in enumerate(levels, 1):
        atlas = bytearray(128 * 48)
        for slot, (name, idx) in resident.items():
            atlas[slot * 48:(slot+1) * 48] = raw[name][idx * 48:(idx+1) * 48]
        (gfx / f"level-{number}.bin").write_bytes(atlas)
    shutil.copyfile(gfx / "level-1.bin", gfx / "tileSet.png.bin")
    pack_tiles(output.resolve(), levels, sheets, raw, ZX0 / "zx0.exe", run)
    flight_sprites = set()
    if sprite_dir is None:
        sprite_dir = ART / "sprites"
        sprites = {**SPRITES, "enemy_yellow_z": "yellow_art.bin"}
        extra = {"enemy_" + ship.name for ship in FLIERS}
        sprites.update({name: f"{name}.bin" for name in sorted(extra)})
        flight_sprites = {"enemy_green_sine", "enemy_yellow_z"} | extra
    else:
        sprites = SPRITES
    for name, filename in sprites.items():
        target = output / filename
        sources = [sprite_dir / f"{name}.png"]
        if name in flight_sprites:
            sources.extend(sprite_dir / f"{name}_{n}.png" for n in (2, 3, 4))
        packed = bytearray()
        for source in sources:
            data = convert_image(source, "converter-sprites.exe", target, (5, 5))
            if len(data) != 60:
                raise ValueError(f"The sprite converter produced an unexpected size for {source}")
            if name == "player":
                (output / "hud_life_icon.bin").write_bytes(hud_life_icon(data))
            # The live compositor preserves the destination's bright/flash bits.
            packed.extend(value | 192 if index % 2 == 0 else value & 63
                          for index, value in enumerate(data))
            if name in flight_sprites:
                packed.extend(bytes(4))  # Four 64-byte poses fit one Z80 page.
        target.write_bytes(packed)
    if flight_sprites:
        pack_catalog(output, ZX0 / "zx0.exe", run)
    maps = output / "maps"
    maps.mkdir(exist_ok=True)
    level_targets = bytearray()
    for number, (data, _) in enumerate(levels, 1):
        unpacked = maps / f"{map_output(number)}.bin"
        unpacked.write_bytes(data)
        level_targets.append(max(data) >= DESTRUCTIBLE_TILE)
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
