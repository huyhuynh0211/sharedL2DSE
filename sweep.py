#!/usr/bin/env python3
"""Chạy cva6_baseline.py với nhiều cấu hình, xuất CSV + bảng Markdown cho báo cáo.

    python3 sweep.py --plan ways                 # (1) số way hoạt động, giữ 1024 set
    python3 sweep.py --plan capacity             # (2) dung lượng, 16 way
    python3 sweep.py --plan assoc                # (3) associativity, 1 MiB
    python3 sweep.py --plan all -j 4 --clock 50MHz
    python3 sweep.py --plan ways --quick         # cửa sổ ngắn để thử nhanh

Kết quả: results/<clock>/<plan>/<lần chạy>/summary.json,
         results/<clock>/<plan>.csv và results/<clock>/<plan>.md
Lần chạy đã có summary.json được bỏ qua -> dừng giữa chừng thì chạy lại lệnh cũ là tiếp tục.
Sửa danh sách cấu hình ở phần CẤU HÌNH QUÉT ngay dưới đây.
"""
import argparse
import csv
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------
# CẤU HÌNH QUÉT - sửa ở đây
# ------------------------------------------------------------------------------
FOOTPRINT = "768KiB"                    # tổng 4 core = 12 line / set ở L2 1024 set
WORKLOADS = {                           # tên -> --args của cva6_baseline.py
    "cap":   "cap {fp} 64 {core} 1 0 8",     # quét tuần tự: vách LRU
    "rand":  "rand {fp} 64 {core} 1 0 8",    # ngẫu nhiên độc lập: miss ~ 1 - C/F
    "write": "write {fp} 64 {core} 1 0 8",   # chỉ ghi: writeback
    "binv":  "binv {fp} 64 {core} 1 0 8",    # vùng nóng 8 KiB ở L1 + luồng lạnh qua L2
}
# Plan chỉ chạy một số workload (mặc định: mọi workload trong --workloads)
PLAN_WORKLOADS = {"binv": ["binv"]}
DRAMS = {                               # tên ngắn -> giá trị "dram" của baseline
    "ddr4":    "DDR4_2400_8x8",                         # gem5, baseline
    "ddr5g":   "DDR5_6400_4x8",                         # gem5 có sẵn
    "ds3ddr4": "dramsim3:DDR4_8Gb_x8_2400.ini",         # DRAMsim3, đối chứng với ddr4
    "ds3ddr5": "dramsim3:DDR5_16Gb_x8_4800.ini",
    "ds3ddr5f": "dramsim3:DDR5_16Gb_x8_6400.ini",
    "ds3ddr6": "dramsim3:DDR6_whatif_8800_x8.ini",      # GIẢ ĐỊNH, xem dram_configs/
}
PLANS = {
    "ways":     [("w%d" % w, {"l2.active_ways": w}) for w in (16, 14, 13, 12, 11, 10, 8, 6, 4, 2)],
    "capacity": [("c%s" % s, {"l2.size": s}) for s in ("256KiB", "512KiB", "1MiB", "2MiB")],
    "assoc":    [("a%d" % a, {"l2.size": "1MiB", "l2.assoc": a}) for a in (1, 2, 4, 8, 16, 32)],
    # Back-invalidation: gem5 classic không có L2 inclusive -> đây là đối chứng đo được
    # (non-inclusive mostly_incl và exclusive mostly_excl); phần inclusive: binv_model.py
    "binv":     [(f"{c[7:]}_w{w}", {"l2.clusivity": c, "l2.active_ways": w})
                 for c in ("mostly_incl", "mostly_excl") for w in (16, 12, 11, 10, 8, 4, 2)],
    # DRAM: mỗi loại x 2 điểm way (16 = vừa cache, 8 = phần lớn miss xuống DRAM)
    "dram":     [(f"{tag}_w{w}", {"dram": d, "l2.active_ways": w})
                 for tag, d in DRAMS.items() for w in (16, 8)],
}
QUICK = {"warmup_cycles": 300000, "measure_cycles": 1000000}

COLS = [  # (khóa, tiêu đề) cho CSV / bảng
    ("plan", "Sweep"), ("workload", "Workload"), ("l2_kib", "L2 (KiB)"), ("ways", "Way"),
    ("sets", "Set"), ("clusivity", "L2 incl"), ("dram", "DRAM"),
    ("l1d_miss_pct", "L1D miss (%)"), ("l2_miss_pct", "L2 miss (%)"), ("l2_mpki", "L2 MPKI"),
    ("ipc_mean", "IPC"), ("l1d_miss_lat_cyc", "L1D miss lat (cyc)"),
    ("amat_l1d_cyc", "AMAT (cyc)"), ("cycles", "Cycles"), ("cycles_vs_ref", "Cycles / 1MiB-16w"),
    ("l1d_writebacks", "L1D WB"), ("sanity", "Sanity"), ("valid", "Hợp lệ"),
]


def run_one(job, gem5, binary, clock, extra, force):
    name, outdir, args, sets = job
    if not force and os.path.exists(os.path.join(outdir, "summary.json")):
        return name, "đã có"
    os.makedirs(outdir, exist_ok=True)
    cmd = gem5.split() + ["-d", outdir, os.path.join(HERE, "cva6_baseline.py"),
                          "--binary", binary, "--clock", clock, "--footprint", FOOTPRINT,
                          "--args", args, "--tag", name]
    for k, v in {**sets, **extra}.items():
        cmd += ["--set", f"{k}={v}"]
    t0 = time.time()
    with open(os.path.join(outdir, "run.log"), "w") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
    ok = rc == 0 and os.path.exists(os.path.join(outdir, "summary.json"))
    return name, f"xong {time.time() - t0:.0f} s" if ok else f"LỖI rc={rc}, xem {outdir}/run.log"


def load_rows(plan, plan_dir):
    rows = []
    for name in sorted(os.listdir(plan_dir)):
        f = os.path.join(plan_dir, name, "summary.json")
        if not os.path.exists(f):
            continue
        s = json.load(open(f))
        p, m = s["params"], s["metrics"]
        rows.append(dict(
            plan=plan, workload=name.split("_")[0], run=name, clock=p["clock"],
            l2_kib=p["l2_bytes"] // 1024, ways=p["l2_assoc"], sets=p["l2_sets"],
            l2_miss_pct=None if m["l2_miss_rate"] is None else 100 * m["l2_miss_rate"],
            l2_mpki=m["l2_mpki"], ipc_mean=m["ipc_mean"], l1d_miss_lat_cyc=m["l1d_miss_lat_cyc"],
            amat_l1d_cyc=m["amat_l1d_cyc"], cycles=m["cycles"], l1d_writebacks=m["l1d_writebacks"],
            sanity=m["sanity_l2acc_over_l1miss"], valid=s["valid"],
            l2_hit_cyc=p["l2"]["hit"], ns_per_cycle=p["ns_per_cycle"],
            noc_cyc="/".join(str(p["noc"][k]) for k in ("frontend", "forward", "response")),
            dram=p["dram"], clusivity=p["l2"]["clusivity"],
            l1d_miss_pct=None if m["l1d_miss_rate"] is None else 100 * m["l1d_miss_rate"]))
    # Tham chiếu: 1 MiB / 16 way, cùng workload (cấu hình production)
    ref = {}
    for r in rows:
        if r["l2_kib"] == 1024 and r["ways"] == 16:
            ref[r["workload"]] = r["cycles"]
    if not ref:                          # plan không chứa 1 MiB/16w: lấy từ plan "ways"
        other = os.path.join(os.path.dirname(plan_dir), "ways")
        for name in os.listdir(other) if os.path.isdir(other) else []:
            f = os.path.join(other, name, "summary.json")
            if name.endswith("_w16") and os.path.exists(f):
                ref[name.split("_")[0]] = json.load(open(f))["metrics"]["cycles"]
    for r in rows:
        b = ref.get(r["workload"])
        r["cycles_vs_ref"] = r["cycles"] / b if b and r["cycles"] else None
    order = list(WORKLOADS)
    dorder = list(DRAMS.values())
    rows.sort(key=lambda r: (order.index(r["workload"]) if r["workload"] in order else 99,
                             r["clusivity"],
                             dorder.index(r["dram"]) if r["dram"] in dorder else 99,
                             -r["l2_kib"], -r["ways"]))
    return rows


def fmt(v, key):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "có" if v else "KHÔNG"
    if isinstance(v, float):
        if key in ("cycles", "l1d_writebacks"):
            return f"{v:,.0f}"
        return f"{v:.2f}" if key in ("l2_miss_pct", "l1d_miss_pct", "l1d_miss_lat_cyc") else f"{v:.3f}"
    return str(v)


def write_outputs(plan, rows, base, clock):
    csv_path, md_path = os.path.join(base, f"{plan}.csv"), os.path.join(base, f"{plan}.md")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    r0 = rows[0]
    lines = [f"### Sweep `{plan}` @ {clock}, footprint tổng {FOOTPRINT}", "",
             f"Giả định độ trễ (Assumed): 1 chu kỳ = {r0['ns_per_cycle']:g} ns; L2 hit "
             f"{r0['l2_hit_cyc']} chu kỳ; NoC frontend/forward/response {r0['noc_cyc']} chu kỳ; " +
             (f"DRAM {r0['dram']} (gem5 tính theo ns)." if plan != "dram" else
              "DRAM theo cột DRAM; *_whatif_* là GIẢ ĐỊNH, DRAMsim3 DDR5 là APPROXIMATED."), "",
             "| " + " | ".join(h for _, h in COLS) + " |", "|" + "---|" * len(COLS)]
    lines += ["| " + " | ".join(fmt(r[k], k) for k, _ in COLS) + " |" for r in rows]
    lines += ["", "Nhãn: L2 miss, MPKI, IPC, độ trễ miss L1D, cycles = Measured (mô hình gem5); "
              "AMAT = Computed (1 + m_L1 x độ trễ miss L1D); độ trễ L2/NoC theo chu kỳ = Assumed. "
              "Sanity = L2 accesses / tổng L1 miss, phải ≈ 1."]
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return csv_path, md_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default="ways", choices=list(PLANS) + ["all"])
    ap.add_argument("--clock", default="100MHz", choices=["100MHz", "50MHz"])
    ap.add_argument("--workloads", default="cap,rand,write",
                    help="chọn bớt workload, vd cap,rand")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--gem5", default=os.environ.get(
        "GEM5", os.path.expanduser("~/gem5/build/RISCV/gem5.opt")))
    ap.add_argument("--binary", default=os.path.join(HERE, "build", "l2_workloads"))
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--quick", action="store_true", help="cửa sổ ngắn để thử (số liệu chưa ổn định)")
    ap.add_argument("--force", action="store_true", help="chạy lại cả lần đã có kết quả")
    ap.add_argument("--table-only", action="store_true", help="chỉ gom kết quả có sẵn thành bảng")
    a = ap.parse_args()

    plans = [k for k in PLANS if k != "dram"] if a.plan == "all" else [a.plan]   # dram: chạy riêng
    wls = [w.strip() for w in a.workloads.split(",")]
    base = os.path.join(a.out, a.clock + ("_quick" if a.quick else ""))
    extra = QUICK if a.quick else {}

    for plan in plans:
        plan_dir = os.path.join(base, plan)
        jobs = [(f"{wl}_{tag}", os.path.join(plan_dir, f"{wl}_{tag}"), WORKLOADS[wl], sets)
                for wl in PLAN_WORKLOADS.get(plan, wls) for tag, sets in PLANS[plan]]
        if not a.table_only:
            print(f"[*] {plan} @ {a.clock}: {len(jobs)} lần chạy, {a.jobs} song song -> {plan_dir}",
                  flush=True)
            with ThreadPoolExecutor(max_workers=a.jobs) as ex:
                for name, status in ex.map(
                        lambda j: run_one(j, a.gem5, a.binary, a.clock, extra, a.force), jobs):
                    print(f"    {name:<14} {status}", flush=True)
        if not os.path.isdir(plan_dir):
            continue
        rows = load_rows(plan, plan_dir)
        if rows:
            c, m = write_outputs(plan, rows, base, a.clock)
            bad = [r["run"] for r in rows if not r["valid"]]
            print(f"[*] {len(rows)} dòng -> {c}, {m}" + (f"; KHÔNG hợp lệ: {bad}" if bad else ""))


if __name__ == "__main__":
    main()
