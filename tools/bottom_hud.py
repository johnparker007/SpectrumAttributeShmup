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
        # The final four tiles are on the bottom tile row. Finish the first
        # three on this pass. Tile 48 now runs before the first visible swap.
        first = code[starts[-4]:starts[-2]].replace(macro + b" 8", macro + b" 6")
        third = code[starts[-2]:starts[-1]].split(macro + b" 4")[0]
        path.write_bytes(code[:starts[-4]] + first + third + macro + b" 6\n"
                         b"TILE = TILE + 2\n" + code[end:])
