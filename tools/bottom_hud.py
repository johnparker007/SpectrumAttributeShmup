"""Adapt the pinned renderer to a static bottom character row."""

import re


def install_bottom_raster(game):
    engine = game / "engine"
    path = engine / "render.a80"
    code = path.read_bytes()
    start = code.rindex(b"renderLine46:")  # the Spectrum, rather than Pentagon, renderer
    end = start + re.search(rb"(?m)^ *dup 2 : ld \(0\),bc : edup", code[start:]).start()
    # Keep the renderer's fixed addresses and its first 46 attribute copies.
    path.write_bytes(code[:start] + b'''renderLine46:
    exx
    ld de,(renderTilesPage+1)
hudTilePage:
    out (c),d                  ; map the tile data with the normal screen still visible
    exx
    jp prepareHudTile
    defs 132-($-renderLine46),0
hudTileDone:
''' + code[end:])

    variants = (("tilesCode.a80", b"DRAW_TILE_LINES"),
                ("tilesCodeShifted.a80", b"DRAW_TILE_LINES_SHIFTED"))
    for filename, macro in variants:
        path = engine / filename
        code = path.read_bytes()
        end = code.index(b"    jp renderTiles1Exit")
        starts = [match.start() for match in re.finditer(rb"(?m)^ADDR = attrBufferStart", code[:end])]
        # Draw the first bottom-row tile early so the remaining shifted tiles
        # can still merge their edges in left-to-right order.
        second = code[starts[-3]:starts[-2]].replace(macro + b" 8", macro + b" 6")
        third = code[starts[-2]:starts[-1]].split(macro + b" 4")[0]
        fourth = code[starts[-1]:end].replace(macro + b" 8", macro + b" 6")
        path.write_bytes(code[:starts[-4]] + b"    assert TILE = HUD_PREPARED_TILE\nTILE = TILE + 1\n"
                         + second + third + macro + b" 6\nTILE = TILE + 1\n"
                         + fourth + code[end:])
