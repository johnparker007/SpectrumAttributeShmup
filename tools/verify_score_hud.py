"""Check HUD glyphs, bitmap writes and incremental update cost."""

from pathlib import Path

from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols, trace
from verify_zesarux_raster import HEIGHT, WIDTH, capture_video, paper_row, run


PROBE = Path(__file__).resolve().parents[1] / "tests" / "hud" / "score_arithmetic.asm"


def assemble_arithmetic_probe(assembler, game):
    run([assembler, "--sym=score_arithmetic.sym", PROBE], game)


def check_arithmetic(emulator, game, model):
    result = trace(emulator, game / "score_arithmetic.sna", game / "score_arithmetic.sym",
                   ["passed", "failed"], model, 1)
    if [event["labels"] for event in result["events"]] != [["passed"]]:
        raise ValueError(f"{model}: score carry, saturation or digit order failed")


def expected_rows(targets, glyphs, icon, left, right):
    drawn = [0] * 4
    drawn_lives = previous_lives = 3
    lives_dirty = False
    active = None
    for score, lives in targets:
        digits = [int(digit) for digit in reversed(f"{score:04d}")]
        lives_dirty |= lives != previous_lives
        previous_lives = lives
        for _ in range(2):
            if active is None:
                if lives_dirty:
                    if drawn_lives > lives:
                        drawn_lives -= 1
                        active = (bytes(8), left + drawn_lives, 0)
                    elif drawn_lives < lives:
                        active = (icon, left + drawn_lives, 0)
                        drawn_lives += 1
                    else:
                        lives_dirty = False
                else:
                    for position, digit in enumerate(digits):
                        if drawn[position] != digit:
                            drawn[position] = digit
                            active = (glyphs[8 * digit:8 * (digit + 1)], right - position, 0)
                            break
                yield []
            else:
                glyph, column, row = active
                address = (0x40 + row) * 256 + column
                pixel = glyph[row]
                yield [("bitmap", address * 256 + pixel), ("page_in", 0x17),
                       ("shadow", (address + 0x8000) * 256 + pixel), ("page_out", 0x10)]
                active = (glyph, column, row + 1) if row < 7 else None


def check_hud_updates(emulator, replay, model, targets):
    symbols = read_symbols(replay / "main.sym")
    points = {
        "hudInit": ("init", "TSTATESP"),
        "hudStep": ("start", "TSTATESP"),
        "hudFrame1Done": ("finish", "TSTATESP"),
        "hudFrame2Done": ("finish", "TSTATESP"),
        "hudBitmapWrite": ("bitmap", "DE*256+A"),
        "hudShadowWrite": ("shadow", "DE*256+A"),
        "hudPageIn": ("page_in", "A"),
        "hudPageOut": ("page_out", "A"),
        "hudAttributes": ("attrs_start", "TSTATESP"),
        "hudAttributesDone": ("attrs_finish", "TSTATESP"),
    }
    breakpoints = {f"PC={symbols[label]:04X}H": details for label, details in points.items()}
    log = breakpoint_log(emulator, replay / "main.tap", model, 125,
                         [(condition, expression) for condition, (_, expression) in breakpoints.items()],
                         fast_autoload=True)
    hits = HIT.findall(log)
    if not hits or len(hits) != log.count("Catch breakpoint:"):
        raise ValueError(f"{model}: incomplete HUD trace")
    glyphs = (replay / "score_digits.bin").read_bytes()
    icon = (replay / "hud_life_icon.bin").read_bytes()
    left, right = symbols["HUD_X"], symbols["HUD_DIGIT_RIGHT"]
    reference = list(expected_rows(targets, glyphs, icon, left, right))
    drawing, idle, attrs = [], [], []
    life_rows, score_rows = 0, 0
    previous_frame = None
    update, attrs_begin = None, None
    index = 0
    initialized = False
    for condition, raw in hits:
        event, _ = breakpoints[condition]
        value = int(raw)
        if event == "init":
            if initialized or previous_frame is not None:
                raise ValueError(f"{model}: the HUD bitmap was initialized again during play")
            initialized = True
        elif event == "start":
            if not initialized:
                raise ValueError(f"{model}: score updates began before HUD initialization")
            if update is not None:
                raise ValueError(f"{model}: overlapping HUD updates")
            frame = value // FRAME
            if previous_frame is not None and frame != previous_frame + 1:
                raise ValueError(f"{model}: missed a HUD frame")
            previous_frame = frame
            update = (value, [])
        elif event == "attrs_start":
            attrs_begin = value
        elif event == "attrs_finish":
            if attrs_begin is None or attrs_begin // FRAME != value // FRAME:
                raise ValueError(f"{model}: attribute copy escaped its frame")
            attrs.append(value - attrs_begin + 17)
            attrs_begin = None
        elif event == "finish":
            if update is None or update[0] // FRAME != value // FRAME or update[1] != reference[index]:
                raise ValueError(f"{model}: wrong or late HUD bitmap update at replay frame {index + 1}")
            cost = value - update[0] + 17
            (drawing if update[1] else idle).append(cost)
            if update[1]:
                column = (update[1][0][1] >> 8) & 255
                if column < left + 3:
                    life_rows += 1
                else:
                    score_rows += 1
            update = None
            index += 1
            if index == len(reference):
                break
        elif event in ("bitmap", "shadow") and ((value >> 8) & 255) > right:
            raise ValueError(f"{model}: the HUD rewrote a startup-only trailing zero")
        elif update is not None:
            update[1].append((event, value))
        else:
            raise ValueError(f"{model}: a bitmap write occurred outside the HUD update")
    if index < len(reference):
        raise ValueError(f"{model}: only {index} of {len(reference)} score frames were captured")
    if len(attrs) * 2 != index:
        raise ValueError(f"{model}: score attributes were not copied once per game tick")
    return {"frames_checked": index, "bitmap_rows_written": len(drawing),
            "life_icon_rows_written": life_rows, "score_rows_written": score_rows, "trailing_zero_writes": 0,
            "bitmap_row_tstates": [min(drawing), max(drawing)],
            "no_bitmap_write_tstates": [min(idle), max(idle)],
            "attribute_strip_tstates": sorted(set(attrs))}


def check_hud_video(emulator, replay, model):
    video = replay / f"score-{model}.raw"
    capture_video(emulator, model, ["--tape", replay / "main.tap", "--fastautoload", "--vofilefps", "25"], video, 15)
    symbols = read_symbols(replay / "main.sym")
    width = symbols["HUD_WIDTH"]
    x = symbols["HUD_X"] * 8 * 3
    digit_column = symbols["HUD_DIGIT_RIGHT"] - symbols["HUD_X"]
    font = (replay / "score_digits.bin").read_bytes()
    initial = (replay / "hud_initial.bin").read_bytes()

    def bitmap(glyph_rows):
        data = b"".join(bytes((255 if value & (0x80 >> bit) else 0,)) * 3
                        for value in glyph_rows for bit in range(8))
        return data

    wanted = {}
    for lives in range(4):
        for score, glyph in (("000000", font[:8]), ("000100", font[8:16])):
            image = bytearray(initial)
            for row, pixels in enumerate(glyph):
                start = width * row
                image[start + lives:start + 3] = bytes(3 - lives)
                image[start + digit_column] = pixels
            wanted[bitmap(image)] = (score, lives)
    observed = set()
    frame_size = WIDTH * HEIGHT * 3
    with video.open("rb") as recording:
        while frame := recording.read(frame_size):
            if len(frame) != frame_size:
                raise ValueError(f"{model}: truncated score video")
            row_bytes = width * 8 * 3
            region = b"".join(paper_row(frame, row)[x:x + row_bytes] for row in range(8))
            if region in wanted:
                observed.add(wanted[region])
    if not {("000000", 3), ("000100", 2)} <= observed:
        raise ValueError(f"{model}: video missed the opening HUD or its first score and life changes")
    return {"scores_seen_in_video": sorted({score for score, _ in observed}),
            "life_icon_counts_seen_in_video": sorted({lives for _, lives in observed})}
