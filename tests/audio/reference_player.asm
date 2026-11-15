; Run the compiled Blokius PT3 player once per video interrupt.
    device ZXSPECTRUM128
    page 0
playback_init equ 55000
playback_tick equ 55005
    include "tick_loop.a80"

    org playback_init
    incbin "player_55000.bin"
    org 57158
    incbin "song_57158.bin"

    savesna "reference_player.sna",start
