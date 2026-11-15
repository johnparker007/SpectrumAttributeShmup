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
    include "packed_plot.a80"

start:
    di
    ld sp,#bff0

players_begin:
    PLOT_PLAYERS
players_end:
    ld de,expected_players
    call verify_buffer
    jp nz,failed

enemies_begin:
    PLOT_ENEMIES
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

    DOT_ADDRESS

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

    DOT_ROW_OFFSETS

viewport: dw buffer+VIEWPORT_OFFSET
player_positions: incbin "player_positions.bin"
enemy_positions: incbin "enemy_positions.bin"
buffer: incbin "initial.bin"
expected_players: incbin "expected_players.bin"
expected_enemies: incbin "expected_enemies.bin"

    assert $<#bff0
    savesna "plot.sna",start
