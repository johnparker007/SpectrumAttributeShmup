"""Build and check the bounded moving-projectile fixture used by the renderer test."""

from dataclasses import dataclass

from benchmark_motion import STEPS, step
from profile_ringo8 import HIT
from trace_zesarux import breakpoint_log, read_symbols


ENEMY_BOXES = [(17 + (7 * i) % 42, (11 * i + 6) % 44) for i in range(15)]
PLAYER_BOX = (35, 17)


@dataclass
class Phase:
    state: bytes
    hits: bytes
    dots: dict


def hit(box, shots, width):
    x, y = box
    return 255 * any(x <= sx + width - 1 and sx < x + 5 and y <= sy < y + 5 for sx, sy in shots)


def phases():
    enemies = [(33 + (7 * i) % 31, (33 if min(STEPS[i % 8]) < 0 else 12) + i // 8, 8 * (i % 8) + i // 8)
               for i in range(32)]
    volleys = [(6, 12, 0), (23, 24, 0), (40, 36, 0)]
    result = []
    for _ in range(16):
        enemies, volleys, shots = step(enemies, volleys)
        incoming = [(x, y) for x, y, _ in enemies]
        dots = {(x + dx, y): 5 for x, y in shots for dx in (0, 1)}
        dots.update({point: 6 for point in incoming})
        if any(not (0 <= x < 64 and 0 <= y < 48) for x, y in dots):
            raise ValueError("Moving integration fixture must keep every slot active")
        state = bytes(value for record in (*enemies, *volleys, *shots) for value in record)
        hits = bytes([hit(box, shots, 2) for box in ENEMY_BOXES] + [hit(PLAYER_BOX, incoming, 1)])
        result.append(Phase(state, hits, dots))
    if len({phase.hits for phase in result}) < 3:
        raise ValueError("Moving integration needs time-varying collision outcomes")
    return result


def prepare(directory):
    (directory / "motion_seed.bin").write_bytes(phases()[0].state)
    (directory / "trajectories.bin").write_bytes(bytes(delta % 256 for path in STEPS for delta in path))


def verify_state(emulator, sample, model, scenario):
    symbols = read_symbols(sample / "main.sym")
    end = symbols["overlayEnd"]
    expressions = [f"PEEK({symbols['motion_phase']:04X}H)"]
    sizes = [1]
    for label, size in (("enemy_records", len(scenario[0].state)), ("collision_actual", len(scenario[0].hits))):
        for offset in range(0, size, 2):
            length = min(2, size - offset)
            function = "PEEKW" if length == 2 else "PEEK"
            expressions.append(f"{function}({symbols[label] + offset:04X}H)")
            sizes.append(length)
    points = [(f"PC={end:04X}H AND {n}={n}", expression) for n, expression in enumerate(expressions, 1)]
    log = breakpoint_log(emulator, sample / "main.tap", model, 22, points, fast_autoload=True)
    hits = HIT.findall(log)
    if not hits or log.count("Catch breakpoint:") != len(hits):
        raise ValueError(f"{model}: missing moving state debugger output")
    width = len(points)
    visited = set()
    for index in range(0, len(hits) - width + 1, width):
        group = hits[index:index + width]
        if [cond for cond, _ in group] != [cond for cond, _ in points]:
            raise ValueError(f"{model}: moving state breakpoints are out of order")
        phase = int(group[0][1])
        data = b"".join(int(value).to_bytes(size, "little") for (_, value), size in zip(group[1:], sizes[1:]))
        if not 0 <= phase < len(scenario) or data != scenario[phase].state + scenario[phase].hits:
            raise ValueError(f"{model}: projectile state or hit flags differ at phase {phase}")
        visited.add(phase)
    if len(visited) != len(scenario):
        raise ValueError(f"{model}: moving state test covered only {len(visited)} phases")
    return len(visited)
