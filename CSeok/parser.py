import argparse
import csv
import json
from pathlib import Path

NUM_CPUS = 4
L2_HIT_CYCLES = 2       # L2 latency set in model.py (assumed)
TICKS_PER_CYCLE = 10000   # 1 GHz clock: 1 cycle = 1000 ticks

parser = argparse.ArgumentParser(description="Collect a sweep's stats into one CSV")
parser.add_argument("--runs", required=True,
                    help="sweep folder, e.g. CSeok/runs")
parser.add_argument("--out",
                    help="CSV file to write (default: results.csv inside --runs)")
args = parser.parse_args()

runs = Path(args.runs)
out = Path(args.out) if args.out else runs / "results.csv"


def read_stats(path):
    stats = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            stats[parts[0]] = float(parts[1])
        except ValueError:
            continue
    return stats


# gem5 leaves out stats that are zero, so a missing stat counts as 0.
# A stat that is missing in EVERY run is probably a typo; we report those at the end.
asked = set()
found = set()

def get(stats, name):
    asked.add(name)
    if name in stats:
        found.add(name)
        return stats[name]
    return 0


def div(a, b):
    if b == 0:
        return ""
    return a / b


def size_kib(size):
    if size.endswith("MiB"):
        return int(size[:-3]) * 1024
    return int(size[:-3])


rows = []
for run_dir in sorted(runs.iterdir()):
    if not run_dir.is_dir():
        continue
    stats_file = run_dir / "stats.txt"
    if not stats_file.exists() or stats_file.stat().st_size == 0:
        print(f"skipping {run_dir.name}: no stats")
        continue

    stats = read_stats(stats_file)
    params = json.loads((run_dir / "params.json").read_text())

    # settings of this run, straight from params.json
    row = {"run": run_dir.name}
    row.update(params)
    row["l2_kib"] = size_kib(params["l2_size"])
    row["sim_ticks"] = get(stats, "simTicks")

    # shared L2, all cores together
    l2_acc = get(stats, "system.l2cache.demandAccesses::total")
    l2_miss = get(stats, "system.l2cache.demandMisses::total")
    l2_lat = get(stats, "system.l2cache.demandAvgMissLatency::total")
    row["l2_accesses"] = l2_acc
    row["l2_misses"] = l2_miss
    row["l2_miss_rate"] = div(l2_miss, l2_acc)
    row["l2_miss_lat_cyc"] = l2_lat / TICKS_PER_CYCLE
    if l2_acc:
        row["l2_amat_cyc"] = L2_HIT_CYCLES + row["l2_miss_rate"] * row["l2_miss_lat_cyc"]
    else:
        row["l2_amat_cyc"] = ""

    # each core on its own
    l1_misses = 0
    for c in range(NUM_CPUS):
        cpu = f"system.cpu{c}"
        insts = get(stats, f"{cpu}.commitStats0.numInsts")
        l1d_acc = get(stats, f"{cpu}.dcache.demandAccesses::total")
        l1d_miss = get(stats, f"{cpu}.dcache.demandMisses::total")
        l1i_miss = get(stats, f"{cpu}.icache.demandMisses::total")
        l2_miss_c = (get(stats, f"system.l2cache.demandMisses::cpu{c}.data")
                     + get(stats, f"system.l2cache.demandMisses::cpu{c}.inst"))

        row[f"c{c}_insts"] = insts
        row[f"c{c}_l1d_miss_rate"] = div(l1d_miss, l1d_acc)
        row[f"c{c}_l2_misses"] = l2_miss_c
        row[f"c{c}_l2_mpki"] = div(1000 * l2_miss_c, insts)
        l1_misses += l1d_miss + l1i_miss

    # sanity check: every L1 miss becomes one L2 access, so this should be close to 1
    row["check_l2acc_per_l1miss"] = div(l2_acc, l1_misses)

    rows.append(row)

if not rows:
    raise SystemExit(f"no finished runs in {runs}")

with out.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print(f"wrote {len(rows)} rows to {out}")
for name in sorted(asked - found):
    print(f"warning: {name} not found in any run, check the name")