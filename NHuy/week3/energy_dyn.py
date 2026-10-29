# L2 leakage of dynamic way shutdown vs W16 -> results.log
# python3 energy_dyn.py <out dynamic> <interval> <out static W16>
import csv
import json
import sys

LOG = "results.log"
P_MCPAT = {16: 0.1436, 8: 0.0786, 4: 0.0482, 2: 0.0345, 1: 0.0264}   # W -> watt (McPAT 22 nm)


def p_leak(w):
    keys = sorted(P_MCPAT)
    for lo, hi in zip(keys, keys[1:]):
        if lo <= w <= hi:
            return P_MCPAT[lo] + (w - lo) * (P_MCPAT[hi] - P_MCPAT[lo]) / (hi - lo)
    return P_MCPAT[16]


out = sys.argv[1]
interval = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
dt = interval / 1e9

rows = list(csv.DictReader(open(f"{out}/dyn_log.csv")))
e_dyn = sum(p_leak(int(r["ways"])) for r in rows) * dt
t_dyn = json.load(open(f"{out}/run_meta.json"))["ticks_measured"] / 1e12
avg_w = sum(int(r["ways"]) for r in rows) / len(rows)
e_dyn += p_leak(int(rows[-1]["ways"])) * max(0.0, t_dyn - len(rows) * dt)   # last partial interval

if len(sys.argv) > 3:
    t_w16 = json.load(open(f"{sys.argv[3]}/run_meta.json"))["ticks_measured"] / 1e12
else:
    t_w16 = t_dyn
e_w16 = P_MCPAT[16] * t_w16

lines = [f"intervals        : {len(rows)}, average W: {avg_w:.2f}",
         f"run time         : dynamic {t_dyn * 1e3:.3f} ms, W16 {t_w16 * 1e3:.3f} ms "
         f"({100 * (t_dyn / t_w16 - 1):+.2f} %)",
         f"L2 leakage (dyn) : {e_dyn * 1e3:.3f} mJ",
         f"L2 leakage (W16) : {e_w16 * 1e3:.3f} mJ",
         f"saving           : {100 * (1 - e_dyn / e_w16):.1f} %"]
with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
