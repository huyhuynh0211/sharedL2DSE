# Total energy per run vs static W16 -> results.log
#   McPAT (cores, L2 dynamic, bus, MC) + DRAMPower + L2 leakage:
#     static/fixed : McPAT of the run
#     dynamic      : sum P_leak(W) x time at each W (P_leak(W) from l2_leak.csv)
#     drowsy       : P_leak(16) x T x [f_tag + (1 - f_tag)(a + r(1 - a))]
# python3 energy_total.py <energy.csv> <l2_leak.csv> <out dir> <workload> [<workload> ...]
import csv
import json
import sys

LOG = "results.log"
R_DROWSY = 0.16      # drowsy / awake line leakage (assumed, Flautner 2002 table 4)
F_TAG = 0.1          # tag array share of L2 leakage, always awake (assumed)

runs = {r["run"]: r for r in csv.DictReader(open(sys.argv[1]))}
P = {int(r["ways"]): float(r["P_l2_leak_W"]) for r in csv.DictReader(open(sys.argv[2]))}
out = sys.argv[3]


def p_leak(w):
    keys = sorted(P)
    for lo, hi in zip(keys, keys[1:]):
        if lo <= w <= hi:
            return P[lo] + (w - lo) * (P[hi] - P[lo]) / (hi - lo)
    return P[keys[-1]]


def l2_leak_mJ(name, r):
    meta = json.load(open(f"{out}/{name}/run_meta.json"))
    T = float(r["time_ms"]) / 1e3
    if meta["mode"] == "dynamic":
        rows = list(csv.DictReader(open(f"{out}/{name}/dyn_log.csv")))
        dt = meta["interval"] / 1e9
        e = sum(p_leak(int(x["ways"])) for x in rows) * dt
        e += p_leak(int(rows[-1]["ways"])) * max(0.0, T - len(rows) * dt)
        return e * 1e3, sum(int(x["ways"]) for x in rows) / len(rows)
    if meta["mode"] == "drowsy" and meta["window"] > 0:
        a = meta["awake_fraction"]
        p16 = float(r["P_l2_leak_W"])
        return p16 * T * (F_TAG + (1 - F_TAG) * (a + R_DROWSY * (1 - a))) * 1e3, None
    return float(r["E_l2_leak_mJ"]), None


lines = ["P_leak L2 (W): " + ", ".join(f"W{w} {P[w]:.4f}" for w in sorted(P, reverse=True))]
for wl in sys.argv[4:]:
    base_name = f"static_W16_{wl}"
    if base_name not in runs:
        lines.append(f"{wl}: no {base_name} in energy.csv")
        continue
    names = [n for n in (base_name, f"dyn_{wl}", f"dyn_{wl}_idle0", f"drowsy_w4000_{wl}",
                         f"drowsy_w16000_{wl}", f"drowsy_w4000_lat2_{wl}") if n in runs]
    lines.append("")
    lines.append(f"[{wl}] run, time ms (dT %), avg W, L2 leak mJ (save %), other mJ, "
                 f"total mJ (save %) | core, L2 dyn, bus+MC, DRAM mJ")
    base = None
    for n in names:
        r = runs[n]
        l2, avg_w = l2_leak_mJ(n, r)
        core = float(r["E_core_leak_mJ"]) + float(r["E_core_dyn_mJ"])
        l2dyn = float(r["E_l2_dyn_mJ"])
        busmc = sum(float(r[k]) for k in ("E_bus_leak_mJ", "E_bus_dyn_mJ", "E_mc_leak_mJ", "E_mc_dyn_mJ"))
        dram = float(r["E_dram_mJ"])
        other = core + l2dyn + busmc + dram
        total = other + l2
        t = float(r["time_ms"])
        if base is None:
            base = (t, l2, total)
        lines.append(f"{n}, {t:.3f} ({100 * (t / base[0] - 1):+.2f}), "
                     f"{'-' if avg_w is None else f'{avg_w:.2f}'}, "
                     f"{l2:.3f} ({100 * (1 - l2 / base[1]):.1f}), {other:.3f}, "
                     f"{total:.3f} ({100 * (1 - total / base[2]):.2f}) | "
                     f"{core:.3f}, {l2dyn:.3f}, {busmc:.3f}, {dram:.3f}")

with open(LOG, "a") as f:
    f.write("\n== " + " ".join(sys.argv) + "\n" + "\n".join(lines) + "\n")
