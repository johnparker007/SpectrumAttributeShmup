    device ZXSPECTRUM128
    org #8000
start:
    di
    ld sp,#bfff

    macro CHECK_BEARING targetX,targetY,direction
        ld hl,targetX+targetY*256-514
        ld (playerXY),hl
        ld bc,32*256+24
        call aimIncoming
        ld a,d
        cp direction
        jp nz,failed
        ld a,b
        cp 32
        jp nz,failed
        ld a,c
        cp 24
        jp nz,failed
    endm
    CHECK_BEARING 12,24,0
    CHECK_BEARING 52,24,64
    CHECK_BEARING 32,4,168
    CHECK_BEARING 32,44,176
    CHECK_BEARING 16,8,40
    CHECK_BEARING 48,8,104
    CHECK_BEARING 16,40,48
    CHECK_BEARING 48,40,112
    CHECK_BEARING 12,14,0
    CHECK_BEARING 22,4,168
passed: halt
    nop
failed: halt

playerXY: dw 0
    include "aim_incoming.a80"
    savesna "aim.sna", start
