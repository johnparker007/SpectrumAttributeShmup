; Read-only hitbox probes over the two colour layers and their coordinates.
; Fixtures contain fifteen 5x5 enemy boxes followed by one 5x5 player box.
    device ZXSPECTRUM128
    org #8000

ROW_BYTES equ 38
VIEWPORT_OFFSET equ 7*ROW_BYTES+4
BOX_COUNT equ 16
BOX_WIDTH equ 5

    macro CHECK_BOXES check_cyan, check_yellow
    ld ix,boxes
    ld iy,results
    ld b,BOX_COUNT-1
.enemy:
    push bc
    call check_cyan
    ld a,0
    jr z,.write_enemy
    inc a
.write_enemy:
    ld (iy),a
    inc iy
    inc ix
    inc ix
    pop bc
    djnz .enemy
    call check_yellow
    ld a,0
    jr z,.write_player
    inc a
.write_player:
    ld (iy),a
    endm

start:
    di
    ld sp,#bff0
packed_begin:
    CHECK_BOXES probe_cyan, probe_yellow
packed_end:
    call verify_results
    jp nz,failed
coordinate_begin:
    CHECK_BOXES coordinate_cyan, coordinate_yellow
coordinate_end:
    call verify_results
    jp nz,failed
passed:
    jp idle
failed:
    jp idle
idle:
    halt
    jr idle

verify_results:
    ld hl,results
    ld de,expected
    ld bc,BOX_COUNT
.loop:
    ld a,(de)
    cpi
    ret nz
    inc de
    jp pe,.loop
    ret

probe_cyan:
    ld bc,cyan_layer+VIEWPORT_OFFSET
    call box_address
    ld d,high cyan_lut
    jr probe_fields
probe_yellow:
    ld bc,yellow_layer+VIEWPORT_OFFSET
    call box_address
    ld d,high yellow_lut
probe_fields:
    ld bc,ROW_BYTES-2
    jr c,probe_odd

    ; LUT bits 0 and 1 mark matching ink and paper in an attribute byte.
    macro MATCH_FIELD mask
    ld e,(hl)
    ld a,(de)
    if mask=3
        or a
    else
        and mask
    endif
    ret nz
    endm

    macro PROBE_ROWS first, last
    dup BOX_WIDTH
        MATCH_FIELD first
        inc hl
        MATCH_FIELD 3
        inc hl
        MATCH_FIELD last
        add hl,bc
    edup
    ret                         ; Z from the final field test means miss
    endm

    PROBE_ROWS 3,1
probe_odd:
    PROBE_ROWS 2,3

; BC = active viewport address, IX -> box top left. Preserves IY.
; Returns HL = attribute byte, carry for odd X.
box_address:
    ld a,(ix+1)
    add a,a
    ld l,a
    ld h,high row_offsets
    ld e,(hl)
    inc l
    ld d,(hl)
    ex de,hl
    add hl,bc
    ld a,(ix)
    srl a
    ld e,a
    ld d,0
    ex af,af'
    add hl,de
    ex af,af'
    ret

    macro CHECK_COORDINATES width
.loop:
    ld a,(de)
    sub (ix)
    if width=2
        inc a                   ; width two can also start one dot left
    endif
    cp BOX_WIDTH+width-1
    jr nc,.next
    inc de
    ld a,(de)
    sub (ix+1)
    cp BOX_WIDTH
    jr c,.hit
    dec de
.next:
    inc de
    inc de
    djnz .loop
    xor a
    ret
.hit:
    or 1
    ret
    endm

coordinate_cyan:
    ld de,player_shots
    ld b,9
    CHECK_COORDINATES 2
coordinate_yellow:
    ld de,enemy_shots
    ld b,ENEMY_COUNT
    CHECK_COORDINATES 1

    align 256
row_offsets:
    dup 48, row
        dw ROW_BYTES*row
    edup
    align 256
cyan_lut: incbin "cyan_lut.bin"
yellow_lut: incbin "yellow_lut.bin"
cyan_layer: incbin "expected_players.bin"
yellow_layer: incbin "expected_enemies.bin"
boxes: incbin "boxes.bin"
player_shots: incbin "player_positions.bin"
enemy_shots: incbin "enemy_positions.bin"
expected: incbin "expected.bin"
results: block BOX_COUNT

    assert $<#bff0
    savesna "collision.sna",start
