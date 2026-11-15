; One 25 Hz update of three three-way volleys and a fixed enemy pool.
; X=#ff identifies an inactive slot. Coordinates are logical dots.
    device ZXSPECTRUM128
    org #8000

STATE_SIZE equ ENEMY_COUNT*3+9+18

start:
    di
    ld sp,#bff0
players_begin:
    ld ix,volleys
    ld de,player_shots
    ld b,3
.next:
    ld a,(ix)
    cp 62
    jr nc,.retire
    inc a
    ld (ix),a
    ld c,a
    ld a,(ix+2)
    inc a
    ld (ix+2),a
    srl a
    ld h,a                      ; spread grows by one dot every two ticks
    ld l,(ix+1)
    ld a,l
    sub h
    call write_shot
    ld a,l
    call write_shot
    ld a,l
    add a,h
    call write_shot
    jr .advance
.retire:
    ld (ix),#ff
    ld c,#ff
    xor a
    call write_shot
    call write_shot
    call write_shot
.advance:
    inc ix
    inc ix
    inc ix
    djnz .next
players_end:
    nop
enemies_begin:
    ld hl,enemy_records
    ld d,high trajectories
    ld b,ENEMY_COUNT
.next:
    ld a,(hl)
    cp #ff
    jr z,.skip
    sub 1
    jr c,.retire_x
    ld (hl),a
    inc hl
    inc hl
    ld a,(hl)
    ld c,a
    ; Increment packed phase bits 0–2 while keeping trajectory bits 3–5.
    inc a
    xor c
    and 7
    xor c
    ld (hl),a
    ld e,a
    dec hl
    ld a,(de)
    add a,(hl)
    cp 48
    jr nc,.retire_y
    ld (hl),a
    inc hl
    inc hl
    djnz .next
    jr enemies_end
.retire_y:
    dec hl
.retire_x:
    ld (hl),#ff
.skip:
    inc hl
    inc hl
    inc hl
    djnz .next
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

; A is the candidate Y, C the shared volley X. Preserve HL and B.
write_shot:
    cp 48
    jr nc,.outside
    push af
    ld a,c
    ld (de),a
    inc de
    pop af
    ld (de),a
    inc de
    ret
.outside:
    ld a,#ff
    ld (de),a
    inc de
    xor a
    ld (de),a
    inc de
    ret

    align 256
trajectories: incbin "trajectories.bin"
enemy_records: incbin "initial.bin"
volleys equ enemy_records+ENEMY_COUNT*3
player_shots equ volleys+9
expected: incbin "expected.bin"
    assert $<#bff0
    savesna "motion.sna",start
