# Total energy per run vs static W16 -> results.log
# L2 leakage: static = McPAT, fixed/dynamic = P_leak(W) x time (+ flush), drowsy = formula
# python3 energy_total.py <energy.csv> <l2_leak.csv> <out dir> <workload> [<workload> ...]
import csv
import json
import re
import sys

LOG = "results.log"
R_DROWSY = 0.16      # assumed, Flautner 2002
F_TAG = 0.1          # assumed
E_WR_LINE_PJ = 2000  # fallback, assumed

runs = {r["run"]: r for r in csv.DictReader(open(sys.argv[1]))}
P = {int(r["ways"]): float(r["P_l2_leak_W"]) for r in csv.DictReader(open(sys.argv[2]))}
out = sys.argv[3]


def p_leak(w):
    keys = sorted(P)
    for lo, hi in zip(keys, keys[1:]):
        if lo <= w <= hi:
            return P[lo] + (w - lo) * (P[hi] - P[lo]) / (hi - lo)
    return P[keys[-1]]


def dram_write_pj_per_line(name):
    e = n = 0.0
    for line in open(f"{out}/{name}/stats.txt"):
        p = line.split()
        if len(p) < 2:
            continue
        if re.fullmatch(r"system\.mem_ctrl\.dram\.rank\d+\.writeEnergy", p[0]):
            e += float(p[1])
        elif p[0] == "system.mem_ctrl.dram.writeBursts":
            n += float(p[1])
    return e / n if n else E_WR_LINE_PJ


def l2_leak_mJ(name, r):
    meta = json.load(open(f"{out}/{name}/run_meta.json"))
    T = float(r["time_ms"]) / 1e3
    if meta["mode"] == "fixed":
        return p_leak(meta["ways"]) * T * 1e3, meta["ways"], 0.0
    if meta["mode"] == "dynamic":
        rows = list(csv.DictReader(open(f"{out}/{name}/dyn_log.csv")))
        dt = meta["interval"] / (meta["clock_mhz"] * 1e6)
        e = sum(p_leak(int(x["ways"])) for x in rows) * dt
        e += p_leak(int(rows[-1]["ways"]) if rows else 16) * max(0.0, T - len(rows) * dt)
        avg_w = sum(int(x["ways"]) for x in rows) / len(rows) if rows else 16
        flush = meta["way_off_writebacks"] * dram_write_pj_per_line(name) * 1e-9
        return e * 1e3, avg_w, flush
    if meta["mode"] == "drowsy" and meta["window"] > 0:
        a = meta["awake_fraction"]
        p16 = float(r["P_l2_leak_W"])
        return p16 * T * (F_TAG + (1 - F_TAG) * (a + R_DROWSY * (1 - a))) * 1e3, 16, 0.0
    return float(r["E_l2_leak_mJ"]), int(r["ways"]), 0.0


lines = ["P_leak L2 (W): " + ", ".join(f"W{w} {P[w]:.4f}" for w in sorted(P, reverse=True))]
for wl in sys.argv[4:]:
    base_name = f"static_W16_{wl}"
    if base_name not in runs:
        lines.append(f"{wl}: no {base_name} in energy.csv")
        continue
    names = [n for n in (base_name, f"fixed_W12_{wl}", f"fixed_W8_{wl}", f"fixed_W4_{wl}",
                         f"dyn_{wl}") if n in runs]
    lines.append("")
    lines.append(f"[{wl}] run, time ms (dT %), avg W, L2 leak mJ (save %), flush mJ, other mJ, "
                 f"total mJ (save %) | core, L2 dyn, bus+MC, DRAM mJ")
    base = None
    for n in names:
        r = runs[n]
        l2, avg_w, flush = l2_leak_mJ(n, r)
        core = float(r["E_core_leak_mJ"]) + float(r["E_core_dyn_mJ"])
        l2dyn = float(r["E_l2_dyn_mJ"])
        busmc = sum(float(r[k]) for k in ("E_bus_leak_mJ", "E_bus_dyn_mJ", "E_mc_leak_mJ", "E_mc_dyn_mJ"))
        dram = float(r["E_dram_mJ"])
        other = core + l2dyn + busmc + dram
        total = other + l2 + flush
        t = float(r["time_ms"])
        if base is None:
            base = (t, l2, total)
        lines.append(f"{n}, {t:.3f} ({100 * (t / base[0] - 1):+.2f}), {avg_w:.2f}, "
                     f"{l2:.3f} ({100 * (1 - l2 / base[1]):.1f}), {flush:.4f}, {other:.3f}, "
                     f"{total:.3f} ({100 * (1 - total / base[2]):.2f}) | "
                     f"{core:.3f}, {l2dyn:.3f}, {busmc:.3f}, {dram:.3f}")

with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
print("\n".join(lines))
