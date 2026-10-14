import argparse
import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path


def read_stats(path):
    blocks, cur = [], None
    for line in path.read_text().splitlines():
        if "Begin Simulation Statistics" in line:
            cur = {}
        elif "End Simulation Statistics" in line:
            blocks.append(cur)
            cur = None
        elif cur is not None:
            p = line.split()
            if len(p) >= 2:
                try:
                    cur[p[0]] = float(p[1])
                except ValueError:
                    pass
    return blocks[-1] if blocks else {}


class Missing(Exception):
    pass


def make_env(stats, config):
    def S(name, default=None):
        rx = re.compile("^" + re.escape(name).replace(r"\*", r"\d*") + "$")
        vals = [v for k, v in stats.items() if rx.match(k) and not math.isnan(v)]
        if vals:
            return sum(vals)
        if default is None:
            raise Missing("err")
        return default

    def C(path):
        cur = config
        for key in path.split("."):
            if isinstance(cur, list):
                cur = cur[0]
            if key not in cur:
                raise Missing("err")
            cur = cur[key]
        return cur[0] if isinstance(cur, list) else cur

    period = C("system.clk_domain.clock")
    return {"S": S, "C": C, "min": min, "max": max,
            "N": len(config["system"]["cpu"]),
            "MHZ": round(1e6 / period),
            "CYC": round(S("simTicks") / period)}


def fill(template, out, env):
    text = template.read_text()
    m = re.search(r'\t*<component id="system.core0".*?\n\t\t</component>\n', text, re.S)
    N = env["N"]
    cores = ""
    for i in range(N):
        cpu = "system.cpu" if N == 1 else f"system.cpu{i}"
        cores += m.group(0).replace("system.core0", f"system.core{i}").replace('name="core0"', f'name="core{i}"') \
                           .replace("system.cpu*", cpu)
    text = text[:m.start()] + cores + text[m.end():]

    def ev(m):
        v = eval(m.group(1), {"__builtins__": {}}, env)
        return str(int(round(v))) if isinstance(v, float) and abs(v - round(v)) < 1e-9 else str(v)

    text = re.sub(r"\{([^{}]+)\}", ev, text)
    out.write_text(text)


def block_power(text, header):
    i = text.find(header)
    if i < 0:
        return None
    seg = text[i:i + 1500]
    get = lambda k: float(re.search(rf"{k}\s*=\s*([-\d.eE+]+)", seg).group(1))
    return {"sub": get("Subthreshold Leakage"), "gate": get("Gate Leakage"), "dyn": get("Runtime Dynamic")}


def run_one(d, args):
    stats = read_stats(d / "stats.txt")
    config = json.loads((d / "config.json").read_text())
    env = make_env(stats, config)
    if env["S"]("simSeconds") == 0:
        raise Missing("err")
    xml = d / "mcpat.xml"
    fill(Path(args.template), xml, env)
    row = {"run": d.name, "ways": env["C"]("system.l2cache.assoc"),
           "size_KiB": env["C"]("system.l2cache.size") // 1024,
           "repl": env["C"]("system.l2cache.replacement_policy.type"),
           "insts": env["S"]("simInsts"), "time_ms": env["S"]("simSeconds") * 1e3}
    row["E_dram_mJ"] = env["S"]("system.mem_ctrl.dram.rank*.totalEnergy") * 1e-9
    if not args.mcpat:
        return row
    T = env["S"]("simSeconds")
    res = subprocess.run([args.mcpat, "-infile", str(xml), "-print_level", "5"], capture_output=True, text=True)
    (d / "mcpat.txt").write_text(res.stdout + res.stderr)
    for name, header in [("core", "Total Cores:"), ("l2", "Total L2s:"),
                         ("bus", "Total NoCs (Network/Bus):"), ("mc", "Total MCs:")]:
        p = block_power(res.stdout, header)
        if p is None:
            raise Missing("err")
        row[f"E_{name}_leak_mJ"] = (p["sub"] + p["gate"]) * T * 1e3
        row[f"E_{name}_dyn_mJ"] = p["dyn"] * T * 1e3
    row["E_l2_mJ"] = row["E_l2_leak_mJ"] + row["E_l2_dyn_mJ"]
    row["E_total_mJ"] = sum(v for k, v in row.items() if k.startswith("E_") and k.endswith(("leak_mJ", "dyn_mJ"))) \
        + row["E_dram_mJ"]
    row["nJ_per_inst"] = row["E_total_mJ"] * 1e6 / row["insts"]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--template", default=str(Path(__file__).with_name("template_minor4c.xml")))
    ap.add_argument("--mcpat", default="")
    ap.add_argument("--filter", default="")
    ap.add_argument("--out", default="result/energy.csv")
    args = ap.parse_args()

    rows = []
    for d in sorted(p for p in Path(args.runs).iterdir() if p.is_dir() and re.search(args.filter, p.name)):
        if not (d / "stats.txt").exists() or (d / "stats.txt").stat().st_size == 0 or not (d / "config.json").exists():
            continue
        try:
            rows.append(run_one(d, args))
        except Missing:
            pass
    if not rows:
        sys.exit("err")

    rows.sort(key=lambda r: (re.sub(r"W\d+", "", r["run"]), -r["size_KiB"]))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
