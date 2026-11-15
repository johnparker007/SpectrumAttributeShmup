; Paint the bank 5 screen red and bank 7 cyan, then switch partway through
; a paper scanline. Keep the code, stack and interrupt vector in bank 2.
    device ZXSPECTRUM128
    page 0
    org #8000

    ifndef DELAY_LOOPS
DELAY_LOOPS equ 1080
    endif

start:
    di
    ld sp,#bd00
    xor a
    out (#fe),a

    ld hl,#5800
    ld a,#50                   ; bright red paper
    call fill_attrs

    ld bc,#7ffd
    ld a,#17                   ; page bank 7 into #c000, display bank 5
    out (c),a
    ld hl,#d800
    ld a,#68                   ; bright cyan paper
    call fill_attrs

    ld hl,#be00
    ld de,#be01
    ld bc,256
    ld (hl),#bd
    ldir
    ld a,#be
    ld i,a
    im 2
    ei

next_frame:
    halt
    ld bc,#7ffd
    ld a,#10                   ; display bank 5
    out (c),a
    ld bc,DELAY_LOOPS          ; 26 T-states per iteration, 5 fewer on exit
delay:
    dec bc
    ld a,b
    or c
    jr nz,delay
    ld bc,#7ffd
    ld a,#18                   ; display bank 7
    out (c),a
    jr next_frame

fill_attrs:
    ld (hl),a
    ld d,h
    ld e,l
    inc de
    ld bc,767
    ldir
    ret

    org #bdbd
interrupt:
    ei
    ret

    savesna "shadow_screen.sna",start
