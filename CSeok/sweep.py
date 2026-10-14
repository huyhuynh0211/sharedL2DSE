import subprocess

GEM5   = "build/RISCV/gem5.opt"
CONFIG = "dse/test/model.py"

sizes  = ["4KiB", "8KiB", "16KiB", "32KiB", "64KiB"]
assocs = [1, 2, 4, 8]
repl  = ["LRU", "FIFO", "Random", "TreePLRU"]

for size in sizes:
    for assoc in assocs:
        for rep in repl:
            if repl == "TreePLRU" and assoc == 1:
                continue
            outdir = f"dse/test/runs/l1d_{size}_a{assoc}_{rep}"
            cmd = [GEM5, "-d", outdir, CONFIG,
                   "--l1d_size", size, "--l1d_assoc", str(assoc), "--l1d_repl", rep]

            print(f"running {outdir} ...")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                print("  FAILED. Last part of the error:")
                print(result.stderr[-800:])