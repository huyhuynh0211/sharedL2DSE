import argparse
import itertools
import json
import subprocess
from pathlib import Path

MIXES = {
    "loop":        ["loop768k", "empty", "empty", "empty"],
    "temporal":    ["temporal", "empty", "empty", "empty"],
    "graph":       ["graph", "empty", "empty", "empty"],
    "stream":      ["stream", "empty", "empty", "empty"],
    "loop_x4":     ["loop768k", "loop768k", "loop768k", "loop768k"],
    "temporal_x4": ["temporal", "temporal", "temporal", "temporal"],
    "graph_x4":    ["graph", "graph", "graph", "graph"],
    "stream_x4":   ["stream", "stream", "stream", "stream"],
    "mix":         ["temporal", "stream", "loop768k", "graph"],
}

SWEEP = {
    #"mix":     list(MIXES.keys()),
    "mix":     ["temporal", "temporal_x4", "mix"],
    "l2_size": ["256KiB", "512KiB", "1MiB", "2MiB", "4MiB"],
}

parser = argparse.ArgumentParser(description="Run a gem5 sweep")
parser.add_argument("--gem5", default="~/gem5/build/RISCV/gem5.opt",
                    help="path to gem5.opt")
parser.add_argument("--config", required=True,
                    help="gem5 config script, e.g. dse/test/model.py")
parser.add_argument("--out", required=True,
                    help="new folder for this sweep's runs")
parser.add_argument("--bin_dir", required=True,
                    help="folder with the compiled .riscv workloads, e.g. CSeok/workloads")
args = parser.parse_args()

gem5 = Path(args.gem5).expanduser().resolve()
config = Path(args.config).resolve()
out = Path(args.out)
bin_dir = Path(args.bin_dir).resolve()

if not bin_dir.exists():
    raise SystemExit(f"bin_dir not found at {bin_dir}")
if not gem5.exists():
    raise SystemExit(f"gem5 not found at {gem5}, give the right path with --gem5")
if not config.exists():
    raise SystemExit(f"config not found at {config}")
if out.exists():
    raise SystemExit(f"{out} already exists, pick a new --out")

names = list(SWEEP.keys())
run = 0
failed = []
for values in itertools.product(*SWEEP.values()):
    cfg = dict(zip(names, values))

    folder = f"{run:03d}_" + "_".join(str(v) for v in values)
    run_dir = out / folder
    run += 1
    run_dir.mkdir(parents=True)
    (run_dir / "params.json").write_text(json.dumps(cfg, indent=2))

    cmd = [str(gem5), "-d", str(run_dir), str(config), "--bin_dir", str(bin_dir)]
    for name, value in cfg.items():
        if name == "mix":
            cmd += ["--workload"] + MIXES[value]
        else:
            cmd += [f"--{name}", str(value)]

    print(f"{run_dir.name}: {cfg}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    (run_dir / "gem5.log").write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        failed.append(run_dir.name)
        print("   FAILED, see", run_dir / "gem5.log")

print(f"done: {run} runs, {len(failed)} failed")
for f in failed:
    print("   ", f)