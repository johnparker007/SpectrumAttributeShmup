"""Check the emitted logo program at individual ULA attribute fetches."""

from struct import unpack_from

from menu_luminance import ATTRS, LINE_TSTATES, LUMINANCE_BANDS, PROFILES, PUSH, visible_cells


# First attribute fetch at the logo, including its eight-line and two-cell inset.
# https://github.com/redcode/ZXSpectrum/wiki/2A-3-Floating-Bus-Test
FIRST_FETCH = {"128k": 16197, "plus": 16200}


def attribute_stores(program, phase, time, model):
    origin, waits, _ = PROFILES[model]
    palette = {opcode: bytes(LUMINANCE_BANDS[2 * pair:2 * pair + 2])
               for opcode, pair in zip(PUSH, ((i + 3 * (phase // 6)) % 6 for i in range(6)))}
    sp = 0
    pc = 0
    while program[pc] != 0xC3:  # Jump back to the fixed-bank menu code.
        opcode = program[pc]
        if opcode == 0x31:
            sp = unpack_from("<H", program, pc + 1)[0]
            pc += 3
            time += 10
        elif opcode == 0x00:
            pc += 1
            time += 4
        elif opcode == 0x18 and program[pc + 1] == 0:
            pc += 2
            time += 12
        elif opcode in (0x33, 0x3B):
            sp += 1 if opcode == 0x33 else -1
            pc += 1
            time += 6
        else:
            size = 2 if opcode in (0xDD, 0xFD) else 1
            pair = palette[program[pc:pc + size]]
            pc += size
            time += 5 + 4 * (size - 1)
            for ink in reversed(pair):
                slot = (time - origin) % LINE_TSTATES
                time += 3 + (waits[slot % 8] if slot < 128 else 0)
                sp -= 1
                yield time, sp, ink


def verify_luminance_writes(gfx, bitmap):
    cells = [sorted(row) for row in visible_cells(bitmap)]
    for model, first_fetch in FIRST_FETCH.items():
        bundle = (gfx / f"luminance-{model}.bin").read_bytes()
        frames = []
        for phase in range(len(LUMINANCE_BANDS)):
            offset = unpack_from("<H", bundle, 2 * (phase % 6))[0]
            length, seed_offset = unpack_from("<HH", bundle, offset)
            start = offset + 4
            seed = bundle[start + seed_offset:start + length]
            raster = bundle[start:start + seed_offset]
            frames.append((list(attribute_stores(seed, phase, 0, model)),
                           list(attribute_stores(raster, phase, PROFILES[model][2], model))))

        for phase, (seed, raster) in enumerate(frames):
            # Begin with the preceding frame's final attributes, then preseed.
            previous_seed, previous_raster = frames[phase - 1]
            attributes = {address: ink for _, address, ink in previous_seed + previous_raster + seed}
            pending = iter(raster)
            store = next(pending, None)
            for y, row in enumerate(cells):
                for x in row:
                    fetch = first_fetch + y * LINE_TSTATES + (x // 2) * 8 + (x % 2) * 2
                    while store and store[0] <= fetch:
                        _, address, ink = store
                        attributes[address] = ink
                        store = next(pending, None)
                    expected = LUMINANCE_BANDS[(phase + y + x) % len(LUMINANCE_BANDS)]
                    if attributes.get(ATTRS + 32 * (y // 8) + x) != expected:
                        raise ValueError(f"{model}: wrong ink at ULA fetch, phase {phase}, row {y}, column {x}")
