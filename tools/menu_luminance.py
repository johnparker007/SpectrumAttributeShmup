"""Compile the experimental 12-band logo into timed Z80 stack writes."""

from concurrent.futures import ProcessPoolExecutor
from functools import cache
from struct import pack


LUMINANCE_BANDS = bytes(range(0x41, 0x48)) + bytes(range(0x46, 0x41, -1))
WIDTH, HEIGHT = 28, 32
LINE_TSTATES = 228
ATTRS = 0x5822
EARLIEST_FETCH, LATEST_FETCH = 16191, 16198  # At the logo's left edge.
ATTRIBUTE_WRITE_DEADLINE = 16194  # Three T-states before the nominal 128K fetch.
RASTER_EXIT, SEED_EXIT = 0x8003, 0x8006
PROGRAM_BYTES = 960
RASTER_END = 23364
COPPER_BANDS = (0x01, 0x05, 0x05, 0x45, 0x47, 0x45, 0x05, 0x05)
COPPER_MENU_TEXT = {
    10: "      1-8  START LEVEL 1-8",
    16: ">K KEYBOARD     J KEMPSTON",
    18: " S SINCLAIR     R REDEFINE KEYS",
}
COPPER_CONTROL_MARKS = {16: {0, 15}, 18: {0}}
PROFILES = {
    # Contention start, wait pattern and calibrated first instruction T-state.
    "128k": (16185, (6, 5, 4, 3, 2, 1, 0, 0), 16110),
    "plus": (16189, (1, 0, 7, 6, 5, 4, 3, 2), 16109),
}
# BC, DE, HL, AF, IX, IY hold pairs 1, 2, 4, 5, 0, 3 respectively.
PUSH = (b"\xdd\xe5", b"\xc5", b"\xd5", b"\xfd\xe5", b"\xe5", b"\xf5")


def word(value):
    return pack("<H", value)


def load_sp(address):
    return b"\x31" + word(address)


def padding(cycles):
    # Short jumps and NOPs preserve the palette. INC SP can supply six cycles
    # at the end of a scanline where the next burst will reload SP.
    tail = b"\x33" if cycles % 4 == 2 else b""
    cycles -= 6 * len(tail)
    return b"\x18\x00" * (cycles // 12) + b"\x00" * (cycles % 12 // 4) + tail


def visible_cells(bitmap):
    for y in range(HEIGHT):
        start = ((y % 8) * (HEIGHT // 8) + y // 8) * WIDTH
        yield {x for x, bits in enumerate(bitmap[start:start + WIDTH]) if bits}


def attribute_write_end(time, origin, waits):
    slot = (time - origin) % LINE_TSTATES
    return time + 3 + (waits[slot % 8] if slot < 128 else 0)


def schedule(model, phase, visible, *, copper=False):
    """Find a scanline schedule whose writes straddle the ULA fetch window."""
    origin, waits, first = PROFILES[model]
    width = 32 if copper else WIDTH
    height = len(visible) - 1
    fetch_offset = -8 if copper else 0

    def parity(y):
        return 0 if copper else (y + phase) % 2

    @cache
    def columns(y, first_column, last_column):
        cells = visible[y] & set(range(first_column, last_column))
        if not cells:
            return ()
        if copper:
            return tuple(sorted({x & ~1 for x in cells}, reverse=True))
        high, low, p = max(cells), min(cells), parity(y)
        return tuple(range(high - (high - p) % 2, low - (low - p) % 2 - 1, -2))

    def cuts(y):
        # Seed the entire first scanline of each character row ahead of time.
        return (width + parity(y),) if y % 8 == 0 else range(parity(y) - 2, width + 2, 2)

    @cache
    def burst(y, pairs, t, early):
        for i, x in enumerate(pairs):
            if i and x != pairs[i - 1] - 2:
                t += 10  # Reload SP to skip a gap in the text.
            begin = t
            prefixed = not copper and len(PUSH[((x + y + phase) % 12) // 2]) == 2
            t += 5 + 4 * prefixed
            for cell in (x + 1, x):
                t = attribute_write_end(t, origin, waits)
                if cell in visible[y]:
                    # The ULA fetches two cells in an eight-T-state burst.
                    # Check each byte's completion, as well as the emulator's
                    # instruction-start fetch window.
                    deadline = ATTRIBUTE_WRITE_DEADLINE + fetch_offset + 4 * cell - 2 * (cell % 2)
                    if t > deadline + (0 if early else LINE_TSTATES):
                        return None
                    if early and begin > EARLIEST_FETCH + fetch_offset + 4 * cell:
                        return None
                if cell in visible[y - 1]:
                    previous_fetch = LATEST_FETCH + fetch_offset + 4 * cell - (LINE_TSTATES if early else 0)
                    if begin <= previous_fetch:
                        return None
        return t

    # The left-side burst paints the following scanline. The state holds its
    # cutover column, the next instruction time and the program to reach it.
    first_start, last_start = 16032, 16257
    states = {(cut, first): () for cut in cuts(0)}
    for y in range(height):
        following = {}
        for (cut, start), program in states.items():
            right = columns(y, cut, width)
            after_right = burst(y, right, start + 10, True) if right else start
            if after_right is None:
                continue
            if copper and y + 1 < height:
                after_right += 10  # LD HL sets the next scanline's uniform ink.
            for next_cut in cuts(y + 1):
                left = columns(y + 1, 0, next_cut) if (y + 1) % 8 else ()
                shift, setup, delays = None, 0, (0,)
                if left:
                    shift = left[0] + 2 - right[-1] if right else None
                    setup = 0 if shift == 0 else 6 if shift in (-1, 1) else 10
                    delays = range(0, 54 if right else 225, 4)
                for idle in delays:
                    end = burst(y + 1, left, after_right + setup + idle, False) if left else after_right
                    if end is None or end > LINE_TSTATES + last_start:
                        continue
                    next_line = end - LINE_TSTATES
                    start_search = next_line + max(0, first_start - next_line + (first_start - next_line) % 2)
                    for next_start in range(start_search, last_start + 1, 2):
                        tail = next_start - next_line
                        key = next_cut, next_start
                        if tail != 2 and key not in following:
                            following[key] = program + ((right, left, shift, idle, tail),)
                    if left and next_line >= first_start:
                        break
        if not following:
            raise ValueError(f"Luminance logo exceeds the {model} raster budget on line {y}, phase {phase}")
        states = following
    (_, finish), program = next(iter(states.items()))
    return program, height * LINE_TSTATES + finish


def compile_copper(model):
    """Shade the full spans of the three populated menu character rows."""
    origin, waits, first = PROFILES[model]
    # The logo jumps through the two exit stubs, restores SP, then selects
    # the copper's private stack and jumps to this program.
    time = RASTER_END + 70
    code = []

    def delay_until(target):
        delay = target - time - 10  # DELAY includes CALL, but not LD BC.
        if delay < 141:
            raise ValueError("Copper setup exceeds the available beam time")
        code.extend((f"ld bc,{delay}", "call DELAY"))

    def ink(attr):
        return f"ld hl,{attr * 257}"

    def push_ink(pairs, target):
        for i, x in enumerate(pairs):
            if i and x != pairs[i - 1] - 2:
                code.append(f"ld sp,{target + x + 2}")
            code.append("push hl")

    for row, text in COPPER_MENU_TEXT.items():
        cells = {x for x, char in enumerate(text) if char != " "} | COPPER_CONTROL_MARKS.get(row, set())
        visible = (cells,) * 8 + (set(),)
        program, finish = schedule(model, 0, visible, copper=True)
        row_time = (row * 8 - 8) * LINE_TSTATES
        target = 0x5800 + 32 * row
        start = first + row_time
        # Seed the first band two scanlines before this character row.
        seed_start = start - 2 * LINE_TSTATES
        delay_until(seed_start)
        left, right = min(cells) & ~1, (max(cells) + 2) & ~1
        pairs = (right - left) // 2
        code.extend((ink(COPPER_BANDS[0]), f"ld sp,{target + right}"))
        code.extend(["push hl"] * pairs)
        code.append("ld sp,menuCopperStack")
        time = seed_start + 20
        for _ in range(pairs):
            time += 5
            for _ in range(2):
                time = attribute_write_end(time, origin, waits)
        time += 10
        delay_until(start)
        for y, (early, late, shift, idle, tail) in enumerate(program):
            if early:
                code.append(f"ld sp,{target + early[0] + 2}")
                push_ink(early, target)
            if y + 1 < len(COPPER_BANDS):
                code.append(ink(COPPER_BANDS[y + 1]))
            if late:
                if shift != 0:
                    code.append(f"ld sp,{target + late[0] + 2}")
                if idle:
                    code.append(f"db {','.join(map(str, padding(idle)))}")
                push_ink(late, target)
            if tail:
                code.append(f"db {','.join(map(str, padding(tail)))}")
        code.append("ld sp,menuCopperStack")
        time = finish + row_time + 10
    delay_until(58160)
    code.append("jp menuCopperDone")
    return "\n".join(f"    {line}" for line in code) + "\n"


def compile_phase(job):
    model, phase, bitmap = job
    visible = tuple(visible_cells(bitmap)) + (set(),)
    raster = bytearray()
    seed = bytearray()

    def pushes(pairs, y):
        return b"".join(PUSH[((x + y + phase) % 12) // 2] for x in pairs)

    program, finish = schedule(model, phase, visible)
    for y, (right, left, shift, idle, tail) in enumerate(program):
        target = ATTRS + 32 * (y // 8)
        if right:
            raster += load_sp(target + right[0] + 2) + pushes(right, y)
        if left:
            adjust = {-1: b"\x3b", 0: b"", 1: b"\x33"}
            raster += adjust.get(shift, load_sp(target + left[0] + 2))
            raster += padding(idle) + pushes(left, y + 1)
        raster += padding(tail)
        if y % 8 == 0 and visible[y]:
            parity = (y + phase) % 2
            high, low = max(visible[y]), min(visible[y])
            pairs = range(high - (high - parity) % 2, low - (low - parity) % 2 - 1, -2)
            seed += load_sp(target + pairs[0] + 2) + pushes(pairs, y)
    cycles = RASTER_END - finish
    if cycles % 2:
        raster += b"\x3e\0"  # LD A,0. The logo has finished using the palette.
        cycles -= 7
    assert cycles >= 4
    raster += padding(cycles) + b"\xc3" + word(RASTER_EXIT)
    seed += b"\xc3" + word(SEED_EXIT)
    if len(raster) + len(seed) > PROGRAM_BYTES:
        raise ValueError("Luminance logo exceeds its scratch buffer")
    return word(len(raster)) + (raster + seed).ljust(PROGRAM_BYTES, b"\0")


def build_luminance(output, bitmap):
    # Phase n+6 has identical instruction timing to n: IX and IY swap words,
    # as do the four unprefixed PUSH registers. Store only six programs.
    jobs = [(model, phase, bitmap) for model in PROFILES for phase in range(6)]
    with ProcessPoolExecutor(max_workers=6) as pool:
        programs = list(pool.map(compile_phase, jobs))
    for index, model in enumerate(PROFILES):
        pointer = 12  # Six offsets relative to the start of this bundle.
        offsets = bytearray()
        images = programs[index * 6:index * 6 + 6]
        for image in images:
            offsets += word(pointer)
            pointer += len(image)
        (output / f"luminance-{model}.bin").write_bytes(offsets + b"".join(images))
        (output / f"copper-{model}.a80").write_text(compile_copper(model), encoding="ascii")

    palette = bytearray()
    for offset in (0, 3):
        for pair in (1, 2, 4, 5, 0, 3):
            start = 2 * ((pair + offset) % 6)
            palette += LUMINANCE_BANDS[start:start + 2]
    (output / "luminance-inks.bin").write_bytes(palette)
