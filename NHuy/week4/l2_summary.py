# Summary of l2_run.py runs -> results.log (first run = reference)
# python3 l2_summary.py <out> [<out> ...]
import json
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
    return sum(v for k, v in st.items() if re.fullmatch(pattern, k))


def mean(st, pattern):
    vals = [v for k, v in st.items() if re.fullmatch(pattern, k)]
    return sum(vals) / len(vals) if vals else float("nan")


lines = ["out, MHz, avg W, L2 acc, L2 miss, miss %, MPKI, L1D miss lat (cyc), "
         "cycles, cycles vs ref, IPC/core, DRAM MB/s, way-off WB"]
ref = None
for out in sys.argv[1:]:
    st = read_stats(f"{out}/stats.txt")
    meta = json.load(open(f"{out}/run_meta.json"))
    tpc = 1e6 / meta["clock_mhz"]                       # ticks per cycle
    acc = total(st, r"system\.l2bank\d*\.demandAccesses::total")
    miss = total(st, r"system\.l2bank\d*\.demandMisses::total")
    insts = st.get("simInsts", 0)
    cyc = st.get("simTicks", 0) / tpc
    lat = mean(st, r"system\.cpu\d+\.dcache\.demandAvgMissLatency::total") / tpc
    ipc = mean(st, r"system\.cpu\d+\.ipc")
    bw = st.get("system.mem_ctrl.dram.bwTotal::total", 0) / 1e6
    if ref is None:
        ref = cyc
    avg_w = meta["ways"] if meta["mode"] in ("static", "fixed") else 16
    if meta["mode"] == "dynamic":
        rows = [l.split(",") for l in open(f"{out}/dyn_log.csv")][1:]
        avg_w = sum(int(r[1]) for r in rows) / len(rows) if rows else 16
    lines.append(f"{out}, {meta['clock_mhz']}, {avg_w:.2f}, {int(acc)}, {int(miss)}, "
                 f"{100 * miss / acc if acc else 0:.2f}, {1000 * miss / insts if insts else 0:.3f}, "
                 f"{lat:.1f}, {cyc:.0f}, {100 * (cyc / ref - 1):+.2f}%, {ipc:.3f}, {bw:.1f}, "
                 f"{meta.get('way_off_writebacks', 0)}")

with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
print("\n".join(lines))
