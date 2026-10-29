# L2 miss rate predicted by the ATD for each W (from dyn_log.csv) -> results.log
# python3 atd_check.py <out dynamic>
import csv
import sys

LOG = "results.log"

rows = list(csv.DictReader(open(f"{sys.argv[1]}/dyn_log.csv")))
acc = sum(int(r["sampled_acc"]) for r in rows)
hits = [sum(int(r[f"h{p}"]) for r in rows) for p in range(16)]

lines = ["W, predicted miss (%)"]
for w in range(16, 0, -1):
    miss = 100 * (1 - sum(hits[:w]) / acc) if acc else float("nan")
    lines.append(f"{w}, {miss:.2f}")
with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
