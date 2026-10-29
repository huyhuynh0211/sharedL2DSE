# L2 leakage power vs active ways (4 banks), from McPAT -> result/l2_leak.csv
# Leakage depends only on the array geometry, so one run's mcpat.xml is reused
# with only L2_config changed (W ways = 64 KiB x W, 1024 sets kept).
# python3 mcpat_flow/mcpat_l2_leak.py <run dir with mcpat.xml> --mcpat ~/mcpat/mcpat
import argparse
import csv
import re
import subprocess
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--mcpat", required=True)
ap.add_argument("--out", default="result/l2_leak.csv")
args = ap.parse_args()

xml = (Path(args.run) / "mcpat.xml").read_text()
m = re.search(r'name="L2_config" value="(\d+),(\d+),(\d+),(\d+),([^"]*)"', xml)
size, line, assoc, banks, rest = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
way_bytes = size // assoc

rows = []
for w in (16, 8, 4, 2, 1):
    cfg = f'name="L2_config" value="{way_bytes * w},{line},{w},{banks},{rest}"'
    f = Path(args.run) / f"mcpat_l2_W{w}.xml"
    f.write_text(xml[:m.start()] + cfg + xml[m.end():])
    res = subprocess.run([args.mcpat, "-infile", str(f), "-print_level", "5"], capture_output=True, text=True)
    i = res.stdout.find("Total L2s:")
    seg = res.stdout[i:i + 1500]
    get = lambda k: float(re.search(rf"{k}\s*=\s*([-\d.eE+]+)", seg).group(1))
    rows.append({"ways": w, "banks": banks, "size_KiB": way_bytes * w // 1024,
                 "P_l2_leak_W": get("Subthreshold Leakage") + get("Gate Leakage")})

Path(args.out).parent.mkdir(parents=True, exist_ok=True)
with open(args.out, "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0]))
    wr.writeheader()
    wr.writerows(rows)
