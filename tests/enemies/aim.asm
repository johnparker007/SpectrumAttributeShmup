    device ZXSPECTRUM128
    org #8000
start:
    di
    ld sp,#bfff

    macro CHECK_BEARING targetX,targetY,direction
        ld hl,0+(targetX)+(targetY)*256-514
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
    macro CHECK_QUADRANTS dx,dy,bearing
        CHECK_BEARING 32+(dx),24+(dy),(bearing)*8
        CHECK_BEARING 32-(dy),24+(dx),((bearing)+8)*8
        CHECK_BEARING 32-(dx),24-(dy),((bearing)+16)*8
        CHECK_BEARING 32+(dy),24-(dx),((bearing)+24)*8
    endm
    CHECK_QUADRANTS -20,0,0
    CHECK_QUADRANTS -20,-4,1
    CHECK_QUADRANTS -20,-8,2
    CHECK_QUADRANTS -20,-13,3
    CHECK_QUADRANTS -20,-20,4
    CHECK_QUADRANTS -13,-20,5
    CHECK_QUADRANTS -8,-20,6
    CHECK_QUADRANTS -4,-20,7
    CHECK_BEARING 12,23,0
    CHECK_BEARING 12,22,8
    CHECK_BEARING 12,18,8
    CHECK_BEARING 12,17,16
    CHECK_BEARING 32,24,128
passed: halt
    nop
failed: halt

playerXY: dw 0
    include "aim_incoming.a80"
    align 256
aimThresholds: incbin "aim_thresholds.bin"
    savesna "aim.sna", start
