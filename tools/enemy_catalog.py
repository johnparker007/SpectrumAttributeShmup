"""Authoring data for seven-ship waves. All curves and gun gates bake off-machine."""

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class Flier:
    name: str
    heights: tuple[int, ...]  # inward displacement across the screen, from entry to exit
    smooth: bool
    lanes: tuple[int, ...]    # top-left Y, seven ships in spawn order
    dashes: tuple[tuple[int, int], ...]  # inclusive X windows for double steps
    spacing: int
    guns: tuple[tuple[int, int | None], ...]  # (X, bearing), in unlock order


# Every formation covers the playfield. Order matters when the player camps a lane.
RANK = (1, 7, 14, 21, 28, 35, 41)
INTERLEAVE = (3, 27, 10, 39, 17, 32, 22)
PINCER = (1, 40, 7, 34, 13, 28, 20)
FAN = (20, 8, 33, 2, 39, 14, 27)
AIM = None
# Bearings count upwards from left. Fixed angles reflect with the flight path.
FLIERS = (
    Flier("cobalt_skimmer", (0, 0), False, RANK, (), 8,
          ((44, AIM), (24, AIM), (58, AIM), (33, 0), (62, AIM), (15, 0))),
    Flier("scarlet_hook", (0, 0, 0, 2, 13, 20, 16, 6, 5), True, PINCER, ((24, 39),), 9,
          ((39, AIM), (54, AIM), (22, 2), (61, AIM), (34, 30), (17, AIM))),
    Flier("ivory_stair", (0, 0, 0, 7, 7, 7, 14, 14, 14, 20, 20), False, INTERLEAVE, (), 8,
          ((47, AIM), (32, 0), (57, AIM), (23, AIM), (62, AIM), (15, 0))),
    Flier("amber_kite", (0, 0, 8, 19, 9, 0, 10, 20, 8), False, FAN, ((29, 42),), 8,
          ((45, AIM), (30, 29), (58, AIM), (18, 3), (62, AIM), (38, AIM))),
    Flier("violet_needle", (0, 0, 0, 0, 0, 13, 19, 19, 19), False, RANK, ((23, 49),), 7,
          ((51, AIM), (30, AIM), (59, AIM), (22, 0), (63, AIM), (41, 0))),
    Flier("mint_manta", (0, 3, 12, 15, 8, 2, 9, 17, 10), True, INTERLEAVE, (), 9,
          ((42, AIM), (54, 31), (60, AIM), (32, 1), (24, AIM), (16, AIM))),
    Flier("copper_drill", (0, 0, 12, 2, 14, 3, 15, 4, 13, 2), False, PINCER, ((15, 30),), 7,
          ((49, AIM), (40, 2), (58, AIM), (26, 30), (63, AIM), (35, AIM))),
    Flier("azure_hopper", (0, 0, 1, 17, 2, 1, 1, 20, 2, 0), True, INTERLEAVE, ((37, 52), (9, 20)), 8,
          ((46, AIM), (33, AIM), (57, AIM), (24, 3), (62, AIM), (39, 29))),
    Flier("rose_claw", (0, 0, 12, 19, 20, 18, 6, 1), True, FAN, ((19, 33),), 8,
          ((45, AIM), (35, 3), (58, AIM), (24, AIM), (62, AIM), (51, 29))),
    Flier("jade_pendulum", (0, 3, 12, 20, 17, 7, 0, 4, 13), True, PINCER, (), 8,
          ((50, AIM), (37, 2), (58, AIM), (27, 30), (63, AIM), (44, AIM))),
    Flier("silver_splitter", (0, 0, 0, 0, 1, 8, 16, 16, 16), False, RANK, ((23, 34),), 7,
          ((52, AIM), (46, AIM), (58, 30), (29, 2), (63, AIM), (40, AIM))),
    Flier("crimson_comet", (0, 0, 4, 9, 14, 19, 19, 19, 19), False, PINCER, ((12, 53),), 7,
          ((48, AIM), (33, AIM), (58, AIM), (20, 0), (63, AIM), (42, 0))),
    Flier("polar_wraith", (0, 0, 13, 13, 4, 4, 17, 17, 9), True, INTERLEAVE, ((39, 51), (12, 25)), 7,
          ((51, AIM), (35, 3), (59, AIM), (25, AIM), (63, AIM), (45, 29))),
    Flier("ruby_crown", (0, 0, 16, 6, 20, 4, 18, 0, 9), False, FAN, ((33, 46),), 8,
          ((53, AIM), (38, 29), (59, AIM), (27, 3), (63, AIM), (46, AIM))),
)
NAMES = ("green_sine", "yellow_z", *(ship.name for ship in FLIERS))
ROSTERS = (
    (0,), (0, 1, 2, 3), (0, 1, 2, 3, 4, 5), (0, 1, 4, 5, 6, 7), (0, 1, 6, 7, 8, 9),
    (0, 1, 8, 9, 10, 11), (0, 1, 8, 10, 11, 12, 13),
    (0, 1, 10, 11, 12, 13, 14, 15), (0, 1, 9, 11, 12, 13, 14, 15),
)
MAX_RESIDENT = 8  # One 256-byte art page per resident species in bank 0.


# The on-screen path ends at sample 135. Negative X uses samples 248..255.
BEARINGS = 142
ENTRIES = 148
GATES = 162


def flight_steps(ship):
    """Yield the sampled X, landing X and inward displacement after each step."""
    x = 67
    while x > -4:
        sample = x - 1
        dash = any(left <= sample <= right for left, right in ship.dashes)
        x = sample - 1 if dash else sample
        t = (67 - x) * (len(ship.heights) - 1) / 71
        i = min(floor(t), len(ship.heights) - 2)
        f = t - i
        if ship.smooth:
            f = f * f * (3 - 2 * f)
        yield sample, x, round(ship.heights[i] + f * (ship.heights[i + 1] - ship.heights[i]))


def spawn_lane(ship, member, reflected):
    y = ship.lanes[member]
    inward_up = y > 20
    return (41 - y, not inward_up) if reflected else (y, inward_up)


def path_bytes(ship):
    """Bake movement, entry rows and all gun positions into one resident page."""
    data = bytearray(256)
    samples = {}
    previous_y = 0
    for sample, x, y in flight_steps(ship):
        dy = y - previous_y
        if abs(dy) >= 16:
            raise ValueError(f"{ship.name} moves too far vertically in one step")
        step = 32 if x != sample else 0
        index = 2 * (sample % 128)
        data[index:index + 2] = bytes((step + 16 + dy, step + 16 - dy))
        for crossed in range(x, sample + 1):
            samples[crossed] = index
        previous_y = y

    for member in range(7):
        for reflected in (0, 1):
            y, upward = spawn_lane(ship, member, reflected)
            data[ENTRIES + 2 * (6 - member) + reflected] = y + 128 * upward

    bearings = list(dict.fromkeys(bearing for _, bearing in ship.guns))
    if len(bearings) > 3 or len({samples[x] for x, _ in ship.guns}) != len(ship.guns):
        raise ValueError(f"{ship.name} needs distinct gun positions and at most three bearings")
    for gun, bearing in enumerate(bearings):
        data[BEARINGS + gun * 2:BEARINGS + gun * 2 + 2] = (
            (1, 1) if bearing is AIM else (bearing * 8, (-bearing % 32) * 8))
    for n, (x, bearing) in enumerate(ship.guns):
        data[GATES + 2 * n:GATES + 2 * n + 2] = (samples[x], (1 + bearings.index(bearing)) * 64)
    return data


def settings(level, species):
    if species < 2:
        return (9 if species == 0 else 4), ()
    ship = FLIERS[species - 2]
    counts = (0, 1, 2, 2, 3, 3, 4, 5, 6)
    gap = (0, 5, 4, 2, 1, 0, -1, -2, -3)
    return ship.spacing + gap[level - 1], ship.guns[:counts[level - 1]]


def pack_catalog(output, compressor, run):
    """Store each four-frame sheet once, alongside its optional flight curve."""
    resource_lines = []
    manifests = [
        f"CATALOG_BEARINGS equ {BEARINGS}",
        f"CATALOG_ENTRIES equ {ENTRIES}",
        f"CATALOG_GATES equ {GATES}",
        "enemyManifests: dw " + ",".join(f"enemyLevel{n}" for n in range(1, len(ROSTERS) + 1)),
    ]
    for i, name in enumerate(NAMES):
        art = ("enemy_art", "yellow_art")[i] if i < 2 else f"enemy_{name}"
        data = (output / (art + ".bin")).read_bytes()
        if len(data) != 256:
            raise ValueError(f"{name} must have four 64-byte flight poses")
        if i >= 2:
            ship = FLIERS[i - 2]
            columns = [x for x, bearing in ship.guns]
            if (len(columns) > 6 or len(set(columns)) != len(columns)
                    or any(x < 0 or x >= 64 for x in columns)
                    or any(d is not None and not 0 <= d < 32 for _, d in ship.guns)
                    or len(ship.lanes) != 7 or len(set(ship.lanes)) != 7 or ship.heights[0] != 0
                    or any(not 0 <= left <= right <= 63 for left, right in ship.dashes)
                    or any(not 0 <= y + (-h if y > 20 else h) <= 41
                           for y in ship.lanes for h in ship.heights)):
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
            manifests.append(f"    db {wait},{len(guns)}")
    (output / "enemy_packets.a80").write_text("\n".join(resource_lines)+"\n", encoding="ascii")
    (output / "enemy_manifests.a80").write_text("\n".join(manifests)+"\n", encoding="ascii")
