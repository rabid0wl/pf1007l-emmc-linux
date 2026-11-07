import struct, sys, subprocess
# Pull .data from the vendor lcd.ko and decode the 72-byte LCM init records.
ko, off, size = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3])
hdr = subprocess.run(["arm-linux-gnu-readelf", "-SW", ko], capture_output=True, text=True).stdout
line = next(l for l in hdr.splitlines() if " .data " in l and "PROGBITS" in l)
f = line.split("]", 1)[1].split()
sec_off = int(f[3], 16)
blob = open(ko, "rb").read()[sec_off + off: sec_off + off + size]
recs = []
for i in range(0, len(blob), 72):
    cmd, cnt = struct.unpack_from("<II", blob, i)
    if cmd == 0xFF1:
        break
    if cmd == 0xFF0:
        recs.append(("delay", cnt, b""))
    else:
        recs.append(("dsi", cmd, blob[i + 8: i + 8 + cnt]))
for kind, a, p in recs:
    print(f"DELAY {a}ms" if kind == "delay" else f"0x{a:02X} " + " ".join(f"{b:02X}" for b in p))
print(f"# {sum(1 for r in recs if r[0]=='dsi')} writes, {sum(1 for r in recs if r[0]=='delay')} delays", file=sys.stderr)
