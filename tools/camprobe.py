#!/usr/bin/env python3
"""Camera presence probe for the AEEZO U708HC (run on the frame as root, camprobe DTB booted).

The DTB powers the vendor csi0 rails, enables i2c2 and muxes PE1 to CSI MCLK. This script gates
the CCU csi-mclk on at 24MHz (no kernel consumer exists), drives the sensor control pins through
the PIO registers (PE15 = dev0 pwdn, PE17 = dev1 pwdn, high = off; PE16 = shared reset, low =
reset), then scans i2c-2 and reads the GalaxyCore chip id at 0x3c (0xf0/0xf1, gc2035 = 0x2035).
"""
import fcntl
import mmap
import os
import struct
import time

CCU, PIO = 0x01C20000, 0x01C20800
CSI_CLK = 0x134
PE = 4 * 0x24  # bank E register block inside PIO
I2C_SLAVE = 0x0703


class Regs:
    def __init__(self, base):
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.m = mmap.mmap(fd, 0x1000, offset=base & ~0xFFF)
        self.off = base & 0xFFF
        os.close(fd)

    def rd(self, r):
        return struct.unpack_from("<I", self.m, self.off + r)[0]

    def wr(self, r, v):
        struct.pack_into("<I", self.m, self.off + r, v)


def pin_out(pio, pin, val):
    cfg = PE + 4 * (pin // 8)
    sh = (pin % 8) * 4
    pio.wr(cfg, (pio.rd(cfg) & ~(7 << sh)) | (1 << sh))
    dat = PE + 0x10
    pio.wr(dat, (pio.rd(dat) & ~(1 << pin)) | (val << pin))


def scan(bus=2):
    fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
    found = []
    for a in range(0x08, 0x78):
        try:
            fcntl.ioctl(fd, I2C_SLAVE, a)
            os.read(fd, 1)
            found.append(a)
        except OSError:
            pass
    os.close(fd)
    return found


def gc_id(addr=0x3C, bus=2):
    fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
    fcntl.ioctl(fd, I2C_SLAVE, addr)
    out = []
    for reg in (0xF0, 0xF1):
        os.write(fd, bytes([reg]))
        out.append(os.read(fd, 1)[0])
    os.close(fd)
    return out


def hexes(xs):
    return " ".join(f"0x{x:02x}" for x in xs) or "nothing"


ccu, pio = Regs(CCU), Regs(PIO)
# The board has no external pull-ups on PE12/PE13 (they float, 2026-11-05): without these the
# controller reports "bus locked" for ~2s per address. Internal ~100k pull-ups are enough at 100kHz.
pio.wr(PE + 0x1C, (pio.rd(PE + 0x1C) & ~(0xF << 24)) | (0x5 << 24))
print(f"i2c-2 before MCLK: {hexes(scan())}")

v = ccu.rd(CSI_CLK)
ccu.wr(CSI_CLK, (v & ~0x71F) | (5 << 8) | (1 << 15))  # osc24M, M=0, gate on
print(f"CSI_CLK 0x{v:08x} -> 0x{ccu.rd(CSI_CLK):08x}")

for name, on, off in (("dev0", 15, 17), ("dev1", 17, 15)):
    pin_out(pio, off, 1)  # the other sensor slot stays powered down
    pin_out(pio, 16, 0)
    pin_out(pio, on, 0)
    time.sleep(0.01)
    pin_out(pio, 16, 1)
    time.sleep(0.05)
    found = scan()
    line = f"{name} (pwdn PE{on} low): {hexes(found)}"
    if 0x3C in found:
        hi, lo = gc_id()
        line += f"  | 0x3c id f0/f1 = 0x{hi:02x}{lo:02x}"
    print(line)

# leave both slots powered down and MCLK off
pin_out(pio, 15, 1)
pin_out(pio, 17, 1)
ccu.wr(CSI_CLK, ccu.rd(CSI_CLK) & ~(1 << 15))
print("done: both pwdn high, MCLK gated off")
