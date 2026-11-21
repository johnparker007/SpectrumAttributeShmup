"""Capture a two-tone Vortex PT3, retaining its intro and native loop point."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from struct import pack as header
from tempfile import TemporaryDirectory

from benchmark_ay import PROBE, extract_music, record
from profile_blokius import ARCHIVE
from verify_ay_phrases import pack, unpack
from verify_ay_stream import encode
from verify_zesarux_raster import run


def music_rows(capture):
    ticks = capture["ticks"]
    first_wrap = next(i for i, tick in enumerate(ticks) if "loop" in tick)
    rows = []
    for tick in ticks:
        state = {w["register"]: w["value"] for w in tick["writes"]}
        if state[10] or (state[8] | state[9]) & 16 or state[7] & 24 != 24:
            raise ValueError("Use two tone channels A/B with software volume and leave C silent")
        # Explicitly disable C in the music mixer. The effects layer opens its
        # tone/noise gates after the music tick, including during the handoff.
        state[7] |= 0x24
        rows.append([(r, state[r]) for r in (0, 1, 2, 3, 7, 8, 9)])
    loop = rows[first_wrap:]
    intro = first_wrap - len(loop)
    if intro >= 0 and rows[intro:first_wrap] == loop:
        return rows[:first_wrap], intro
    return rows, first_wrap


def pack_music(rows, loop_tick):
    wire = []
    previous = {}
    last = dict(rows[-1])
    for tick, row in enumerate(rows):
        # At the loop head, keep changes from both possible preceding states.
        changes = [(r, v) for r, v in row
                   if previous.get(r) != v or (tick == loop_tick and last[r] != v)]
        wire.append(encode([changes]))
        previous.update(row)
    # Favour longer phrases to fit the recipe beside the boss art in bank 0.
    recipe, literal, overflow = pack(wire, min_reuse_bytes=24)
    if overflow:
        raise ValueError("Boss audio exceeds one literal bank")
    # A loop may begin in the middle of a reused run. Split its descriptor
    # without duplicating the underlying tick packets.
    entries = bytearray()
    start = 0
    for lo, hi, count in zip(recipe[::3], recipe[1::3], recipe[2::3], strict=True):
        offset = lo + 256 * hi
        end = start + count
        if start <= loop_tick < end:
            prefix = loop_tick - start
            if prefix:
                entries.extend(header("<HB", offset, prefix))
                offset += sum(map(len, wire[start:loop_tick]))
                count -= prefix
            loop_offset = len(entries)
        entries.extend(header("<HB", offset, count))
        start = end
    assert list(unpack(entries, [literal])) == wire
    # The diagnostic decoder expects one initialization descriptor first.
    assert list(unpack(entries[:3] + entries[loop_offset:], [literal]))[1:] == wire[loop_tick:]
    return header("<HH", len(entries), loop_offset) + entries + literal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pt3", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=100, help="wall-clock budget for two passes of the song")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="boss-music-") as tmp:
        game = Path(tmp)
        extract_music(ARCHIVE, game, None, args.pt3)
        run([args.assembler.resolve(), "--sym=reference_player.sym", PROBE], game)
        with ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(record, args.emulator.resolve(), game, model, args.seconds, True, loops=2)
                    for model in ("P2", "P2A41")]
            first, second = (music_rows(job.result()) for job in jobs)
    if first != second:
        raise ValueError("AY music differs between models")
    rows, loop_tick = first
    data = pack_music(rows, loop_tick)
    args.output.write_bytes(data)
    print(f"{loop_tick} intro ticks, {len(rows) - loop_tick} loop ticks, {len(data)-4} resident bytes")


if __name__ == "__main__":
    main()
