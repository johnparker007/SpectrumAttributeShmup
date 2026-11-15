    device ZXSPECTRUM128
    include "macros.asm"
ROW_BYTES equ 38

    org #8000
start:
    di
    ld sp,#bfff
    macro CHECK_AWARD initialScore,wantedScore
        ld hl,initialScore
        ld (hudScore),hl
        call hudAward
        ld hl,(hudScore)
        ld de,wantedScore
        or a
        sbc hl,de
        jp nz,failed
    endm
    CHECK_AWARD #0009,#0010
    CHECK_AWARD #0099,#0100
    CHECK_AWARD #0999,#1000
    CHECK_AWARD #9999,#9999

    ; A three-digit carry must queue each changed glyph separately, right to left.
    ld hl,#0099
    ld (hudDrawn),hl
    ld (hudScore),hl
    call hudAward
    macro CHECK_DIGIT wantedColumn
        call hudStep
        ld a,(hudColumn)
        cp wantedColumn
        jp nz,failed
        dup 8 : call hudStep : edup
    endm
    CHECK_DIGIT HUD_DIGIT_RIGHT
    CHECK_DIGIT HUD_DIGIT_RIGHT-1
    CHECK_DIGIT HUD_DIGIT_RIGHT-2
    call hudStep
    ld a,(hudPending)
    or a
    jp nz,failed
passed: halt
    nop                        ; ZEsarUX exposes the HALT fall-through PC
failed: halt

attrPointer: dw #9000
    include "score_hud.a80"
    savesna "score_arithmetic.sna", start
