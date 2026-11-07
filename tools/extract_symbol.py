#!/usr/bin/env python3
"""Dump a data symbol's bytes out of a relocatable ELF (vendor .ko).

Usage: python3 -I extract_symbol.py <module.ko> <SYMBOL> <out.bin>
"""
import subprocess, sys

ko, sym, out = sys.argv[1:4]
run = lambda *a: subprocess.run(["arm-linux-gnu-readelf", "-W", *a, ko],
                                capture_output=True, text=True, check=True).stdout
row = next(l.split() for l in run("-s").splitlines() if l.split()[-1:] == [sym])
value, size, ndx = int(row[1], 16), int(row[2]), int(row[6])
sec = next(l for l in run("-S").splitlines() if l.strip().startswith(f"[{ndx:2d}]") or l.strip().startswith(f"[{ndx}]"))
sec_off = int(sec.split("]", 1)[1].split()[3], 16)
blob = open(ko, "rb").read()[sec_off + value: sec_off + value + size]
assert len(blob) == size, (len(blob), size)
open(out, "wb").write(blob)
print(f"{sym}: {size} bytes from section {ndx} -> {out}")
