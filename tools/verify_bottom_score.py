"""Check all eight HUD scanlines on both screens, including bonus and restart boundaries."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile

from trace_zesarux import trace
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run

PROBE = Path(__file__).resolve().parents[1] / "tests/hud/bottom_score.asm"


def bitmap(font, level, score, lives):
    text = f"LEVEL {level}".ljust(26) + f"{score:6d}"
    image = bytearray(font[8 * (ord(char) - 32) + y] for y in range(8) for char in text)
    for n in range(lives):
        for y, row in enumerate(("00000", "01000", "01110", "11111", "01110", "01000", "00000", "00000")):
            for dx, pixel in enumerate(row):
                if pixel == "1":
                    x = 64 + 6*n + dx
                    image[32*y + x//8] |= 0x80 >> (x % 8)
    return image


def build_cases(game):
    font = (game / "font/arcade-8.bin").read_bytes()
    images, cases = bytearray(), []

    def check(level, score, lives):
        cases.extend((f"ld hl,expectedImages+{len(images)}", f"ld bc,#{score // 100:04d}",
                      f"ld a,{lives}", "call checkHUD"))
        images.extend(bitmap(font, level, score, lives))

    previous = 0
    # Include all extra lives, consecutive awards across boundaries, and
    # the non-award at 50k. Each actual +100 passes through the enemy kill path's counter.
    milestones = range(20000, 1000000, 50000)
    scores = sorted({0, 100, 900, 1000, 9900, 10000, 19900, 20100, 50000, 69900,
                     100000, 101000, 999900, *milestones})
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
    cases.extend(("ld bc,200", "call awardMany", "call hudStep", "call hudStep",
                  "ld a,1", "ld (player_hit),a", "call updatePlayerLife"))
    check(16, 20000, 3)
    cases.extend(("call resetEncounter", "call hudAward", "call hudStep", "call resetEncounter"))
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
