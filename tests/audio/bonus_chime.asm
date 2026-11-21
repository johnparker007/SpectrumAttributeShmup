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
    ld hl,#1999
    ld (hudScore),hl
    call hudAward               ; 200,000
    ld bc,3 : call checkTicks
    call resetEncounter         ; interrupt the second chime
    ld bc,4 : call checkTicks
    ld hl,BEFORE_FIRST_ONE : ld (hudScore),hl
    call hudAward
    call resetEncounter         ; cancel before the first AY tick, too
    ld bc,3 : call checkTicks

    ; A surviving boss hit starts the short burst. A second hit restarts it.
    ld a,4 : ld (bossHealth),a
    ld a,1 : ld (collision_actual),a
    call bossStep
    ld ix,impactNoise : ld b,1 : call checkNoise
    call bossStep
    ld ix,impactNoise : ld b,(impactNoiseEnd-impactNoise)/2 : call checkNoise
    call checkQuiet

    ; A ram damages both ships. The surviving boss's hit must leave the
    ; player's full explosion audible for all of its remaining ticks.
    call startImpactSound
    ld ix,impactNoise : ld b,1 : call checkNoise
    ld hl,(enemy_boxes) : ld (player_box),hl
    call checkPlayerContact
    call updatePlayerLife
    call bossStep
    ld a,(playerLives) : cp STARTING_LIVES-1 : jp nz,failed
    ld ix,explosionNoise : ld b,(explosionNoiseEnd-explosionNoise)/2 : call checkNoise
    call checkQuiet
    ; The next hit destroys the boss and gets its own full explosion.
    call bossStep
    ld a,(bossHealth) : or a : jp nz,failed
    ld ix,explosionNoise : ld b,(explosionNoiseEnd-explosionNoise)/2 : call checkNoise
    call checkQuiet

    ; An incoming bullet overlaps the player on two successive checks.
    ; The protected frame is quiet. The vulnerable frame takes the last life.
    call resetEncounter
    ld hl,PLAYER_START : ld (player_box),hl : ld (enemy_records),hl
    ld a,1 : ld (invincibleTicks),a : ld (playerLives),a
    call collisionInit : call updatePlayerLife : call checkQuiet
    call collisionInit : call updatePlayerLife
    ld a,(playerLives) : or a : jp nz,failed
    ld ix,explosionNoise : ld b,(explosionNoiseEnd-explosionNoise)/2 : call checkNoise
    call checkQuiet
passed:
    halt
    nop
failed:
    halt

checkNoise:
    push bc : push ix : call soundTick : pop ix
    ld bc,#fffd : ld a,6 : out (c),a : in a,(c)
    cp (ix) : jp nz,failed
    ld a,10 : out (c),a : in a,(c)
    cp (ix+1) : jp nz,failed
    ; When volume is nonzero, C's noise gate must also be enabled.
    or a : jr z,.next
    ld a,7 : out (c),a : in a,(c) : bit 5,a : jp nz,failed
.next:
    inc ix : inc ix : pop bc : djnz checkNoise
    ret

checkQuiet:
    call soundTick
    ld bc,#fffd : ld a,10 : out (c),a : in a,(c)
    or a : jp nz,failed
    ret

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
