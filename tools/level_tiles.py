"""Resolve Tiled's library IDs into a 128-slot level and pack the shared art strips."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = "tileSet.tsx"
TARGETS = "destructible.tsx"
MOUNT, BLAST, TARGET = 104, 121, 124
TILE_BYTES = 48
STARS = range(64, 80)
# Six build-generated poses follow the seven editor tiles in the packed fixture art.
SHEEN_OFFSETS = (-5, -3, -1, 1, 3, 5)
SHEEN_FIRST = BLAST - len(SHEEN_OFFSETS)
# Resident frame order is the order of the beam renderer's pointer tables.
TRACKS = {"pump": (3, (10, 9, 8, 7, 6, 5, 4, 3)),
          "fanNW": (12, (12, 14, 44, 46)), "fanNE": (13, (13, 15, 45, 47)),
          "fanSW": (28, (28, 30, 60, 62)), "fanSE": (29, (29, 31, 61, 63))}
BASE_TRACKS = {root: name for name, (root, _) in TRACKS.items()}


@dataclass
class Sheet:
    image: Path
    size: tuple[int, int]
    count: int
    animations: dict


def read_sheet(path):
    root = ET.parse(path).getroot()
    image = root.find("image")
    if image is None or (root.get("tilewidth"), root.get("tileheight")) != ("8", "8"):
        raise ValueError(f"{path}: expected an 8-dot image tileset")
    w, h = (int(image.get(k)) for k in ("width", "height"))
    if (w % 8 or h % 8 or int(root.get("columns")) != w // 8 or
            int(root.get("tilecount")) != w * h // 64 or int(root.get("spacing", 0)) or int(root.get("margin", 0))):
        raise ValueError(f"{path}: expected a contiguous sheet of 8x8 tiles")
    count = w * h // 64
    if path.name == BASE and count != 128 or path.name == TARGETS and count != 7:
        raise ValueError(f"{path}: expected 128 common tiles or seven fixture/effect tiles")
    animations = {}
    for tile in root.findall("tile[animation]"):
        idx = int(tile.get("id"))
        tag = tile.find("properties/property[@name='engineAnimation']")
        track = BASE_TRACKS.get(idx) if path.name == BASE else None
        if tag is not None:
            track = tag.get("value")
        frames = tuple(int(f.get("tileid")) for f in tile.findall("animation/frame"))
        if (track not in TRACKS or len(frames) != len(TRACKS[track][1])
                or frames[TRACKS[track][1].index(TRACKS[track][0])] != idx
                or any(not 0 <= n < w * h // 64 for n in frames)
                or any(f.get("duration") != "160" for f in tile.findall("animation/frame"))):
            raise ValueError(f"{path}: animation {idx} must match a supported engine track")
        animations[idx] = track, frames
    if path.name == TARGETS:
        marked = {int(t.get("id")) for t in root.findall("tile")
                  if t.find("properties/property[@name='destructible'][@value='true']") is not None}
        if marked != set(range(4)):
            raise ValueError(f"{path}: mark the four intact fixtures as destructible")
    return Sheet(path.parent / image.get("source"), (w, h), count, animations)


def read_map(path):
    root = ET.parse(path).getroot()
    layers = root.findall("layer")
    if (root.get("width"), root.get("height")) != ("256", "6") or len(layers) != 1:
        raise ValueError(f"{path}: expected one 256 by 6 scenery layer")
    layer = layers[0].find("data")
    if layer is None or layer.get("encoding") != "csv" or layer.get("compression"):
        raise ValueError(f"{path}: save the layer as CSV")
    refs = sorted((int(t.get("firstgid")), t.attrib["source"]) for t in root.findall("tileset"))
    starts = [n for n, _ in refs]
    sheets = {name: read_sheet(path.parent / name) for _, name in refs}
    if BASE not in sheets or any(a + sheets[name].count > b for (a, name), b in zip(refs, starts[1:])):
        raise ValueError(f"{path}: missing common sheet or overlapping tilesets")
    cells = []
    for gid in map(int, layer.text.strip().split(",")):
        if gid == 0:
            cells.append((BASE, 0))
            continue
        ref = bisect_right(starts, gid) - 1
        first, name = refs[ref]
        idx = gid - first
        if ref < 0 or idx >= sheets[name].count or (name == BASE and idx >= BLAST) or (name == TARGETS and idx >= 4):
            raise ValueError(f"{path}: unsupported or flipped tile GID {gid}")
        cells.append((name, idx))
    if len(cells) != 1536:
        raise ValueError(f"{path}: expected 1536 cells")
    return cells, sheets


def layout(cells, sheets):
    """Return the map's local IDs and all resident art, including invisible dependencies."""
    used = set(cells)
    resident = {}
    slots = {}

    def bind(slot, key):
        if slot in resident and resident[slot] != key:
            raise ValueError(f"Two tiles need animation/engine slot {slot}: {key} and {resident[slot]}")
        resident[slot] = key
        slots[key] = slot

    for idx in (0, *STARS):
        bind(idx, (BASE, idx))
    if (TARGETS, 0) in used:
        for i in range(len(SHEEN_OFFSETS)):
            bind(SHEEN_FIRST + i, (TARGETS, sheets[TARGETS].count + i))
    if any(name == TARGETS for name, _ in used):
        for idx in (MOUNT, BLAST, BLAST+1, BLAST+2):
            bind(idx, (BASE, idx))
    for name, idx in sorted(used):
        key = name, idx
        if idx in sheets[name].animations:
            track, frames = sheets[name].animations[idx]
            _, dest = TRACKS[track]
            for slot, frame in zip(dest, frames, strict=True):
                bind(slot, (name, frame))
        elif name == TARGETS:
            bind(TARGET + idx, key)
    # All five LUT entries are animated, even on maps that omit a track.
    reserved = {root for root, _ in TRACKS.values()}
    for key in sorted(used - slots.keys()):
        name, idx = key
        if name == BASE and idx not in reserved and idx not in resident:
            bind(idx, key)
    free = iter(sorted(set(range(BLAST)) - reserved - resident.keys()))
    for key in sorted(used - slots.keys()):
        slot = next(free, None)
        if slot is None:
            raise ValueError(f"The 128-slot tileset is full while placing {key}")
        bind(slot, key)
    local = [slots[key] for key in cells]
    # The barrel opens with nine complete columns laid out in rows. It then
    # consumes one six-byte column at a time as the scenery scrolls.
    return bytes([local[y*256+x] for y in range(6) for x in range(9)] +
                 [local[y*256+x] for x in range(9, 256) for y in range(6)]), resident


def pack_tiles(output, levels, sheets, raw, compressor, run):
    """ZX0 each shared strip once. The manifest copies contiguous runs of required tiles."""
    groups = defaultdict(set)
    for _, resident in levels:
        for name, idx in resident.values():
            # Two atlas rows per packet, capped at the 1536-byte map scratch area.
            width = min(32, sheets[name].size[0] // 4)
            groups[name, idx // width].add(idx)
    location = {}
    strips = []
    manifest = ["packedTileLevels: dw " + ",".join(f"tileList{i}" for i in range(1, len(levels)+1))]
    for i, ((name, _), indices) in enumerate(sorted(groups.items())):
        order = sorted(indices)
        label = f"tilePacket{i}"
        path = output / "gfx" / (label + ".bin")
        path.write_bytes(b"".join(raw[name][j*TILE_BYTES:(j+1)*TILE_BYTES] for j in order))
        packed = path.with_suffix(".zx0")
        run([compressor, "-f", path, packed], output)
        size = packed.stat().st_size
        strips.append((size, f'    STORE_TILE {label},{label}Bank,{size},"gfx/{packed.name}"'))
        for index, tile in enumerate(order):
            location[name, tile] = (i, index)
    for level, (_, resident) in enumerate(levels, 1):
        manifest.append(f"tileList{level}:")
        packets = defaultdict(list)
        for dest, key in resident.items():
            i, index = location[key]
            packets[i].append((index, dest))
        for i, copies in sorted(packets.items()):
            label = f"tilePacket{i}"
            runs = []
            for src, dst in sorted(copies):
                if runs and (src, dst) == (runs[-1][0]+runs[-1][2], runs[-1][1]+runs[-1][2]):
                    runs[-1][2] += 1
                else:
                    runs.append([src, dst, 1])
            manifest.extend((f"    db {label}Bank", f"    dw {label}", f"    db {len(runs)}"))
            manifest.extend(f"    db {src},{dst},{count}" for src, dst, count in runs)
        manifest.append("    db 0")
    (output / "tile_packets.a80").write_text("".join(line+"\n" for _, line in sorted(strips, reverse=True)), encoding="ascii")
    (output / "tile_lists.a80").write_text("\n".join(manifest)+"\n", encoding="ascii")
