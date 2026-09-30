@ Extended-ROM probe. Walks the check table that make-test-rom.py appends after the code,
@ counts failures in r7 and the first failing entry index in r6, then exits with `swi 0xFE`
@ (mgba-rom-test -S 0xFE -R r7).
@
@ Every ROM word outside this code holds its own file offset, so a read through a wrong
@ mapping (a mirror, a wrap, a truncation) returns a different number, never a plausible one.

	.arm
	.section .text
	.global _start
_start:
	b entry
	.space 0xC0 - 4          @ cartridge header, filled in by gbafix

entry:
	ldr r4, =table
	mov r7, #0               @ failures
	mvn r6, #0               @ first failing index (-1 = none)
	mov r5, #0               @ index

next:
	ldr r0, [r4], #4         @ kind
	cmn r0, #1
	beq done
	ldr r1, [r4], #4         @ address
	ldr r2, [r4], #4         @ expected value (or second address for kind 6)
	cmp r0, #0
	beq k_word
	cmp r0, #1
	beq k_half
	cmp r0, #2
	beq k_byte
	cmp r0, #3
	beq k_dma
	cmp r0, #4
	beq k_cpuset
	cmp r0, #6
	beq k_mirror
	cmp r0, #7
	beq k_exec
	b fail                   @ unknown kind

k_exec:                      @ call code that runs straight across a 16 MiB boundary; it must set r3 = 0x5A
	mov r3, #0               @ (the bytes a wrapped fetch would reach set r3 = 0xEE instead)
	mov lr, pc
	bx r1
	cmp r3, #0x5A
	bne fail
	b pass

k_word:                      @ 32-bit CPU load
	ldr r3, [r1]
	cmp r3, r2
	bne fail
	b pass

k_half:                      @ 16-bit CPU load
	ldrh r3, [r1]
	cmp r3, r2
	bne fail
	b pass

k_byte:                      @ 8-bit CPU load
	ldrb r3, [r1]
	cmp r3, r2
	bne fail
	b pass

k_dma:                       @ DMA3, 4 words, immediate, into EWRAM
	ldr r0, =0x02000000
	mov r3, #0
	str r3, [r0]
	str r3, [r0, #4]
	str r3, [r0, #8]
	str r3, [r0, #12]
	ldr r3, =0x040000D4
	str r1, [r3]             @ DMA3SAD
	str r0, [r3, #4]         @ DMA3DAD
	ldr r1, =0x84000004      @ enable | 32-bit | count 4
	str r1, [r3, #8]
	nop
	nop
	b compare4

k_cpuset:                    @ BIOS CpuSet, 4 words, 32-bit copy, into EWRAM
	mov r0, r1               @ source
	ldr r1, =0x02000000      @ destination
	mov r3, #0
	str r3, [r1]
	str r3, [r1, #4]
	str r3, [r1, #8]
	str r3, [r1, #12]
	stmfd sp!, {r2}
	mov r2, #4
	orr r2, r2, #0x04000000  @ 32-bit units
	swi 0x0B0000
	ldmfd sp!, {r2}
	ldr r0, =0x02000000
	b compare4

compare4:                    @ EWRAM[0..3] must be expected, +4, +8, +12
	mov r1, #0
1:	ldr r3, [r0, r1, lsl #2]
	add r12, r2, r1, lsl #2
	cmp r3, r12
	bne fail
	add r1, r1, #1
	cmp r1, #4
	bne 1b
	b pass

k_mirror:                    @ two addresses must read the same word
	ldr r3, [r1]
	ldr r12, [r2]
	cmp r3, r12
	bne fail
	b pass

fail:
	add r7, r7, #1
	cmn r6, #1
	moveq r6, r5
pass:
	add r5, r5, #1
	b next

done:
	swi 0xFE
1:	b 1b

	.ltorg
	.balign 4
table:                       @ appended by make-test-rom.py
