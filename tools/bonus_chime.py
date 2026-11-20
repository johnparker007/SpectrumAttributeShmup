"""Bake the bonus VT2's fixed-volume, tone-only B track for the gameplay mixer."""

import re

from verify_ay_phrases import packets


NOTES = "C- C# D- D# E- F- F# G- G# A- A# B-".split()
# Vortex Tracker's ASM note table (table 2, PT3.5+), C-1 through B-8.
PERIODS = (
    3344, 3157, 2980, 2812, 2655, 2506, 2365, 2232, 2107, 1989, 1877, 1772,
    1672, 1578, 1490, 1406, 1327, 1253, 1182, 1116, 1053, 994, 939, 886,
    836, 789, 745, 703, 664, 626, 591, 558, 527, 497, 469, 443,
    418, 395, 372, 352, 332, 313, 296, 279, 263, 249, 235, 221,
    209, 197, 186, 176, 166, 157, 148, 140, 132, 124, 117, 111,
    105, 99, 93, 88, 83, 78, 74, 70, 66, 62, 59, 55,
    52, 49, 47, 44, 41, 39, 37, 35, 33, 31, 29, 28,
    26, 25, 23, 22, 21, 20, 18, 17, 16, 15, 14, 13,
)


def tag_music_bank(data):
    """Flag B's three registers and the shared mixer for the live packet reader."""
    result = bytearray()
    for packet in packets(data):
        for reg, value in zip(packet[:-1:2], packet[1:-1:2], strict=True):
            if reg in (2, 3, 7, 9):
                reg |= 16
            result.extend((reg, value))
        result.append(255)
    return bytes(result)


def bake_bonus(path):
    rows = read_bonus_rows(path)
    events = bytearray()
    previous = (None, None, None)
    for duration, low, high, volume in rows:
        values = (low, high, volume)
        mask = sum(1 << bit for bit in range(3) if values[bit] != previous[bit])
        events.extend((duration, mask))
        events.extend(value for bit, value in enumerate(values) if mask & (1 << bit))
        previous = values
    return bytes(events) + b"\0"


def read_bonus_rows(path):
    parts = re.split(r"^\[([^\]]+)\]\s*$", path.read_text(encoding="utf-8-sig"), flags=re.M)
    sections = {key: body.strip() for key, body in zip(parts[1::2], parts[2::2], strict=True)}
    settings = dict(line.split("=", 1) for line in sections["Module"].splitlines() if "=" in line)
    if (settings["PlayOrder"] != "L0" or settings["NoteTable"] != "2"
            or settings["Version"] != "3.7" or settings["ChipFreq"] != "1773400"
            or sections.get("Ornament0", "L0") != "L0"
            or sections["Sample1"] != "T.. +000_ +00_ F_ L"
            or sections["Sample3"] != "... +000_ +00_ 0_ L"):
        raise ValueError("Bonus chime expects pattern 0, ASM tuning, plain tone sample 1 and silent sample 3")
    speed = int(settings["Speed"])
    if not 1 <= speed <= 255:
        raise ValueError("Invalid bonus chime speed")
    rows = []
    period = volume = None
    for row in sections["Pattern0"].splitlines():
        envelope, noise, a, channel, c = row.strip().split("|")
        if (envelope, noise, a, c) != ("....", "..", "--- .... ....", "--- .... ...."):
            raise ValueError("The bonus chime only owns channel B tone and volume")
        note = re.fullmatch(r"([A-G][-#][1-8]|---) ([13.])\.\.([1-9A-F.]) \.{4}", channel)
        if not note:
            raise ValueError(f"Unsupported bonus note, instrument or effect on B: {channel}")
        if note[2] == "3":
            if not rows or note[1] == "---":
                raise ValueError("Empty bonus chime")
            return rows
        if note[1] != "---":
            pitch, octave = note[1][:2], int(note[1][-1])
            period = PERIODS[12 * (octave - 1) + NOTES.index(pitch)]
        if note[3] != ".":
            volume = int(note[3], 16)
        if period is None or volume is None or (not rows and note[2] != "1"):
            raise ValueError("Start the bonus chime with a note, sample 1 and a volume")
        values = (period & 255, period >> 8, volume)
        if rows and rows[-1][1:] == values and rows[-1][0] + speed <= 255:
            rows[-1] = (rows[-1][0] + speed, *values)
        else:
            rows.append((speed, *values))
    raise ValueError("End the bonus chime with a sample 3 note")
