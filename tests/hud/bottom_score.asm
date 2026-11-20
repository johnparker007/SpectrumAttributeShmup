; Include the production image, then use its unused level buffer for this
; snapshot-only driver. The production HUD and bank-switching code run in place.
    include "main.asm"
    page 6
    org #c000
expectedImages: incbin "hud_expected.bin"
    assert $ <= #10000
    page 0
    org sourceTileMap
hudProbe:
    di
    ld sp,24499
    SET_PAGE 0
    ld a,15                     ; check the widest level label alongside all 23 ships
    ld (selectedLevel),a
    call gameInit
    ; Return after the production dot pool finishes, before the HUD/raster
    ; continuation. Plot both parities over nonblack neighbours across wrap.
    ld a,#c9
    ld (overlayEnd),a
    ld hl,attrBuffer
    ld (attrPointer),hl
    ld hl,10+5*256 : ld (enemy_records),hl
    ld hl,13+5*256 : ld (enemy_records+3),hl
    ld a,#fe
    ld (gameTick),a
    dup 4,phase
        ld hl,#cac9
        ld (attrBuffer+5*ROW_BYTES+5),hl
        call drawIncomingDots
        ld hl,(attrBuffer+5*ROW_BYTES+5)
        ld de,(#c8 | (6+(phase%2))) + 256*(#c2 | ((6+(phase%2))*8))
        or a
        sbc hl,de
        jp nz,failed
        ld hl,gameTick
        inc (hl)
    edup
    include "hud_cases.asm"
passed:
    halt
    nop
failed:
    halt

awardMany:
    call hudAward
    dec bc
    ld a,b
    or c
    jr nz,awardMany
    ret

; A = expected lives, BC = packed score, HL = expected image in bank 6.
checkHUD:
    ld de,playerLives
    ex de,hl
    cp (hl)
    jp nz,failed
    ld hl,(hudScore)
    or a
    sbc hl,bc
    jp nz,failed
    push de
.flush:
    call hudStep
    ld a,(hudPending)
    or a
    jr nz,.flush
    ld a,(hudRow)
    cp 8
    jr nz,.flush
    pop hl
    SET_PAGE 6
    ld de,expectedRow
    ld bc,256
    ldir
    ld d,HUD_BITMAP_HIGH
    call compareBitmap
    SET_PAGE 7
    ld d,HUD_BITMAP_HIGH+#80
    call compareBitmap
    SET_PAGE 0
    ret

compareBitmap:
    ld hl,expectedRow
    ld c,8
.row:
    ld e,HUD_BITMAP_LOW
    ld b,32
.cell:
    ld a,(de)
    cp (hl)
    jp nz,failed
    inc hl
    inc e
    djnz .cell
    inc d
    dec c
    jr nz,.row
    ret
expectedRow: defs 256
    assert $ <= loadLevel
    savesna "bottom_score.sna",hudProbe
