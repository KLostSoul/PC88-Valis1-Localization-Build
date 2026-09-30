; Consumer entry recorded in source/asm/symbols.json.
; HL is the byte cursor; screen cursor state is separate.
        ORG 02EDh
        LD E,(HL)
        INC HL
