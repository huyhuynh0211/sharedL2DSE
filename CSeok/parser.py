import csv
from pathlib import Path

RUNS = Path("dse/test/runs")
OUT  = Path("dse/test/results.csv")

WANTED = {
    "sim_ticks":        "simTicks",
    "insts":            "simInsts",
    "cycles":           "system.cpu.numCycles",
    "l1d_accesses":     "system.cpu.dcache.demandAccesses::total",
    "l1d_misses":       "system.cpu.dcache.demandMisses::total",
    "l1d_miss_rate":    "system.cpu.dcache.demandMissRate::total",
    "l1d_miss_lat_ps":  "system.cpu.dcache.demandAvgMissLatency::total",
    "l2_misses":        "system.l2cache.demandMisses::total",
}

HIT_CYCLES = 2
TICKS_PER_CYCLE = 1000

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

def params_from_name(name):
    parts = name.split("_")
    size_kib = int(parts[1].replace("KiB", ""))
    assoc = int(parts[2][1:])
    repl = parts[3]
    return size_kib, assoc, repl

rows = []
for run_dir in RUNS.iterdir():
    stats_file = run_dir / "stats.txt"
    if not stats_file.exists() or stats_file.stat().st_size == 0:
        print(f"skipping {run_dir.name}: no stats")
        continue

    stats = read_stats(stats_file)
    size_kib, assoc, repl = params_from_name(run_dir.name)
    row = {"run": run_dir.name, "l1d_kib": size_kib, "l1d_assoc": assoc, "l1d_repl": repl}

    for column, stat_name in WANTED.items():
        if stat_name not in stats:
            print(f"warning: {stat_name} missing in {run_dir.name}")
        row[column] = stats.get(stat_name, "")

    row["cpi"] = row["cycles"] / row["insts"]
    row["l1d_mpki"] = 1000 * row["l1d_misses"] / row["insts"]

    miss_rate = row["l1d_miss_rate"]
    if row["l1d_misses"]:
        miss_penalty = row["l1d_miss_lat_ps"] / TICKS_PER_CYCLE
    else:
        miss_penalty = 0

    row["l1d_miss_penalty_cyc"] = round(miss_penalty, 2)
    row["amat_cyc"] = round(HIT_CYCLES + miss_rate * miss_penalty, 3)

    rows.append(row)

rows.sort(key=lambda r: (r["l1d_kib"], r["l1d_assoc"], r["l1d_repl"]))

with OUT.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print(f"wrote {len(rows)} rows to {OUT}")