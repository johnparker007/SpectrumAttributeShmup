"""Read the AY chip through bonus awards, boss impacts, player deaths and restart."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile

from bonus_chime import read_bonus_rows
from trace_zesarux import trace
from verify_ay_phrases import unpack
from verify_bottom_score import first_bonus_points
from verify_scenery import FLAGS, MODELS
from verify_zesarux_raster import run

PROBE = Path(__file__).resolve().parents[1] / "tests/audio/bonus_chime.asm"


def expected_audio(game):
    gfx = game / "gfx"
    music_dir = PROBE.parents[2] / "game/music"
    song = iter(unpack((music_dir / "star-force-recipe.bin").read_bytes(),
                       [(music_dir / "star-force-literal.bin").read_bytes()]))
    shot = (gfx / "shot-sound.bin").read_bytes()
    explosion = (gfx / "explosion-noise.bin").read_bytes()
    notes = [(lo, hi, vol) for ticks, lo, hi, vol in read_bonus_rows(music_dir / "extra-ship.vt2")
             for _ in range(ticks)]
    window = max(len(notes), len(explosion) // 2, len(shot) // 3) + 4
    music, chip = [0] * 14, [0] * 14
    output = bytearray()
    for tick in range(-1, 4 + window + 3 + 4 + 3):
        packet = next(song)
        for register, value in zip(packet[:-1:2], packet[1:-1:2], strict=True):
            music[register] = chip[register] = value
        if tick < 0:
            continue
        offset = tick - 4
        chime_tick = offset if offset < window else offset - window
        if 0 <= chime_tick < len(notes) and offset < window + 3:
            chip[2], chip[3], chip[9] = notes[chime_tick]
        else:
            chip[2], chip[3], chip[9] = music[2], music[3], music[9]
        shot_volume = noise_volume = 0
        if 0 <= offset < len(shot) // 3:
            chip[4], chip[5], shot_volume = shot[offset*3:offset*3+3]
        if 0 <= offset < len(explosion) // 2:
            chip[6], noise_volume = explosion[offset*2:offset*2+2]
        chip[7] = (music[7] | 36) & ~(4 * bool(shot_volume) + 32 * bool(noise_volume))
        chip[10] = max(shot_volume, noise_volume)
        output.extend(chip[:11])
    return output, window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("game", "assembler", "emulator"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blokius-chime-") as tmp:
        game = Path(tmp) / "game"
        shutil.copytree(args.game, game)
        expected, window = expected_audio(game)
        (game / "expected_sound.bin").write_bytes(expected)
        hundreds = first_bonus_points(game) // 100
        run([args.assembler.resolve(), *("-D"+flag+"=1" for flag in FLAGS),
             f"-DBONUS_TEST_TICKS={window}", f"-DBEFORE_FIRST_TWO=#{hundreds-2:04d}",
             f"-DBEFORE_FIRST_ONE=#{hundreds-1:04d}", "--sym=bonus_chime.sym", PROBE], game)
        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(trace, args.emulator.resolve(), game / "bonus_chime.sna",
                                game / "bonus_chime.sym", ["passed", "failed"], model, 3) for model in MODELS]
            for model, job in zip(MODELS, jobs):
                if [e["labels"] for e in job.result()["events"]] != [["passed"]]:
                    raise ValueError(f"{model}: incorrect AY registers or collision sound")
                print(f"{model}: {len(expected)//11} bonus-mix ticks matched across all three AY channels; "
                      "armour, ram, boss kill and player bullet-death sounds passed")


if __name__ == "__main__":
    main()
