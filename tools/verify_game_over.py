"""Exercise the last hit, the full tracker playthrough, Enter and M on real TAP loads."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shutil
import tempfile

from profile_ringo8 import FRAME, HIT
from trace_zesarux import breakpoint_log, read_symbols
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run


ROOT = Path(__file__).resolve().parents[1]


def song_frames():
    text = (ROOT / "game/music/name-regist.vt2").read_text(encoding="utf-8-sig")
    sections = dict(re.findall(r"^\[([^\]]+)\]\s*([^\[]*)", text, re.M))
    settings = dict(line.split("=", 1) for line in sections["Module"].splitlines() if "=" in line)
    order = settings["PlayOrder"].replace("L", "").split(",")
    return int(settings["Speed"]) * sum(len(sections["Pattern" + p].strip().splitlines()) for p in order)


def make_probe(source, game, assembler):
    shutil.copytree(source, game)
    main = game / "main.asm"
    entry = b"            call gameInit"
    code = main.read_bytes()
    if entry not in code:
        raise ValueError("Missing game initializer")
    main.write_bytes(code.replace(entry, b"            call seedLastShip", 1))
    shutil.copyfile(ROOT / "tests/audio/last_ship_seed.a80", game / "last_ship_seed.a80")
    with (game / "gfx/resources.a80").open("ab") as resource:
        resource.write(b'\n    include "last_ship_seed.a80"\n')
    for filename in ("main.sna", "main.tap"):
        (game / filename).unlink()
    run([assembler, *("-D" + flag + "=1" for flag in FLAGS), "--sym=main.sym", "main.asm"], game)


def verify(game, emulator, model, key, ticks):
    s = read_symbols(game / "main.sym")

    def pc(label):
        return f"PC={s[label]:04X}H"

    death, playing = pc("controlsReady.gameOver"), pc("gameOverTickDone")
    menu, restart = pc("gameOverMenu"), pc("gameOverRestart")
    # Banked player addresses can also execute as tile code during gameplay.
    title_song = pc("menuTrackInit") + " AND PEEKW(PC)=4621H"
    card = pc("menuTrackInitHL") + f" AND HL={s['attrBuffer']:04X}H"
    volumes = playing + " AND 1=1"  # R8-R10 in the archived player's AY output buffer
    level = pc("gameInit")
    checks = [(death, "TSTATESP"), (playing, "TSTATESP"), (title_song, "TSTATESP"),
              (menu, "TSTATESP"), (restart, "TSTATESP"),
              (level, f"PEEK({s['selectedLevel']:04X}H)+256*PEEKW({s['hudScore']:04X}H)"),
              (card, "PEEK(5948H)+256*PEEK(5800H)+65536*PEEK(5AFFH)"),
              (volumes, "PEEK(DD8EH)+256*PEEK(DD8FH)+65536*PEEK(DD90H)"),
              (pc("showGameOver"), f"PEEKW({s['hudScore']:04X}H)")]
    # Read the six final-score glyphs from the visible screen before playback.
    font = (game / "font/arcade-8.bin").read_bytes()
    score = bytes(font[(ord(c) - 32) * 8 + 3] for c in "123400")
    score_checks = []
    for offset in (0, 3):
        address = 0x53FA + offset
        watch = card + f" AND {offset}={offset}"
        checks.append((watch, f"PEEKW({address:04X}H)+65536*PEEK({address+2:04X}H)"))
        score_checks.append((watch, int.from_bytes(score[offset:offset+3], "little")))
    spool = game / f"{model}-{key}.keys"
    spool.write_bytes(b"8" * 33 + {"auto": b"", "enter": b"\r", "menu": b"m"}[key] + b"n" * 20)
    seconds = max(80, ticks // 20 + 25) if key == "auto" else 30
    log = breakpoint_log(emulator, game / "main.tap", model, seconds, checks, True, spool)
    events = [(k, int(v)) for k, v in HIT.findall(log)]

    def values(k):
        return [v for name, v in events if name == k]

    delay = values(death)[:51]
    assert len(delay) == 51 and delay[-1] // FRAME - delay[0] // FRAME == 100
    assert values(card)[0] == 0x470047 and values(pc("showGameOver"))[0] == 0x1234
    assert all(values(watch)[0] == expected for watch, expected in score_checks)
    frames = values(playing)
    assert frames and all(b // FRAME == a // FRAME + 1 for a, b in zip(frames, frames[1:]))
    if key == "auto":
        assert len(frames) == ticks + 1, (model, len(frames), ticks)  # last call detects end
        assert values(volumes)[-1] == 0 and any(all(v & (15 << n) for n in (0, 8, 16))
                                                for v in values(volumes))
    else:
        assert 0 < len(frames) < ticks
    if key == "enter":
        assert values(restart) and not values(menu) and values(level)[:2] == [7, 7]
    else:
        assert values(menu) and not values(restart) and values(title_song)[-1] > values(menu)[0]
    print(f"{model} {key}: 100-frame death delay, {len(frames)} tracker calls, "
          f"latest return at {max(t % FRAME for t in frames)} T", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="Assembled default game directory")
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    args = parser.parse_args()
    ticks = song_frames()
    with tempfile.TemporaryDirectory(prefix="blokius-game-over-") as scratch:
        game = Path(scratch) / "game"
        make_probe(args.game, game, args.assembler.resolve())
        with ThreadPoolExecutor(max_workers=2) as pool:
            for key in ("auto", "enter", "menu"):
                jobs = [pool.submit(verify, game, args.emulator.resolve(), model, key, ticks)
                        for model in MODELS]
                for job in jobs:
                    job.result()


if __name__ == "__main__":
    main()
