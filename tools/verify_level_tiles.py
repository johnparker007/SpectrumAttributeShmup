"""Trace each installed normal and shifted tile row on the retail TAP, and time GET READY."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from build_art import ART, LEVEL_MAPS, SCREEN_FONT
from level_tiles import layout, read_map
from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols


def shifted_rows(tile):
    # Decode the eight dots, shift them one place right, and pack the two edge cells.
    for y in range(8):
        pairs = tile[y*6+2:y*6+6]
        dots = [colour for pair in pairs for colour in (pair & 7, (pair >> 3) & 7)]
        yield bytes([0, 64 | dots[0] << 3,
                     *(64 | dots[x] | dots[x+1] << 3 for x in (1, 3, 5)), 64 | dots[7]])


def verify(game, emulator, model, level, scratch):
    s = read_symbols(game / "main.sym")

    def pc(label):
        return f"PC={s[label]:04X}H"

    select, begin, end, render = map(pc, ("menuSelected", "tileLoadBegin", "tileLoadEnd", "enableRender"))
    raw, row = map(pc, ("copyTileBytes", "installLevelTiles.rowReady"))
    left, right = row + " AND 1=1", row + " AND 2=2"
    state = begin + " AND 3=3"
    captions = [(point+" AND 4=4", "PEEKW(4B4BH)") for point in (begin, end)]
    level_number = [(point+" AND 5=5", "PEEK(4B97H)") for point in (begin, end)]
    spool = scratch / f"tiles-{model}-{level}.txt"
    spool.write_text(str(level)*80, encoding="ascii")
    checks = [(point, "TSTATESP") for point in (select, begin, end, render)]
    checks.extend(((raw, "DE*256+PEEK(HL)"), (row, "DE-6"),
                   (left, "PEEKW(DE-6)+65536*PEEK(DE-4)"), (right, "PEEKW(DE-3)+65536*PEEK(DE-1)"),
                   (state, f"PEEKW({s['intProc']+1:04X}H)")))
    checks.extend(captions + level_number)
    log = breakpoint_log(emulator, game / "main.tap", model, 24, checks, True, spool, repeat=True)
    events = [(point, int(value)) for point, value in HIT.findall(log)]
    def at(point):
        return next(value for key, value in events if key == point)

    start, first, last, play = map(at, (select, begin, end, render))
    assert start < first < last < play and at(state) == s["nullProc"]
    font = (game / SCREEN_FONT).read_bytes()
    def scan(char):
        return font[(ord(char)-32)*8+3]
    for key, _ in captions:
        assert at(key) == scan("G") + 256*scan("E"), (model, level, "GET READY bitmap")
    for key, _ in level_number:
        assert at(key) == scan(str(level)), (model, level, "level number bitmap")
    events = events[events.index((begin, first)):events.index((end, last))]
    normal = {value//256: value%256 for point, value in events if point == raw}
    packed_rows = [[value for point, value in events if point == key] for key in (row, left, right)]
    shifted = {address: l.to_bytes(3, "little") + r.to_bytes(3, "little")
               for address, l, r in zip(*packed_rows, strict=True)}
    atlas = (game / "gfx" / f"level-{level}.bin").read_bytes()
    _, active = layout(*read_map(ART / "maps" / LEVEL_MAPS[level-1]))
    want_bytes, want_rows = {}, {}
    for slot in active:
        address = s["tileSet"] + slot*48
        tile = atlas[slot*48:(slot+1)*48]
        want_bytes.update((address+i, value) for i, value in enumerate(tile))
        want_rows.update((address+y*6, value) for y, value in enumerate(shifted_rows(tile)))
    assert normal == want_bytes, (model, level, "normal tile bytes", len(normal), len(want_bytes))
    assert shifted == want_rows, (model, level, "shifted tile rows", len(shifted), len(want_rows))
    assert play-start < FRAME*150, (model, level, "GET READY exceeded three seconds")
    print(f"{model} level {level}: {len(active)} slots, tile load {(last-first)*20/FRAME:.1f} ms, "
          f"selection to renderer {(play-start)*20/FRAME:.1f} ms", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", type=Path, required=True)
    p.add_argument("--emulator", type=Path, required=True)
    p.add_argument("--levels", type=int, nargs="+", choices=range(1,len(LEVEL_MAPS)+1), default=range(1,len(LEVEL_MAPS)+1))
    args = p.parse_args()
    with TemporaryDirectory() as scratch, ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(verify, args.game.resolve(), args.emulator.resolve(), model, level, Path(scratch))
                for level in args.levels for model in ("P2", "P2A41")]
        for job in jobs:
            job.result()
