; Read the actual AY chip after each production tick. The SNA carries the
; literal bank at physical page 1 on either model (the TAP loader remaps it).
    include "main.asm"
    page 0
    org sourceTileMap
bonusProbe:
    di
    ld sp,24499
    SET_PAGE 0
    call resetEncounter
    call soundTickBody
    ld ix,expectedSound
    ld hl,BEFORE_FIRST_TWO
    ld (hudScore),hl
    call hudAward               ; ordinary kill, one short of the first award
    ld bc,4 : call checkTicks
    call hudAward               ; first bonus
    call startShotSound
    call startExplosionSound
    ld bc,BONUS_TEST_TICKS : call checkTicks
    ld hl,#0699
    ld (hudScore),hl
    call hudAward               ; 70,000
    ld bc,3 : call checkTicks
    call resetEncounter         ; interrupt the second chime
    ld bc,4 : call checkTicks
    ld hl,BEFORE_FIRST_ONE : ld (hudScore),hl
    call hudAward
    call resetEncounter         ; cancel before the first AY tick, too
    ld bc,3 : call checkTicks
passed:
    halt
    nop
failed:
    halt

checkTicks:
    push bc
    push ix
    call soundTick
    pop ix
    ld bc,#fffd
    ld e,0
.register:
    out (c),e
    in a,(c)
    cp (ix)
    jp nz,failed
    inc ix
    inc e
    ld a,e
    cp 11
    jr nz,.register
    pop bc
    dec bc
    ld a,b
    or c
    jr nz,checkTicks
    ret
    assert $ <= loadLevel
    org #4000
expectedSound: incbin "expected_sound.bin"
    assert $ <= #5b00
    savesna "bonus_chime.sna",bonusProbe
