    device ZXSPECTRUM128
    org #8000
    define LIVE_SHMUP
    define OVERLAY_MOTION
PLAYER_PAIRS equ 5
PLAYER_PAIR_GAP equ 4

start:
    di
    ld sp,#bfff

    macro CHECK_PAIR shotX,boxX,firstY,secondY,firstFlag,secondFlag
        ld hl,10*256+shotX
        ld (player_pairs),hl
        ld hl,firstY*256+boxX
        ld (enemy_boxes),hl
        ld hl,secondY*256+boxX
        ld (enemy_boxes+2),hl
        call collisionInit
        call collisionEnemy
        call collisionEnemy
        ld hl,(collision_actual)
        ld a,l
        cp firstFlag
        jp nz,failed
        ld a,h
        cp secondFlag
        jp nz,failed
        ld a,(player_pairs)
        cp #ff
        jp nz,failed
    endm

    CHECK_PAIR 13,12,6,14,#ff,0  ; Upper shot hits, lower shot cannot hit the next ship.
    CHECK_PAIR 13,12,14,6,#ff,0  ; Lower shot hits, upper shot cannot hit the next ship.
    CHECK_PAIR 13,12,15,7,0,#ff  ; The first ship misses the pair.
    CHECK_PAIR #ff,0,10,10,0,0   ; A spent pair cannot wrap into a hit at the left edge.

    macro CHECK_INCOMING shotX,shotY,expectedFlag
        ld hl,shotY*256+shotX
        ld (enemy_positions),hl
        call collisionInit
        ld a,(player_hit)
        cp expectedFlag
        jp nz,failed
    endm

    ld hl,10*256+13              ; ship X=12, inset hitbox starts at X=13
    ld (player_box),hl
    CHECK_INCOMING 12,12,0
    CHECK_INCOMING 16,12,0
    CHECK_INCOMING 13,10,#ff
    CHECK_INCOMING 15,14,#ff
    CHECK_INCOMING 14,9,0
    CHECK_INCOMING 14,15,0
passed: halt
    nop
failed: halt

player_pairs: dup PLAYER_PAIRS : db #ff,0 : edup
enemy_boxes: defs 4
enemy_positions: defs 6,#ff
player_box: dw 96
    include "fixed_collision.a80"
    savesna "player_pairs.sna", start
