"""Check all eight HUD scanlines on both screens, including bonus and restart boundaries."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile

from trace_zesarux import read_symbols, trace
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run

PROBE = Path(__file__).resolve().parents[1] / "tests/hud/bottom_score.asm"


def first_bonus_points(game):
    bcd = read_symbols(game / "main.sym")["FIRST_BONUS_HUNDREDS"]
    return int(f"{bcd:04x}") * 100


def life_pixels(sprite, font):
    # Decode the renderer's odd-X copy as a reference for the even-X conversion.
    dots = {}
    for y in range(5):
        for lane in range(1, 6):
            offset = 30 + 6 * y + 2 * (lane // 2)
            shift = 3 * (lane % 2)
            if ((sprite[offset] >> shift) & 7) == 0:
                dots[lane - 1, y] = (sprite[offset + 1] >> shift) & 7
    zero_start = 8 * (ord("0") - 32)
    zero = font[zero_start:zero_start + 8]
    ink_rows = [y for y, bits in enumerate(zero) if bits]
    top = (min(ink_rows) + max(ink_rows)) // 2 - 2
    return [(x, y + top) for (x, y), colour in dots.items()
            if colour != 5 or any(p not in dots for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))]


def bitmap(font, ship_pixels, level, score, lives):
    text = f"LEVEL {level}".ljust(26) + f"{score:6d}"
    image = bytearray(font[8 * (ord(char) - 32) + y] for y in range(8) for char in text)
    # Once the 18 single-ship cells are full, each further life converts
    # the next three cells on the right into a group of four ships.
    spares = max(0, lives - 1)
    tight_groups = max(0, spares - 18)
    wide = spares - 4 * tight_groups
    origins = [64 + 8*n + 1 for n in range(wide)]
    origins.extend(64 + 8*wide + 6*n for n in range(4 * tight_groups))
    for origin in origins:
        for dx, y in ship_pixels:
            x = origin + dx
            image[32*y + x//8] |= 0x80 >> (x % 8)
    return image


def build_cases(game):
    font = (game / "font/arcade-8.bin").read_bytes()
    ship_pixels = life_pixels((game / "player_art.bin").read_bytes(), font)
    images, cases = bytearray(), []

    def check(level, score, lives):
        cases.extend((f"ld hl,expectedImages+{len(images)}", f"ld bc,#{score // 100:04d}",
                      f"ld a,{lives}", "call checkHUD"))
        images.extend(bitmap(font, ship_pixels, level, score, lives))

    previous = 0
    # Include all extra lives, consecutive awards across boundaries, and
    # the non-award at 50k. Each actual +100 passes through the enemy kill path's counter.
    first = first_bonus_points(game)
    milestones = (first, *range(70000, 1000000, 50000))
    scores = sorted({0, 100, 900, 1000, 1100, 9900, 10000, 19900, 20000, 20100, 50000, 69900,
                     100000, 101000, 999900, first-100, first+100, *milestones})
    for score in scores:
        if score > previous:
            cases.extend((f"ld bc,{(score - previous) // 100}", "call awardMany"))
        check(16, score, 3 + sum(target <= score for target in milestones))
        previous = score
    cases.extend(("call hudAward", "ld a,1", "ld (player_hit),a", "call updatePlayerLife"))
    check(16, 999900, 22)
    cases.append("call resetEncounter")
    check(16, 0, 3)
    # Reverse the newly earned icon before its incremental draw has finished.
    cases.extend((f"ld bc,{first//100}", "call awardMany", "call hudStep", "call hudStep",
                  "ld a,1", "ld (player_hit),a", "call updatePlayerLife"))
    check(16, first, 3)
    cases.extend(("call resetEncounter", "call hudAward", "call hudStep", "call resetEncounter"))
    check(16, 0, 3)
    # Lose the 19th spare with the second of its three cells partially drawn.
    cases.extend(("ld bc,8199", "call awardMany"))
    check(16, 819900, 19)
    cases.extend(("call hudAward", "dup 7 : call hudStep : edup",
                  "ld a,1", "ld (player_hit),a", "call updatePlayerLife"))
    check(16, 820000, 19)
    cases.append("call resetEncounter")
    check(16, 0, 3)
    cases.append("call hudAward")
    for lives in (2, 1, 0):
        cases.append("call loseShip")
        check(16, 100, lives)
    cases.append("call resetEncounter")
    check(16, 0, 3)
    for level in (9, 10, 16, 1):
        cases.extend((f"ld a,{level-1}", "ld (selectedLevel),a", "call hudInit"))
        check(level, 0, 3)
    (game / "hud_expected.bin").write_bytes(images)
    (game / "hud_cases.asm").write_text("".join("    " + line + "\n" for line in cases), encoding="ascii")
    return len(images) // 256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path, help="Assembled default game directory")
    parser.add_argument("--assembler", required=True, type=Path)
    parser.add_argument("--emulator", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blokius-hud-") as tmp:
        game = Path(tmp) / "game"
        shutil.copytree(args.game, game)
        count = build_cases(game)
        run([args.assembler.resolve(), *("-D"+flag+"=1" for flag in FLAGS),
             "--sym=bottom_score.sym", PROBE], game)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = {model: pool.submit(trace, args.emulator.resolve(), game / "bottom_score.sna",
                                       game / "bottom_score.sym", ["passed", "failed"], model, 4)
                    for model in MODELS}
            for model, result in jobs.items():
                if [event["labels"] for event in result.result()["events"]] != [["passed"]]:
                    raise ValueError(f"{model}: HUD score, lives or bitmap mismatch")
                print(f"{model}: {count} complete HUD states matched on both screen banks")


if __name__ == "__main__":
    main()
