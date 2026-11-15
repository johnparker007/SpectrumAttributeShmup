; Replay a recipe of 3-byte entries: virtual offset and tick count.
; Literal packets are stored in pages 0 and 1, and never cross a bank edge.
    device ZXSPECTRUM128
    page 0
playback_init equ playback_tick
    include "tick_loop.a80"

    org #8100
playback_tick:
    ld a,(ticks_left)
    or a
    jr nz,packet_ready

    ld hl,(recipe_cursor)
    ld de,recipe_end
    or a
    sbc hl,de
    jr z,recipe_wrap
    add hl,de
    jr read_phrase
recipe_wrap:
    ld hl,recipe+3               ; skip the one-tick initialization entry
read_phrase:
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld a,(hl)
    inc hl
    ld (ticks_left),a
    ld (recipe_cursor),hl
    ld a,d
    rlca
    rlca
    and 3
    or #10
    ld (literal_page),a
    set 6,d
    set 7,d
    ld (literal_cursor),de

packet_ready:
    ld a,(ticks_left)
    dec a
    ld (ticks_left),a
    ld bc,#7ffd
    ld a,(literal_page)
    out (c),a
    ld hl,(literal_cursor)
    ld c,#fd
packet_next:
    ld a,(hl)
    inc hl
    cp #ff
    jr z,packet_end
    ld b,#ff
select_register:
    out (c),a
    ld b,#bf
    ld a,(hl)
    inc hl
write_register:
    out (c),a
    jr packet_next
packet_end:
    ld (literal_cursor),hl
    ld bc,#7ffd
    ld a,#10
    out (c),a
    ret

recipe_cursor: dw recipe
literal_cursor: dw 0
literal_page: db #10
ticks_left: db 0
recipe: incbin "recipe.bin"
recipe_end:
    assert $<#bd00

    page 0
    org #c000
    incbin "literal0.bin"
    ifdef USE_BANK1
    page 1
    org #c000
    incbin "literal1.bin"
    endif
    page 0
    savesna "phrase_player.sna",start
