import argparse
import configparser
import csv
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_stat_blocks(path):
    blocks, cur = [], None
    for line in path.read_text().splitlines():
        if "Begin Simulation Statistics" in line:
            cur = {}
            continue
        if "End Simulation Statistics" in line:
            if cur is not None:
                blocks.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            cur[parts[0]] = float(parts[1])
        except ValueError:
            pass
    if cur:
        blocks.append(cur)
    return blocks


def pick_block(blocks, which):
    if which != -1:
        return blocks[which]
    for b in reversed(blocks):
        if b.get("simInsts", 0) > 0:
            return b
    return blocks[-1]


def find_prefixes(stats, pattern, suffix):
    rx = re.compile(r"^(" + pattern + r")\." + re.escape(suffix) + r"$")
    return sorted({m.group(1) for k in stats if (m := rx.match(k))})


def total(stats, prefixes, suffix):
    vals = [stats.get(f"{p}.{suffix}") for p in prefixes]
    vals = [v for v in vals if v is not None and not math.isnan(v)]
    return sum(vals) if vals else None


def div(a, b, scale=1.0):
    if a is None or b in (None, 0):
        return None
    return scale * a / b


def l2_params_from_config(cfg_path, l2_prefix):
    p = {}
    if not cfg_path.exists() or l2_prefix is None:
        return p
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.read(cfg_path)
    if cfg.has_section(l2_prefix):
        sec = cfg[l2_prefix]
        p["l2_size"] = sec.get("size", "")
        p["l2_assoc"] = sec.get("assoc", "")
        p["l2_clusivity"] = sec.get("clusivity", "")
        p["l2_mshrs"] = sec.get("mshrs", "")
    envs = {cfg[sec].get("env", "") for sec in cfg.sections() if cfg.has_option(sec, "cmd")}
    p["env"] = ";".join(sorted(envs))
    rp = f"{l2_prefix}.replacement_policy"
    if cfg.has_section(rp):
        p["l2_repl"] = cfg[rp].get("type", "")
    return p


def meta_from_json(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        print("warning")
        return {}
    return {f"meta_{k}": v for k, v in data.items() if isinstance(v, (int, float, str, bool))}


def size_to_bytes(s):
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKmMgG]?)i?B?\s*", str(s))
    if not m:
        return None
    mult = {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30}[m.group(2).lower()]
    return int(float(m.group(1)) * mult)


def collect_run(run_dir, block_idx):
    stats_file = run_dir / "stats.txt"
    if not stats_file.exists() or stats_file.stat().st_size == 0:
        print("warning")
        return None

    blocks = read_stat_blocks(stats_file)
    s = pick_block(blocks, block_idx)

    cpus = find_prefixes(s, r"system\.cpu\d*", "numCycles")
    l1ds = find_prefixes(s, r"system\.[\w.]*?(?:dcache|l1d)\w*", "demandMisses::total")
    l1is = find_prefixes(s, r"system\.[\w.]*?(?:icache|l1i)\w*", "demandMisses::total")
    l2s = find_prefixes(s, r"system\.[\w.]*?l2\w*", "demandMisses::total")
    l2s = [p for p in l2s if "xbar" not in p and "bus" not in p]
    if len(l2s) != 1:
        print("warning")
    l2 = l2s[0] if len(l2s) == 1 else None
    if not cpus or not l1ds:
        print("warning")

    group, label, workload = (run_dir.name.split("_", 2) + ["", ""])[:3]
    row = {"run": run_dir.name, "group": group, "label": label, "workload": workload}

    row.update(l2_params_from_config(run_dir / "config.ini", l2))
    row.update(meta_from_json(run_dir / "run_meta.json"))

    insts = s.get("simInsts")
    cycles = max((s[f"{c}.numCycles"] for c in cpus), default=None)
    row["n_cores"] = len(cpus)
    row["sim_ticks"] = s.get("simTicks")
    row["insts"] = insts
    row["cycles"] = cycles

    row["l1d_accesses"] = total(s, l1ds, "demandAccesses::total")
    row["l1d_misses"] = total(s, l1ds, "demandMisses::total")
    row["l1d_writebacks"] = total(s, l1ds, "writebacks::total")
    row["l1i_misses"] = total(s, l1is, "demandMisses::total")
    clk = s.get("system.clk_domain.clock")
    row["clock_ticks"] = clk
    l1d_lat = [s[f"{p}.demandAvgMissLatency::total"] for p in l1ds if f"{p}.demandAvgMissLatency::total" in s]
    row["l1d_miss_lat_cyc"] = div(sum(l1d_lat) / len(l1d_lat), clk) if l1d_lat else None
    dram = [k for k in s if k.endswith(".avgMemAccLat")]
    row["dram_lat_cyc"] = div(s[dram[0]], clk) if dram else None
    if l2:
        row["l2_accesses"] = s.get(f"{l2}.demandAccesses::total")
        row["l2_misses"] = s.get(f"{l2}.demandMisses::total")
        row["l2_mshr_hits"] = s.get(f"{l2}.demandMshrHits::total")
        row["l2_mshr_misses"] = s.get(f"{l2}.demandMshrMisses::total", 0)
        row["l2_writebacks"] = s.get(f"{l2}.writebacks::total")
        row["l2_miss_lat_cyc"] = div(s.get(f"{l2}.demandAvgMissLatency::total"), clk)
        for c in cpus:
            name = c.split(".")[-1]
            row[f"l2_miss_{name}"] = sum(v for k, v in s.items() if k.startswith(f"{l2}.demandMisses::")
                                         and k.split("::")[1].split(".")[-2:-1] == [name])

    row["ipc_total"] = div(insts, cycles)
    row["l1d_miss_rate"] = div(row["l1d_misses"], row["l1d_accesses"])
    row["l1d_mpki"] = div(row["l1d_misses"], insts, 1000)
    row["l2_miss_rate"] = div(row.get("l2_misses"), row.get("l2_accesses"))
    row["l2_mpki"] = div(row.get("l2_misses"), insts, 1000)
    l1_miss = (row["l1d_misses"] or 0) + (row["l1i_misses"] or 0)
    row["chk_l2acc_per_l1miss"] = div(row.get("l2_accesses"), l1_miss)
    return row


KEYS = ["group", "workload", "l2_size", "l2_assoc", "l2_repl", "l2_clusivity"]
VARY = {"shutdown": ["l2_size", "l2_assoc"], "size": ["l2_size"], "assoc": ["l2_assoc"],
        "policy": ["l2_repl"], "incl": ["l2_clusivity"]}


def num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def col_value(r, t):
    if t == "policy":
        return r.get("l2_repl", "-")
    if t == "incl":
        return r.get("l2_clusivity", "-")
    if t == "size":
        return f"{num(r.get('l2_size')) // 1024}K"
    return f"W{r.get('l2_assoc', '-')}"


def col_order(r, t):
    if t == "policy":
        return (r.get("l2_repl") != "LRURP", r.get("l2_repl", ""))
    if t == "incl":
        return (r.get("l2_clusivity") != "mostly_incl", r.get("l2_clusivity", ""))
    if t == "size":
        return (-num(r.get("l2_size")),)
    return (-num(r.get("l2_assoc")),)


def is_base(r, t):
    if t == "policy":
        return r.get("l2_repl") == "LRURP"
    if t == "incl":
        return r.get("l2_clusivity") == "mostly_incl"
    if t == "size":
        return num(r.get("l2_size")) == 1 << 20
    return num(r.get("l2_assoc")) == 16


def same_except(a, b, t):
    return all(a.get(k) == b.get(k) for k in KEYS if k not in VARY[t])


def add_vs_base(rows, t):
    for r in rows:
        bs = [x for x in rows if same_except(x, r, t) and is_base(x, t)]
        if not bs:
            continue
        b = bs[0]
        if r.get("env") != b.get("env"):
            print("warning")
        r["l2_mpki_vs_base"] = div(r.get("l2_mpki"), b.get("l2_mpki"))
        r["cycles_vs_base"] = div(r.get("cycles"), b.get("cycles"))


def sort_key(r):
    size = size_to_bytes(r.get("l2_size", "")) or 0
    try:
        assoc = int(r.get("l2_assoc", 0))
    except ValueError:
        assoc = 0
    return (r["group"], r["workload"], -size, -assoc, r.get("l2_repl", ""), r.get("l2_clusivity", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(HERE / "out"))
    ap.add_argument("--out", default=str(HERE / "result" / "results.csv"))
    ap.add_argument("--type", default="shutdown", choices=list(VARY))
    ap.add_argument("--filter", default="")
    ap.add_argument("--metric", nargs="+", default=list(METRICS), choices=list(METRICS))
    ap.add_argument("--block", type=int, default=-1)
    args = ap.parse_args()

    runs = Path(args.runs)
    if not runs.is_dir():
        raise SystemExit("err")

    rows = []
    for run_dir in sorted(p for p in runs.iterdir() if p.is_dir() and re.search(args.filter, p.name)):
        r = collect_run(run_dir, args.block)
        if r:
            rows.append(r)
    if not rows:
        raise SystemExit("err")

    add_vs_base(rows, args.type)
    rows.sort(key=sort_key)

    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else (round(v, 6) if isinstance(v, float) else v))
                        for k, v in r.items()})

    print(f"\nwrote {len(rows)} rows -> {out}\n")
    rw = max(len(r["run"]) for r in rows) + 2
    print(f"{'run':<{rw}}{'repl':<12}{'size':>10}{'ways':>6}{'L2 miss%':>10}{'L2 MPKI':>10}{'MPKI/base':>11}"
          f"{'cyc/base':>10}{'mshrMiss/miss':>15}{'L2acc/L1miss':>14}{'L2missLat':>11}  valid")
    for r in rows:
        def f(x, fmt):
            return format(x, fmt) if isinstance(x, (int, float)) else "-"
        print(f"{r['run']:<{rw}}{str(r.get('l2_repl', '-')):<12}{str(r.get('l2_size', '-')):>10}"
              f"{str(r.get('l2_assoc', '-')):>6}"
              f"{f(r.get('l2_miss_rate') and 100 * r['l2_miss_rate'], '.2f'):>10}"
              f"{f(r.get('l2_mpki'), '.3f'):>10}{f(r.get('l2_mpki_vs_base'), '.3f'):>11}"
              f"{f(r.get('cycles_vs_base'), '.3f'):>10}"
              f"{f(div(r.get('l2_mshr_misses'), r.get('l2_misses')), '.3f'):>15}"
              f"{f(r.get('chk_l2acc_per_l1miss'), '.3f'):>14}"
              f"{f(r.get('l2_miss_lat_cyc'), '.1f'):>11}  {r.get('meta_valid', '-')}")

    for m in args.metric:
        print_pivot(rows, args.type, m)


METRICS = {
    "miss": ("L2 miss %", lambda r: r.get("l2_miss_rate") and 100 * r["l2_miss_rate"], ".2f"),
    "mpki": ("L2 MPKI", lambda r: r.get("l2_mpki"), ".3f"),
    "mpki_base": ("MPKI/base", lambda r: r.get("l2_mpki_vs_base"), ".3f"),
    "cyc_base": ("cycles/base", lambda r: r.get("cycles_vs_base"), ".3f"),
}


def print_pivot(rows, t, metric):
    name, get, fmt = METRICS[metric]
    keys = [k for k in KEYS if k not in VARY[t] and k != "workload"]
    for blk in sorted({tuple(str(r.get(k, "")) for k in keys) for r in rows}):
        rs = [r for r in rows if tuple(str(r.get(k, "")) for k in keys) == blk]
        cols = []
        for r in sorted(rs, key=lambda r: col_order(r, t)):
            if col_value(r, t) not in cols:
                cols.append(col_value(r, t))
        print(f"\n[{name}]  " + "  ".join(f"{k.replace('l2_', '')}={v}" for k, v in zip(keys, blk)))
        print(f"{'workload':<12}" + "".join(f"{c.removesuffix('RP'):>10}" for c in cols))
        for wl in sorted({r["workload"] for r in rs}):
            line = f"{wl:<12}"
            for c in cols:
                x = [get(r) for r in rs if r["workload"] == wl and col_value(r, t) == c]
                line += f"{x[0]:>10{fmt}}" if x and isinstance(x[0], (int, float)) else f"{'-':>10}"
            print(line)


if __name__ == "__main__":
    main()
