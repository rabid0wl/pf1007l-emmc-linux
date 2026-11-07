import re, sys, difflib
# Compare our decoded vendor table against every *_init() in mainline panel-jadard-jd9365da-h3.c
src = open(sys.argv[1]).read()
ours = []
for l in open(sys.argv[2]):
    if l.startswith("0x"):
        p = l.split(); ours.append((int(p[0], 16), tuple(int(x, 16) for x in p[1:])))
def norm(body):
    out = []
    for m in re.finditer(r'jd9365da_switch_page\(&?dsi_ctx,\s*(0x[0-9a-fA-F]+)\)|jadard_enable_standard_cmds\(&?dsi_ctx\)|mipi_dsi_dcs_write_seq_multi\(&?dsi_ctx,\s*([^)]*)\)|mipi_dsi_dcs_(exit_sleep_mode|set_display_on)_multi', body):
        if m.group(1): out.append((0xE0, (int(m.group(1), 16),)))
        elif m.group(0).startswith("jadard_enable"):
            out += [(0xE0,(0,)),(0xE1,(0x93,)),(0xE2,(0x65,)),(0xE3,(0xF8,)),(0x80,(3,))]
        elif m.group(2):
            v = [int(x, 0) for x in m.group(2).split(",") if x.strip() and not x.strip().isidentifier()]
            if v: out.append((v[0], tuple(v[1:])))
        elif m.group(3) == "exit_sleep_mode": out.append((0x11, ()))
        else: out.append((0x29, ()))
    return out
funcs = re.findall(r'static int (\w+_init(?:_cmds)?)\(struct jadard \*jadard\)\s*\{(.*?)\n\}', src, re.S)
# our 0x11/0x29 carry a dummy 00 param; strip for fair comparison
ours_n = [(c, () if c in (0x11, 0x29) else p) for c, p in ours]
res = []
for name, body in funcs:
    theirs = norm(body)
    r = difflib.SequenceMatcher(None, ours_n, theirs, autojunk=False).ratio()
    res.append((r, name, len(theirs)))
for r, n, ln in sorted(res, reverse=True):
    print(f"{r:6.3f}  {n:40s} {ln} writes  (ours {len(ours_n)})")
