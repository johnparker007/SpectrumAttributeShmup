; One 25 Hz update of three three-way volleys and a fixed enemy pool.
; X=#ff identifies an inactive slot. Coordinates are logical dots.
    device ZXSPECTRUM128
    org #8000

    include "motion_step.a80"

STATE_SIZE equ ENEMY_COUNT*3+9+18

start:
    di
    ld sp,#bff0
players_begin:
    MOVE_VOLLEYS
players_end:
    nop
enemies_begin:
    MOVE_ENEMIES
enemies_end:
    ld hl,enemy_records
    ld de,expected
    ld bc,STATE_SIZE
.check:
    ld a,(de)
    cpi
    jp nz,failed
    inc de
    jp pe,.check
passed:
    jp idle
failed:
    jp idle
idle:
    halt
    jr idle

    MOTION_WRITE_SHOT
    align 256
trajectories: incbin "trajectories.bin"
enemy_records: incbin "initial.bin"
volleys equ enemy_records+ENEMY_COUNT*3
player_shots equ volleys+9
expected: incbin "expected.bin"
    assert $<#bff0
    savesna "motion.sna",start
