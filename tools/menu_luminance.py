"""Compile the luminance logo and menu text into timed Z80 stack writes."""

from concurrent.futures import ProcessPoolExecutor
from functools import cache
from struct import pack


LUMINANCE_BANDS = bytes((
    0x01, 0x05, 0x45, 0x47, 0x45, 0x05,  # Blue and cyan.
    0x01, 0x02, 0x06, 0x46, 0x47, 0x46, 0x06, 0x02,  # Red and yellow.
))
WIDTH, HEIGHT = 28, 32
LINE_TSTATES = 228
ATTRS = 0x5842
EARLIEST_FETCH, LATEST_FETCH = 16191, 16198  # At the logo's left edge.
ATTRIBUTE_WRITE_DEADLINE = 16194  # Three T-states before the nominal 128K fetch.
RASTER_EXIT, SEED_EXIT = 0x8003, 0x8006
RASTER_BYTES = 960
PROGRAM_BYTES = 992  # The seed runs in its source bank and need not fit the raster copy.
RASTER_END = 23364
COPPER_BANDS = (0x01, 0x05, 0x45, 0x45, 0x47, 0x45, 0x45, 0x05)
COPPER_ROW_BANDS = {10: (0x01, 0x06, 0x46, 0x46, 0x47, 0x46, 0x46, 0x06)}
GOLD_BAR = (2, 6, 7, 6, 2)
GOLD_BAR_TOP, GOLD_BAR_BOTTOM = 8, 51
LOGO_LINE_SHIFT = 8 * LINE_TSTATES
TOP_BAR_START = 15950
COPPER_MENU_TEXT = {
    10: "      PRESS FIRE TO START",
    16: "        1-9 TEST LEVELS",
    18: "        R REDEFINE KEYS",
}
PROFILES = {
    # Contention start, wait pattern and calibrated first instruction T-state.
    "128k": (16185, (6, 5, 4, 3, 2, 1, 0, 0), 16110),
    "plus": (16189, (1, 0, 7, 6, 5, 4, 3, 2), 16109),
}
# BC, DE, HL, AF, IX, IY and BC' hold the consecutive two-cell pairs.
PUSH = (0xC5, 0xD5, 0xE5, 0xF5, 0xC5, 0xD5, 0xE5)


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


def burst_ops(pairs, y, phase, *, copper=False):
    """Yield stack writes, reloading SP at gaps and grouping register swaps."""
    alternate = False
    for i, x in enumerate(pairs):
        if i and x != pairs[i - 1] - 2:
            yield 0x31, x  # LD SP,nn
        pair = 2 if copper else ((x + y + phase) % len(LUMINANCE_BANDS)) // 2
        if pair != 3 and alternate != (pair >= 4):
            yield 0xD9, x  # EXX
            alternate = not alternate
        yield PUSH[pair], x
    if alternate:
        yield 0xD9, None


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
        p = parity(y)
        return tuple(sorted({x - (x - p) % 2 for x in cells}, reverse=True))

    def cuts(y):
        # Seed the entire first scanline of each character row ahead of time.
        return (width + parity(y),) if y % 8 == 0 else range(parity(y) - 2, width + 2, 2)

    @cache
    def operations(y, pairs):
        return tuple(burst_ops(pairs, y, phase, copper=copper))

    @cache
    def burst(y, pairs, t, early):
        for op, x in operations(y, pairs):
            if op == 0x31:
                t += 10
                continue
            if op == 0xD9:
                t += 4
                continue
            begin = t
            t += 5
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


def compile_gold_bar(model, scanline, start, end):
    origin, waits, _ = PROFILES[model]
    code = []
    time = start

    def advance(target):
        nonlocal time
        cycles = target - time
        if cycles >= 161 and (time == start or target == end):
            code.extend(("ld sp,menuCopperStack", f"ld bc,{cycles - 20}", "call DELAY"))
        elif cycles:
            if cycles % 2:
                code.append("ld a,0")
                cycles -= 7
            if cycles < 0 or cycles == 2:
                raise ValueError("Cannot pad gold bar raster")
            code.append(f"db {','.join(map(str, padding(cycles)))}")
        time = target

    def sync_at(sample):
        nonlocal time
        advance(sample - 10)  # Opcode and address fetches precede the RAM read.
        code.append("ld a,(#5800)")
        time = attribute_write_end(sample, origin, waits)

    # The shadow screen supplies the yellow and white lines. The normal
    # screen supplies the red edges and the black after the bar.
    beam = origin + (scanline - 8) * LINE_TSTATES
    advance(beam - 85)
    code.append("ld bc,#7ffd")
    time += 10
    for y, colour in enumerate((*GOLD_BAR, 0)):
        line = beam + y * LINE_TSTATES
        advance(line - 65)
        code.extend((f"ld a,{colour}", "out (#fe),a"))
        time += 18
        if y in (1, len(GOLD_BAR) - 1):
            code.extend((f"ld a,{24 if y == 1 else 16}", "out (c),a"))
            time += 19
        if model == "plus" and scanline == GOLD_BAR_TOP and y == len(GOLD_BAR) - 1:
            # Near the end of contention, early arrivals wait while late
            # arrivals run freely. Two such reads narrow the window to one
            # wait group, and the third read locks it to a single cycle.
            sync_at(line + 122)
    if model == "plus" and scanline == GOLD_BAR_TOP:
        sync_at(line + 130)
        sync_at(line + LINE_TSTATES + 99)
    advance(end)
    return code


def compile_copper(model):
    """Shade the full spans of the three populated menu character rows."""
    origin, waits, first = PROFILES[model]
    # The logo jumps through the two exit stubs, restores SP, then selects
    # the copper's private stack and jumps to this program.
    time = RASTER_END + LOGO_LINE_SHIFT + 70
    code = []
    if model == "plus":
        # Re-lock on blank paper below the logo. Sample in the middle of
        # an ASIC wait group so either side of the expected arrival lands
        # on the same release cycle before the lower bar and copper text.
        sample = origin + (49 - 8) * LINE_TSTATES + 29
        delay = sample - time - 20  # LD BC and the read's opcode/address fetch.
        code.extend((f"ld bc,{delay}", "call DELAY", "ld a,(#5800)"))
        time = attribute_write_end(sample, origin, waits)
    code.extend(compile_gold_bar(model, GOLD_BAR_BOTTOM, time, 27000 + LINE_TSTATES * 8))
    time = 27000 + LINE_TSTATES * 8
    code.append("ld sp,menuCopperStack")
    time += 10

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
        bands = COPPER_ROW_BANDS.get(row, COPPER_BANDS)
        cells = {x for x, char in enumerate(text) if char != " "}
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
        code.extend((ink(bands[0]), f"ld sp,{target + right}"))
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
            if y + 1 < len(bands):
                code.append(ink(bands[y + 1]))
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

    def pushes(pairs, y, target):
        code = bytearray()
        for op, x in burst_ops(pairs, y, phase):
            if op == 0x31:
                code += load_sp(target + x + 2)
            else:
                code.append(op)
        return code

    program, finish = schedule(model, phase, visible)
    for y, (right, left, shift, idle, tail) in enumerate(program):
        target = ATTRS + 32 * (y // 8)
        if right:
            raster += load_sp(target + right[0] + 2) + pushes(right, y, target)
        if left:
            adjust = {-1: b"\x3b", 0: b"", 1: b"\x33"}
            raster += adjust.get(shift, load_sp(target + left[0] + 2))
            raster += padding(idle) + pushes(left, y + 1, target)
        raster += padding(tail)
        if y % 8 == 0 and visible[y]:
            parity = (y + phase) % 2
            high, low = max(visible[y]), min(visible[y])
            pairs = range(high - (high - parity) % 2, low - (low - parity) % 2 - 1, -2)
            seed += load_sp(target + pairs[0] + 2) + pushes(pairs, y, target)
    cycles = RASTER_END - finish
    if cycles % 2:
        raster += b"\x3e\0"  # LD A,0. The logo has finished using the palette.
        cycles -= 7
    assert cycles >= 4
    raster += padding(cycles) + b"\xc3" + word(RASTER_EXIT)
    seed += b"\xc3" + word(SEED_EXIT)
    if len(raster) > RASTER_BYTES or len(raster) + len(seed) > PROGRAM_BYTES:
        raise ValueError(f"Luminance logo program is too large for {model}, phase {phase}")
    return word(len(raster)) + (raster + seed).ljust(PROGRAM_BYTES, b"\0")


def build_luminance(output, bitmap):
    phases = len(LUMINANCE_BANDS)
    if not 2 <= phases <= 2 * len(PUSH) or phases % 2:
        raise ValueError("The logo needs an even count of two to fourteen bands")
    jobs = [(model, phase, bitmap) for model in PROFILES for phase in range(phases)]
    with ProcessPoolExecutor(max_workers=6) as pool:
        programs = list(pool.map(compile_phase, jobs))
    layout = [f"MENU_LOGO_PHASES equ {phases}"]
    for name, line in (("TOP", GOLD_BAR_TOP), ("BOTTOM", GOLD_BAR_BOTTOM)):
        layout.append(f"MENU_GOLD_{name}_PIXELS equ {0x4000 + 32 * (line // 8) + 256 * (line % 8)}")
        layout.append(f"MENU_GOLD_{name}_ATTRS equ {0x5800 + 32 * (line // 8)}")
    # Bank 3 has room for five programs before the tracker and six after
    # its song. Put the rest after the maps or above the shadow screen.
    for index, (model, label, bank3_phases, overflow) in enumerate((
        ("128k", "luminance128", 5, 1), ("plus", "luminancePlus", 6, 7),
    )):
        images = programs[index * phases:(index + 1) * phases]
        first = images[:bank3_phases]
        extra = images[bank3_phases:]
        (output / f"luminance-{model}.bin").write_bytes(b"".join(first))
        (output / f"luminance-{model}-extra.bin").write_bytes(b"".join(extra))
        (output / f"copper-{model}.a80").write_text(compile_copper(model), encoding="ascii")
        gate = PROFILES[model][2] + LOGO_LINE_SHIFT - 111  # JP, read, palette loads and JP.
        if model == "plus":
            gate -= 4  # Sample inside the ASIC wait group, before its final free slot.
        top = compile_gold_bar(model, GOLD_BAR_TOP, TOP_BAR_START, gate)
        (output / f"gold-{model}.a80").write_text(
            "\n".join(f"    {line}" for line in (*top, "jp menuLogoGate")) + "\n", encoding="ascii")
        layout.append(f"{label}Programs:")
        for bank, base, entries in ((3, label, first), (overflow, f"{label}Extra", extra)):
            for phase, _ in enumerate(entries):
                layout.extend((f"    db {bank}", f"    dw {base}+{phase}*{PROGRAM_BYTES + 2}"))

    (output / "luminance-layout.a80").write_text("\n".join(layout) + "\n", encoding="ascii")
    (output / "luminance-inks.bin").write_bytes(LUMINANCE_BANDS.ljust(14, b"\0"))
