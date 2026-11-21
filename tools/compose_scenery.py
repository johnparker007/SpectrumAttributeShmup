"""Recreate the nine Blokius scenery maps. Normal TAP builds use the edited TMX files."""

import argparse
from pathlib import Path
from xml.etree import ElementTree as ET

from build_art import LEVEL_MAPS

SKY, PLATE, VENT, RAM = 0, 1, 2, 3
TRUSS, MAST, BRACE, JOINT = 16, 17, 18, 19
PIPE, RISER, HATCH, GRILLE = 20, 21, 26, 27
# Internal IDs 124–127 export as the four marked tiles on the target sheet.
CRATE, CELL, FUSE, GEM = range(124, 128)
FAN = ((12, 13), (28, 29))
DISH = ((36, 37, 38), (52, 53, 54))
TANK = ((39, 40), (55, 56))
RADIATOR = ((41, 42, 43), (57, 58, 59))
COIL = ((96, 97, 98, 99), (112, 113, 114, 115))


class Section:
    """A composition of two screen widths. Coordinates follow the direction of flight."""

    def __init__(self):
        self.rows = [[SKY] * 16 for _ in range(6)]

    def put(self, x, y, *tiles):
        assert 0 <= x <= 16 - len(tiles) and 0 <= y < 6
        self.rows[y][x:x + len(tiles)] = tiles

    def stamp(self, x, y, motif):
        for dy, row in enumerate(motif):
            self.put(x, y + dy, *row)

    def rock(self, x, y, widths):
        cells = {(x + dx, y + dy) for dy, (offset, length) in enumerate(widths)
                 for dx in range(offset, offset+length)}
        for xx, yy in cells:
            edges = sum(1 << side for side, (dx, dy) in enumerate(((0,-1),(1,0),(0,1),(-1,0)))
                        if (xx + dx, yy + dy) not in cells)
            tile = 80 + edges if edges else (80, 109, 110, 111)[(xx + 3*yy) % 4]
            self.put(xx, yy, tile)

    def deck(self, x, y, width, height):
        for dy in range(height):
            self.put(x, y + dy, *([PLATE]*width))
        self.put(x, y, 48)
        self.put(x+width-1, y, 49)
        self.put(x, y+height-1, 50)
        self.put(x+width-1, y+height-1, 51)


def harbour(section, variant):
    # Sealed pressure vessels and jointed docking arms against open space.
    y = (1, 2, 3, 1)[variant]
    section.stamp(2, y, TANK)
    section.put(4, y + 1, JOINT, TRUSS, TRUSS, TRUSS, JOINT)
    section.stamp(9, y, TANK)
    section.put(7, y, 100)
    section.put(12, 0 if variant % 2 else 5, TRUSS, TRUSS, JOINT)
    section.put(14, 1 if variant % 2 else 4, 100)


def reef(section, variant):
    # Two eroded faces form an open channel for the star layers.
    x = (0, 2, 4, 1)[variant]
    section.rock(x, 0, [(0, 8), (1, 7), (3, 4)] if variant != 2 else [(0, 9), (2, 6)])
    section.rock(6 - x, 3, [(4, 3), (2, 7), (0, 10)])
    # The erosion at the top of the ridge leaves room for a broad impact basin.
    if variant != 2:
        section.stamp(x + 3, 0, ((105, 106), (107, 108)))
    section.put(10 - x, 4, 32)
    if variant == 3:
        section.stamp(12, 1, DISH)


def pumps(section, variant):
    y = (1, 2, 0, 3)[variant]
    section.deck(1, y, 12, 3)
    section.stamp(2, y, FAN)
    section.put(4, y + 1, PIPE, PIPE, RAM, PLATE, FUSE)
    section.stamp(9, y, TANK)
    section.put(6, y + 2, GRILLE)
    section.put(11, y + 1, VENT)


def radiator(section, variant):
    y = (1, 3, 0, 2)[variant]
    for x in (1, 5, 9):
        section.stamp(x, y, RADIATOR)
    section.put(4, y + 1, JOINT)
    section.put(8, y + 1, JOINT)
    if y<=2:
        section.put(5, y + 2, MAST)
        section.put(5, y + 3, JOINT, TRUSS, JOINT)
    else:
        section.put(9, y - 1, RISER)
        section.put(8, y - 2, TRUSS, JOINT, 100)


def antenna(section, variant):
    y = (1, 0, 2, 1)[variant]
    section.stamp(1, y, DISH)
    section.put(2, y + 2, MAST)
    section.put(2, y + 3, JOINT, TRUSS, TRUSS, TRUSS, TRUSS, TRUSS, JOINT)
    section.put(8, y + 2, 100)
    section.put(7, y + 1, 100, JOINT)
    if variant % 2:
        section.stamp(10, 0, DISH)
    else:
        section.stamp(11, 4, COIL)


def furnace(section, variant):
    y = variant % 3
    section.deck(0, y, 9, 4)
    section.stamp(1, y + 1, FAN)
    section.stamp(5, y + 1, FAN)
    section.put(3, y + 2, PIPE, RAM)
    section.put(3, y + 1, PLATE, CELL)
    section.put(3, y + 3, 103, GRILLE, 103)
    section.put(8, y + 1, JOINT, TRUSS, TRUSS)
    section.stamp(11, y, TANK)
    section.put(12, y + 2, JOINT)


def cargo(section, variant):
    # Racks of individually shootable cargo with open firing lanes.
    y = variant % 2
    for x in (0, 7):
        section.deck(x, y, 6, 4)
        section.put(x + 1, y + 1, PLATE, CRATE, CELL, GRILLE)
        section.put(x + 1, y + 2, VENT, FUSE, GEM, PLATE)
    section.put(6, y + 2, PIPE)
    if variant >= 2:
        section.put(12, 5, TRUSS, JOINT, 100)


def accelerator(section, variant):
    y = (0, 3, 1, 2)[variant]
    section.stamp(1, y, COIL)
    section.stamp(7, y, COIL)
    section.put(5, y + 1, PIPE, JOINT)
    section.put(11, y + 1, JOINT, PIPE, PIPE, 102)
    section.put(6, y, 100)
    if variant % 2:
        section.stamp(11, 0, RADIATOR)
    else:
        section.put(3, 4, 100, SKY, 100, SKY, 100)
        section.put(3, 5, JOINT, PIPE, 102, PIPE, JOINT)


def gate(section, variant):
    # Two cantilevered decks around a tall central aperture.
    section.deck(1, 0, 10, 2)
    section.deck(3, 4, 11, 2)
    section.put(3, 0, VENT, 103, 103, 103, GRILLE)
    section.put(5, 5, GRILLE, 103, 103, 103, HATCH)
    section.put(2, 2, MAST)
    section.put(2, 3, JOINT, TRUSS)
    section.put(9, 1, RAM)
    section.put(10, 3, 100)
    if variant >= 2:
        section.stamp(12, 1, FAN)
    else:
        section.put(11, 0, TRUSS, TRUSS, JOINT)


def island(section, variant):
    x = (0, 3, 5, 1)[variant]
    y = variant % 3
    section.rock(x, y, [(3, 4), (1, 8), (0, 9), (2, 5)])
    section.deck(x + 2, y, 5, 3)
    section.put(x + 3, y + 1, HATCH, CELL, GRILLE)
    if variant % 2:
        section.put(x + 4, y + 2, RAM)
    if x<4:
        section.put(12, 4, 34, 35)
        section.put(12, 5, 35, 34)


def buoy(section, variant):
    # Sparse interludes leave entire viewports open to both star layers.
    x = (1, 11, 4, 9)[variant]
    y = (1, 4, 3, 0)[variant]
    section.put(x, y, 100)
    section.put(x, y + 1, JOINT, TRUSS, 100)


def hangar(section, variant):
    # Edge-to-edge deck joins the next bay at either height. The rectangular
    # openings are actual sky; the red fixtures sit in intact armour.
    y = variant % 2
    section.deck(0, y, 16, 5)
    section.put(0, y + 1, GRILLE, PLATE, PLATE, CRATE, PLATE, VENT)
    section.put(1, y + 3, VENT, PLATE, GEM, PLATE, HATCH)
    for x, width in ((6,3),(12,2)):
        section.put(x, y + 1, *[SKY] * width)
        section.put(x, y + 2, *[SKY] * width)
        section.put(x, y + 3, *[103] * width)
    section.put(10, y + 2, CELL)
    section.put(0, y + 4, 103, 103, 103)


BUILDERS = {'H': harbour, 'R': reef, 'P': pumps, 'D': radiator, 'A': antenna,
            'M': furnace, 'C': cargo, 'F': accelerator, 'G': gate, 'I': island,
            'B': hangar, '.': buoy}
# Each letter is a composed two-screen section; successive visits change its elevation.
ROUTES = (
    ('Mooring Chain',  'H.BBD.HIPH.ADH.H'),
    ('Basalt Passage', 'RIR.RIBB.RIRP.RI'),
    ('Pressure Works', 'P.HPPM.BBHPM.PHP'),
    ('Shattered Belt', 'I.RIA.IR.RIHI.RI'),
    ('Radiator Wings', 'DD.HDF.BBD.DHDF.'),
    ('Listening Posts','A.AHDA.IAAB.BDA.'),
    ('Induction Line', 'F.DFMFP.BBDF.GFM'),
    ('Salvage Yard',   'CCH.BMPCC.DBHCCG'),
    ('Reactor Gates',  'GFMG.BBCFGM.GFCG'),
)

THEMES = ("frontier", "relay", "reactor")
THEME_TILE = 135  # Follows the 128 common tiles and seven fixture/effect tiles.
# Keep the original firing lanes and target clusters in place. These sections
# have room for new structures between the inhabited decks.
LANDMARK_PARTS = (
    (0, 4, 6, 9, 12, 15), (0, 2, 4, 9, 11, 14), (1, 2, 6, 9, 12, 14),
    (2, 4, 7, 9, 11, 14), (0, 3, 5, 9, 12, 14), (0, 3, 5, 8, 13, 14),
    (0, 3, 5, 10, 13, 14), (2, 3, 9, 10, 12, 15), (0, 3, 8, 9, 12, 15),
)


def landmark(section, sector, variant):
    """Build silhouettes at two-screen scale from the sector's 32×16 and 16×16 art."""
    first = THEME_TILE + sector % 3 * 24

    def machine(x, y, offset, width):
        section.stamp(x, y, tuple(tuple(first + offset + 12*row + i for i in range(width))
                                  for row in range(2)))

    if sector in (1, 3):  # Fossils and ore seams grow out of a broken shelf.
        flip = variant % 2
        y = 1 if flip else 3
        section.rock(0, 0 if flip else 3, [(1, 5), (0, 7), (0, 6)])
        machine(1, y, 0, 4)
        machine(9, 3-y//2, 4, 4)
        machine(13, 0 if flip else 4, 8, 2)
    elif sector in (4, 5, 6):  # Solar wings, receivers and accelerator girders.
        y = 1 if variant % 2 else 3
        section.put(1, y+1, *([TRUSS]*14))
        machine(1, y-1, 0, 4)
        machine(9, y-1, 4, 4)
        machine(5 if variant % 2 else 13, y, 8, 2)
        section.put(5, y+1, JOINT, THEME_TILE+72, JOINT)
    else:  # Service bays. Hull-mounted targets sit between the machinery.
        y = (1, 0, 3, 2)[variant]
        section.deck(0, y, 15, 3)
        machine(1, y, 0 if variant % 2 == 0 else 4, 4)
        machine(8, y, 4 if variant % 2 == 0 else 0, 4)
        machine(13, y, 8, 2)
        section.put(5, y+1, first+11, PLATE, THEME_TILE+72)
        section.put(3, y+2, first+22, PIPE, first+23)


def dress_section(section, sector, part):
    first = THEME_TILE + sector % 3 * 24
    for y, row in enumerate(section.rows):
        for x, tile in enumerate(row):
            if tile == RAM:
                row[x] = THEME_TILE + 72
            elif tile == PLATE and (x + 2*y + part) % 5 == 0:
                row[x] = first + 10
            elif tile in (VENT, GRILLE, HATCH):
                row[x] = first + {VENT: 11, GRILLE: 22, HATCH: 23}[tile]


def place_bonus_targets(rows, sector):
    """One A per 32 columns, with time to line up the opening shot."""
    for district in range(8):
        start = district * 32
        centre = start + 16
        lane = 1 + (sector + 3 * district) % 4
        mounts = [(x, y) for x in range(start + 4, start + 29) for y in range(6)
                  if rows[y][x] in (PLATE, CRATE)]
        if mounts:
            x, y = min(mounts, key=lambda p: abs(p[0]-centre) + 2*abs(p[1]-lane))
        else:
            # The antenna and radiator stretches occasionally need a small service deck.
            bays = [(x, y) for x in range(start + 5, start + 28) for y in range(1, 5)
                    if rows[y][x-1:x+2] == [SKY]*3]
            x, y = min(bays, key=lambda p: abs(p[0]-centre) + 2*abs(p[1]-lane))
            rows[y][x-1:x+2] = [PLATE, PLATE, PLATE]
        for row in rows:
            for col in range(start, start + 32):
                if row[col] == CRATE:
                    row[col] = FUSE
        rows[y][x] = CRATE


def build_maps(directory):
    directory.mkdir(exist_ok=True, parents=True)
    for n, (name, route) in enumerate(ROUTES):
        assert len(route) == 16
        rows = [[] for _ in range(6)]
        visits = {}
        for part, key in enumerate(route):
            section = Section()
            variant = visits.get(key, n) % 4
            if part in LANDMARK_PARTS[n]:
                landmark(section, n, (LANDMARK_PARTS[n].index(part) + n) % 4)
            else:
                BUILDERS[key](section, variant)
                if n == 7 and key == "C":
                    # Hang the grapple and scrapped hull above/below the cargo rows.
                    y = 0 if variant % 2 else 4
                    for start, offset in ((1, 24), (9, 28)):
                        for dy in range(2):
                            section.put(start, y+dy, *(THEME_TILE+offset+12*dy+i for i in range(4)))
            dress_section(section, n, part)
            visits[key] = variant + 1
            for row, part in zip(rows, section.rows):
                row.extend(part)
        place_bonus_targets(rows, n)
        xml = ET.Element(
            "map", version="1.10", tiledversion="1.10.0", orientation="orthogonal",
            renderorder="right-down", width="256", height="6", tilewidth="8", tileheight="8",
            infinite="0", nextlayerid="2", nextobjectid="1",
        )
        ET.SubElement(xml, "tileset", firstgid="1", source="tileSet.tsx")
        ET.SubElement(xml, "tileset", firstgid="129", source="destructible.tsx")
        ET.SubElement(xml, "tileset", firstgid=str(THEME_TILE+1), source=THEMES[n//3]+".tsx")
        layer = ET.SubElement(xml, "layer", id="1", name=name, width="256", height="6")
        data = ET.SubElement(layer, "data", encoding="csv")
        gids = [[129 + tile - CRATE if CRATE <= tile <= GEM else 1 + tile for tile in row] for row in rows]
        data.text = "\n" + ",\n".join(",".join(map(str, row)) for row in gids) + "\n"
        ET.indent(xml, space=" ")
        contents = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        (directory / LEVEL_MAPS[n]).write_bytes(contents + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Output directory (art/maps replaces the editable masters)")
    build_maps(parser.parse_args().directory)
