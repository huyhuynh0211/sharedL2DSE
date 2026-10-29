# tmem = L1D miss lat (all L2 miss) - L1D miss lat (all L2 hit) -> results.log
# python3 tmem_calc.py <out all-miss> <out all-hit>
import re
import sys

LOG = "results.log"


def l1d_lat(out):
    vals = []
    for line in open(f"{out}/stats.txt"):
        p = line.split()
        if len(p) >= 2 and re.fullmatch(r"system\.cpu\d+\.dcache\.demandAvgMissLatency::total", p[0]):
            vals.append(float(p[1]) / 1000)
    return sum(vals) / len(vals)


miss = l1d_lat(sys.argv[1])
hit = l1d_lat(sys.argv[2])
with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n"
            f"L1D miss lat: {miss:.1f} - {hit:.1f} = tmem {miss - hit:.1f} cycles\n")
