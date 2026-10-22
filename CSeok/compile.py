import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description="Compile workload .cpp files for RISC-V")
parser.add_argument("--dir", required=True,
                    help="folder that holds the .cpp files")
parser.add_argument("--cxx", default="riscv64-linux-gnu-g++",
                    help="compiler to use")
args = parser.parse_args()

folder = Path(args.dir)
for src in sorted(folder.glob("*.cpp")):
    out = src.with_suffix(".riscv")

    # skip if the binary exists and is newer than its source
    if out.exists() and out.stat().st_mtime > src.stat().st_mtime:
        print(f"{out.name}: up to date")
        continue

    print(f"{out.name}: compiling")
    cmd = [args.cxx, "-O2", "-static", "-o", str(out), str(src)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)