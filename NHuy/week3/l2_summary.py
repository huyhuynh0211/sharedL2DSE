# Summary of l2_run.py runs (all L2 banks summed) -> results.log
# python3 l2_summary.py <out> [<out> ...]
import re
import sys

LOG = "results.log"


def read_stats(path):
    st = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 2 and not line.startswith("-"):
            try:
                st[p[0]] = float(p[1])
            except ValueError:
                pass
    return st


def total(st, pattern):
    vals = [v for k, v in st.items() if re.fullmatch(pattern, k)]
    return sum(vals), len(vals)


lines = ["out, L2 acc, L2 miss, miss %, MPKI, L1D miss lat (cyc), cycles, acc per bank"]
for out in sys.argv[1:]:
    st = read_stats(f"{out}/stats.txt")
    acc, nb = total(st, r"system\.l2bank\d*\.demandAccesses::total")
    if nb == 0:
        lines.append(f"{out}: no L2 bank stats found")
        continue
    miss, _ = total(st, r"system\.l2bank\d*\.demandMisses::total")
    insts = st.get("simInsts", 0)
    lat, nl = total(st, r"system\.cpu\d+\.dcache\.demandAvgMissLatency::total")
    cyc = st.get("simTicks", 0) / 1000
    per_bank = [int(v) for k, v in sorted(st.items())
                if re.fullmatch(r"system\.l2bank\d*\.demandAccesses::total", k)]
    mpki = 1000 * miss / insts if insts else float("nan")
    lat_cyc = lat / nl / 1000 if nl else float("nan")
    lines.append(f"{out}, {int(acc)}, {int(miss)}, {100 * miss / acc:.2f}, {mpki:.3f}, "
                 f"{lat_cyc:.1f}, {cyc:.0f}, {per_bank}")

with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
