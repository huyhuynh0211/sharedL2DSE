# tmem = L1D miss latency (all L2 miss) - L1D miss latency (all L2 hit)
# python3 tmem_calc.py <out all-miss> <out all-hit>
import json
import re
import sys

LOG = "results.log"


def l1d_lat(out):
    tpc = 1e6 / json.load(open(f"{out}/run_meta.json"))["clock_mhz"]
    vals = []
    for line in open(f"{out}/stats.txt"):
        p = line.split()
        if len(p) >= 2 and re.fullmatch(r"system\.cpu\d+\.dcache\.demandAvgMissLatency::total", p[0]):
            vals.append(float(p[1]) / tpc)
    return sum(vals) / len(vals)


miss = l1d_lat(sys.argv[1])
hit = l1d_lat(sys.argv[2])
text = f"L1D miss lat: {miss:.1f} - {hit:.1f} = tmem {miss - hit:.1f} cycles"
with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + text + "\n")
print(text)
