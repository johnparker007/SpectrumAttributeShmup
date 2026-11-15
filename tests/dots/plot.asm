; Standalone benchmark. The host supplies in-bounds coordinates and the
; expected full buffers, including guard bytes outside the visible viewport.
    device ZXSPECTRUM128
    org #8000

ROW_BYTES equ 38
HEIGHT equ 48
VIEWPORT_OFFSET equ 7*ROW_BYTES+4
BUFFER_SIZE equ 56*ROW_BYTES
CYAN equ 5
YELLOW equ 6

start:
    di
    ld sp,#bff0

players_begin:
    ld ix,player_positions
    ld b,9
.loop:
    call dot_address
    jr c,.split

    ; Aligned 2x1 shot. Retain BRIGHT and FLASH from the pair underneath.
    ld a,(hl)
    and #c0
    or CYAN | (CYAN << 3)
    ld (hl),a
    jr .next
.split:
    ; Odd starting X spans the paper field and the next byte's ink field.
    ld a,(hl)
    and #c7
    or CYAN << 3
    ld (hl),a
    inc hl
    ld a,(hl)
    and #f8
    or CYAN
    ld (hl),a
.next:
    inc ix
    inc ix
    djnz .loop
players_end:
    ld de,expected_players
    call verify_buffer
    jp nz,failed

enemies_begin:
    ld ix,enemy_positions
    ld b,ENEMY_COUNT
.loop:
    call dot_address
    jr c,.paper
    ld a,(hl)
    and #f8
    or YELLOW
    ld (hl),a
    jr .next
.paper:
    ld a,(hl)
    and #c7
    or YELLOW << 3
    ld (hl),a
.next:
    inc ix
    inc ix
    djnz .loop
enemies_end:
    ld de,expected_enemies
    call verify_buffer
    jp nz,failed

passed:
    jp idle
failed:
    jp idle
idle:
    halt
    jr idle

; Input IX -> x,y. Return HL = active attrPointer + 38*y + floor(x/2).
; Carry is set for paper (odd X). Keep B for the outer loop's count.
dot_address:
    ld a,(ix+1)
    add a,a
    ld l,a
    ld h,high row_offsets
    ld e,(hl)
    inc l
    ld d,(hl)
    ld hl,(viewport)
    add hl,de
    ld a,(ix)
    srl a
    ld e,a
    ld d,0
    ex af,af'
    add hl,de
    ex af,af'
    ret

verify_buffer:
    ld hl,buffer
    ld bc,BUFFER_SIZE
.loop:
    ld a,(de)
    cpi
    ret nz
    inc de
    jp pe,.loop
    ret

    align 256
row_offsets:
    dup HEIGHT, row
        dw ROW_BYTES*row
    edup

viewport: dw buffer+VIEWPORT_OFFSET
player_positions: incbin "player_positions.bin"
enemy_positions: incbin "enemy_positions.bin"
buffer: incbin "initial.bin"
expected_players: incbin "expected_players.bin"
expected_enemies: incbin "expected_enemies.bin"

    assert $<#bff0
    savesna "plot.sna",start
