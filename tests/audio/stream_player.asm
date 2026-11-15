; Each tick is a sequence of register/value pairs, terminated by #FF.
    device ZXSPECTRUM128
    page 0
playback_init equ playback_tick
    include "tick_loop.a80"

    org #8100
playback_tick:
    ld hl,(cursor)
    ld c,#fd
stream_next:
    ld a,(hl)
    inc hl
    cp #ff
    jr z,stream_complete
    ld b,#ff
select_register:
    out (c),a
    ld b,#bf
    ld a,(hl)
    inc hl
write_register:
    out (c),a
    jr stream_next
stream_complete:
    ld a,h
    cp high stream_end
    jr nz,stream_store
    ld a,l
    cp low stream_end
    jr nz,stream_store
    ld hl,stream
stream_store:
    ld (cursor),hl
    ret

cursor: dw stream
stream: incbin "stream.bin"
stream_end:
    assert $<#bd00
    savesna "stream_player.sna",start
