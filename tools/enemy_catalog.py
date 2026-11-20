"""Authoring data for seven-ship waves. All curves and gun gates bake off-machine."""

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class Flier:
    name: str
    heights: tuple[int, ...]  # top-left Y, from entry to exit at equal distances
    smooth: bool
    spacing: int     # relative spacing before the level adjustment
    guns: tuple[tuple[int, int | None], ...]  # (X, bearing), or None for aimed fire


# Bearings use 32 compass steps. Zero points left, positive steps turn upwards.
FLIERS = (
    Flier("cobalt_skimmer", (32, 32, 31, 27, 21, 18, 18, 18, 18), True, 9, ((40, 0), (26, None), (53, 2))),
    Flier("scarlet_hook", (5, 5, 5, 9, 26, 35, 23, 18, 18), True, 10, ((30, None), (46, 29), (19, 2))),
    Flier("ivory_stair", (8, 8, 8, 16, 16, 24, 24, 32, 32, 32), False, 9, ((47, 30), (30, 0), (14, 2))),
    Flier("amber_kite", (20, 8, 2, 8, 20, 32, 39, 32, 20), False, 9, ((43, 28), (21, None), (55, 3))),
    Flier("violet_needle", (35, 35, 35, 34, 29, 17, 5, 5, 5), False, 8, ((48, 0), (27, 3), (18, None))),
    Flier("mint_manta", (12, 8, 12, 23, 29, 27, 17, 12, 15), True, 10, ((44, None), (32, 31), (20, 1))),
    Flier("copper_drill", (19, 13, 24, 13, 24, 13, 24, 13, 20), False, 8, ((48, 2), (42, 30), (23, 0))),
    Flier("azure_hopper", (34, 34, 17, 34, 34, 8, 34, 34, 23), True, 9, ((47, 3), (23, 3), (15, None))),
    Flier("rose_claw", (4, 10, 21, 28, 28, 25, 12, 6, 4), True, 9, ((38, 0), (31, None), (17, 29))),
    Flier("jade_pendulum", (20, 37, 40, 32, 15, 3, 2, 9, 20), True, 10, ((51, 2), (26, 30), (15, None))),
    Flier("silver_splitter", (20, 20, 20, 19, 9, 4, 4, 9, 17), True, 8, ((48, 30), (44, 2), (28, None))),
    Flier("crimson_comet", (2, 4, 9, 17, 27, 37, 39, 39, 39), False, 7, ((50, None), (36, 30), (19, 0))),
    Flier("polar_wraith", (33, 27, 12, 12, 21, 20, 6, 4, 12), True, 8, ((51, 3), (36, None), (22, 29))),
    Flier("ruby_crown", (19, 8, 23, 34, 21, 10, 23, 34, 20), True, 9, ((52, None), (38, 29), (24, 3))),
)
NAMES = ("green_sine", "yellow_z", *(ship.name for ship in FLIERS))
ROSTERS = (
    (0,), (0, 1, 2, 3), (0, 1, 2, 3, 4, 5), (0, 1, 4, 5, 6, 7), (0, 1, 6, 7, 8, 9),
    (0, 1, 8, 9, 10, 11), (0, 1, 8, 10, 11, 12, 13),
    (0, 1, 10, 11, 12, 13, 14, 15), (0, 1, 9, 11, 12, 13, 14, 15),
)
MAX_RESIDENT = 8  # One 256-byte art page per resident species in bank 0.


def path_bytes(ship):
    """Interleave the upper/lower entrances so a single Z80 rotate selects one."""
    data = bytearray(256)
    for x in range(-4, 68):
        t = (67 - x) * (len(ship.heights) - 1) / 71
        i = min(floor(t), len(ship.heights) - 2)
        f = t - i
        if ship.smooth:
            f = f * f * (3 - 2 * f)
        y = round(ship.heights[i] + f * (ship.heights[i + 1] - ship.heights[i]))
        pos = 2 * (x % 128)
        data[pos:pos + 2] = bytes((y, 41 - y))
    return data


def settings(level, species):
    if species < 2:
        return (9 if species == 0 else 4), ()
    ship = FLIERS[species - 2]
    debut = next(i for i, roster in enumerate(ROSTERS, 1) if species in roster)
    tier = min(2, level - debut + int(level >= 6))
    # Earlier introductions give one warning shot. Late veterans use all three
    # guns and close the gaps between ships. The level also sets bullet speed.
    return ship.spacing + 3 - tier, ship.guns[:1 + tier]


def pack_catalog(output, compressor, run):
    """Store each four-frame sheet once, alongside its optional flight curve."""
    resource_lines = []
    manifests = ["enemyManifests: dw " + ",".join(f"enemyLevel{n}" for n in range(1, len(ROSTERS) + 1))]
    for i, name in enumerate(NAMES):
        art = ("enemy_art", "yellow_art")[i] if i < 2 else f"enemy_{name}"
        data = (output / (art + ".bin")).read_bytes()
        if len(data) != 256:
            raise ValueError(f"{name} must have four 64-byte flight poses")
        if i >= 2:
            ship = FLIERS[i - 2]
            columns = [x for x, bearing in ship.guns]
            if (len(columns) > 3 or len(set(columns)) != len(columns)
                    or any(x < 0 or x >= 64 for x in columns)
                    or any(d is not None and not 0 <= d < 32 for _, d in ship.guns)
                    or any(y < 0 or y > 41 for y in ship.heights)):
                raise ValueError(f"Invalid flight path or firing positions for {name}")
            data += path_bytes(ship)
        raw = output / f"enemy_packet_{i}.bin"
        raw.write_bytes(data)
        run([compressor, "-f", raw.resolve(), raw.with_suffix(".zx0").resolve()], output)
        resource_lines.append(f'enemyPacket{i}: incbin "enemy_packet_{i}.zx0"')
    for level, roster in enumerate(ROSTERS, 1):
        if (not 1 <= len(roster) <= MAX_RESIDENT or len(set(roster)) != len(roster)
                or roster[:2] != (0, 1)[:len(roster)]):
            raise ValueError(f"Invalid enemy roster on level {level}")
        manifests.append(f"enemyLevel{level}: db {len(roster)}")
        for species in roster:
            wait, guns = settings(level, species)
            manifests.append(f"    dw enemyPacket{species}")
            # Each marked path sample carries a gun number. Store its bearing in
            # the unused offscreen part of the same page, separately for each mirror.
            record = [wait, len(guns)]
            for column, bearing in guns:
                record.extend((column * 2, 1 if bearing is None else bearing * 8,
                               1 if bearing is None else (-bearing % 32) * 8))
            manifests.append("    db " + ",".join(map(str, record)))
    (output / "enemy_packets.a80").write_text("\n".join(resource_lines)+"\n", encoding="ascii")
    (output / "enemy_manifests.a80").write_text("\n".join(manifests)+"\n", encoding="ascii")
