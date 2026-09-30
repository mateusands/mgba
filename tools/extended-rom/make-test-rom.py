#!/usr/bin/env python3
"""Build extended-ROM probe ROMs for mgba-rom-test.

    make-test-rom.py VARIANT OUT.gba [--gbafix PATH]

Variants: stock-16, stock-32 (must behave exactly like stock mGBA) and extended-64, extended-288
(windows A 0x08000000-0x0DFFFFFF and B 0x12000000-0x1DFFFFFF, linear over the file).
Run: mgba-rom-test -S 0xFE -R r7 OUT.gba  -> exit status = failed checks (r6 = first failing index).
"""
import argparse, array, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MB = 1 << 20
WORD, HALF, BYTE, DMA, CPUSET, MIRROR, EXEC = 0, 1, 2, 3, 4, 6, 7


def file_offset(addr):
    """Where the fork maps a cart address in an extended ROM."""
    region = addr >> 24
    if 0x08 <= region <= 0x0D:
        return addr - 0x08000000
    if 0x12 <= region <= 0x1D:
        return addr - 0x12000000 + 96 * MB
    raise ValueError(hex(addr))


def open_bus32(addr):
    """Stock LOAD_CART value for an address past the end of the ROM (memory.c)."""
    a = addr & ~3
    return ((a >> 1) & 0xFFFF) | ((((a + 2) >> 1) & 0xFFFF) << 16)


def word(addr, size):
    off = file_offset(addr)
    return (WORD, addr, off if off < size else open_bus32(addr))


VARIANTS = {
    'stock-16': (16 * MB, lambda s: [
        (WORD, 0x08FFFFFC, 0x00FFFFFC),
        (MIRROR, 0x0A001000, 0x08001000),
        (MIRROR, 0x0C002000, 0x08002000),
        (WORD, 0x09000000, open_bus32(0x09000000)),
    ]),
    'stock-32': (32 * MB, lambda s: [
        (WORD, 0x09FFFFFC, 0x01FFFFFC),
        (MIRROR, 0x0A000100, 0x08000100),
        (MIRROR, 0x0D000100, 0x09000100),
        (DMA, 0x09000010, 0x01000010),
    ]),
    'extended-64': (64 * MB, lambda s: [
        word(0x0BFFFFFC, s),
        word(0x0A000000, s),
        word(0x0C000000, s),            # past the end: open bus, not a wrap to 0
        word(0x12000000, s),            # window B past the end: open bus
        (DMA, 0x0B000010, 0x03000010),
    ]),
    'extended-288': (288 * MB, lambda s: [
        word(0x08001000, s), word(0x09FFFFFC, s), word(0x0A000000, s), word(0x0B000000, s),
        word(0x0DFFFFFC, s), word(0x12000000, s), word(0x17000004, s), word(0x1DFFFFFC, s),
        (HALF, 0x0A000002, 0x0200),
        (BYTE, 0x12000003, 0x06),
        (BYTE, 0x0C100003, 0x04),
        (DMA, 0x0A000010, 0x02000010),
        (DMA, 0x12000100, 0x06000100),
        (CPUSET, 0x0C100020, 0x04100020),
        (CPUSET, 0x1C000000, file_offset(0x1C000000)),
        (EXEC, 0x0D000000 - 8, 0),      # window A: 0x0CFFFFFC -> 0x0D000000
        (EXEC, 0x14000000 - 8, 0),      # window B: 0x13FFFFFC -> 0x14000000
    ]),
}

# Code for EXEC checks: nop; nop; then, at the boundary, `mov r3,#0x5A; bx lr`. A fetch that wraps
# inside a 16 MiB slice lands on the region's first word instead, which gets `mov r3,#0xEE; bx lr`.
EXEC_GOOD = array.array('I', [0xE1A00000, 0xE1A00000, 0xE3A0305A, 0xE12FFF1E])
EXEC_WRAPPED = array.array('I', [0xE3A030EE, 0xE12FFF1E])


def assemble(tmp):
    obj, elf, binf = tmp / 't.o', tmp / 't.elf', tmp / 't.bin'
    subprocess.run(['arm-none-eabi-as', '-mcpu=arm7tdmi', str(HERE / 'test.s'), '-o', str(obj)], check=True)
    subprocess.run(['arm-none-eabi-ld', '-Ttext=0x08000000', str(obj), '-o', str(elf)], check=True)
    subprocess.run(['arm-none-eabi-objcopy', '-O', 'binary', str(elf), str(binf)], check=True)
    syms = subprocess.run(['arm-none-eabi-nm', str(elf)], check=True, capture_output=True, text=True).stdout
    table = next(int(l.split()[0], 16) for l in syms.splitlines() if l.endswith(' table'))
    return binf.read_bytes(), table - 0x08000000


def main():
    p = argparse.ArgumentParser()
    p.add_argument('variant', choices=VARIANTS)
    p.add_argument('out', type=Path)
    p.add_argument('--gbafix', default='gbafix')
    a = p.parse_args()
    size, checks = VARIANTS[a.variant]
    with tempfile.TemporaryDirectory() as t:
        code, table_off = assemble(Path(t))
    table = array.array('I')
    for kind, addr, expected in checks(size):
        table.extend([kind, addr, expected])
    table.append(0xFFFFFFFF)
    head = code[:table_off] + table.tobytes()
    assert len(head) < 0x1000, 'probe code must stay below the first checked offset'
    with open(a.out, 'wb') as f:
        chunk = 16 * MB
        for base in range(0, size, chunk):
            f.write(array.array('I', range(base, base + chunk, 4)).tobytes())
        for kind, addr, _ in checks(size):
            if kind == EXEC:
                f.seek(file_offset(addr))
                f.write(EXEC_GOOD.tobytes())
                f.seek(file_offset((addr + 8) - (1 << 24)))
                f.write(EXEC_WRAPPED.tobytes())
        f.seek(0)
        f.write(head)
    subprocess.run([a.gbafix, str(a.out), '-tEXTROMTEST', '-cXROM', '--silent'], check=True)
    print(f'{a.variant}: {size // MB} MB, {len(checks(size))} checks -> {a.out}')


if __name__ == '__main__':
    main()
