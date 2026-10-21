# ==============================================================================
# cva6_baseline.py - Baseline cụm 4 core CVA6 + L1 riêng + NoC + L2 chia sẻ + DDR4
#                    gem5 classic, SE mode, xung nhịp 100 MHz hoặc 50 MHz
# Phụ trách: Tiến Anh
#
# 1) Chạy trực tiếp:
#    gem5.opt -d out/x cva6_baseline.py --binary build/l2_workloads \
#        --args "cap {fp} 64 {core} 1 0 8" [--clock 50MHz] [--set l2.active_ways=8]
#    {core} = số thứ tự core, {fp} = footprint mỗi core (--footprint chia 4)
#
# 2) Dùng như "core" trong script gem5 của bạn khác:
#    from cva6_baseline import make_params, build_system, run_and_report
#    p = make_params("100MHz", {"l2.repl": "fifo"})
#    system = build_system(p, binary, [["mode", "...", ...] for mỗi core])
#    run_and_report(system, p)
# ==============================================================================
import argparse
import copy
import json
import math
import os

import m5
from m5.objects import *

# ------------------------------------------------------------------------------
# THÔNG SỐ BASELINE (độ trễ tính theo chu kỳ của clock)
# Nguồn: RTL = openhwgroup/cva6 @81245a4 cv64a6_imafdc_sv39_wb;
#        ASSUMED = giả định, thay bằng số chip thật khi có.
# ------------------------------------------------------------------------------
BASELINE = {
    "num_cores": 4,
    "line_bytes": 64,
    "mem_size": "512MiB",
    "core": {"issue_width": 1,              # RTL: SuperscalarEn = 0
             "commit_width": 2,             # RTL: NrCommitPorts = 2
             "decode_to_execute_delay": 2}, # thêm 1 chu kỳ ~ tầng Issue (APPROX)
    "l1i": {"size": "16KiB", "assoc": 4,    # RTL
            "lat": 1, "mshrs": 1, "tgts_per_mshr": 8, "write_buffers": 8, "repl": "random"},
    "l1d": {"size": "32KiB", "assoc": 8,    # RTL; write-back (gem5 classic)
            "lat": 1, "mshrs": 1, "tgts_per_mshr": 8, "write_buffers": 8, "repl": "random"},
    "noc": {"width": 16, "frontend": 1, "forward": 1, "response": 1},    # L2XBar, ASSUMED
    "l2": {"prod_size": "1MiB", "full_ways": 16, "active_ways": 16,      # 1024 set
           "size": None, "assoc": None,     # đặt size (+assoc) để quét dung lượng / assoc
           "hit": 2, "resp": 1,             # ASSUMED, ghi đè theo clock bên dưới
           "repl": "lru", "clusivity": "mostly_incl", "writeback_clean": False,
           "mshrs": 32, "tgts_per_mshr": 12, "write_buffers": 16},
    "dram": "DDR4_2400_8x8",                # gem5 mô hình theo ns -> đúng ở mọi clock
    "warmup_cycles": 2_000_000,
    "measure_cycles": 10_000_000,           # 0 = chạy tới khi mọi tiến trình kết thúc
}

# Độ trễ phụ thuộc clock (ASSUMED: L2 ~14 ns, NoC 1-2 ns, làm tròn lên chu kỳ)
CLOCK_PRESETS = {
    "100MHz": {"l2.hit": 2, "l2.resp": 1, "noc.frontend": 1, "noc.forward": 1, "noc.response": 1},
    "50MHz":  {"l2.hit": 1, "l2.resp": 1, "noc.frontend": 1, "noc.forward": 1, "noc.response": 1},
}

REPL = {"lru": "LRURP", "random": "RandomRP", "fifo": "FIFORP", "treeplru": "TreePLRURP",
        "nru": "NRURP", "srrip": "SRRIPRP", "mru": "MRURP", "lip": "LIPRP"}


def _bytes(s):
    num = "".join(ch for ch in str(s) if ch.isdigit())
    unit = str(s)[len(num):].strip()
    return int(num) * {"": 1, "B": 1, "KiB": 1 << 10, "kB": 1 << 10, "KB": 1 << 10,
                       "MiB": 1 << 20, "MB": 1 << 20}[unit]


def _set(p, key, value):
    node, *path = p, *key.split(".")
    for k in path[:-1]:
        node = node[k]
    if path[-1] not in node:
        raise KeyError(f"Không có tham số '{key}' trong baseline")
    node[path[-1]] = value


def make_params(clock="100MHz", overrides=None):
    """Thông số baseline cho clock, cộng các ghi đè {'l2.active_ways': 8, ...}."""
    if clock not in CLOCK_PRESETS:
        raise ValueError(f"clock phải là một trong {list(CLOCK_PRESETS)}")
    p = copy.deepcopy(BASELINE)
    p["clock"] = clock
    for k, v in {**CLOCK_PRESETS[clock], **(overrides or {})}.items():
        _set(p, k, v)

    l2, line = p["l2"], p["line_bytes"]
    if l2["size"] is None:                  # tắt way: giữ số set production
        sets = _bytes(l2["prod_size"]) // (line * l2["full_ways"])
        p["l2_bytes"], p["l2_assoc"] = sets * line * l2["active_ways"], l2["active_ways"]
    else:
        p["l2_bytes"], p["l2_assoc"] = _bytes(l2["size"]), l2["assoc"] or l2["full_ways"]
    p["l2_sets"] = p["l2_bytes"] // (line * p["l2_assoc"])
    if p["l2_sets"] & (p["l2_sets"] - 1) or p["l2_sets"] * line * p["l2_assoc"] != p["l2_bytes"]:
        raise ValueError(f"L2 {p['l2_bytes']} B / {p['l2_assoc']} way: số set không phải lũy thừa 2")
    p["ns_per_cycle"] = 1e3 / float(clock[:-3])
    return p


# ------------------------------------------------------------------------------
# DỰNG HỆ THỐNG
# ------------------------------------------------------------------------------
def _cache(c, **extra):
    return Cache(size=c["size"], assoc=c["assoc"], tag_latency=c["lat"], data_latency=c["lat"],
                 response_latency=c["lat"], mshrs=c["mshrs"], tgts_per_mshr=c["tgts_per_mshr"],
                 write_buffers=c["write_buffers"], replacement_policy=globals()[REPL[c["repl"]]](),
                 writeback_clean=False, **extra)


def build_system(p, binary, cmd_per_core):
    """cmd_per_core: danh sách tham số dòng lệnh (không gồm tên binary) cho từng core."""
    system = System()
    system.clk_domain = SrcClockDomain(clock=p["clock"], voltage_domain=VoltageDomain())
    system.mem_mode = "timing"
    system.mem_ranges = [AddrRange(p["mem_size"])]
    system.cache_line_size = p["line_bytes"]

    c = p["core"]
    system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(p["num_cores"])]
    for cpu in system.cpu:
        cpu.decodeInputWidth = cpu.executeInputWidth = cpu.executeIssueLimit = c["issue_width"]
        cpu.executeCommitLimit = c["commit_width"]
        cpu.decodeToExecuteForwardDelay = c["decode_to_execute_delay"]

    n = p["noc"]
    system.noc = L2XBar(width=n["width"], frontend_latency=n["frontend"],
                        forward_latency=n["forward"], response_latency=n["response"])
    l2 = p["l2"]
    system.l2 = Cache(size=f"{p['l2_bytes']}B", assoc=p["l2_assoc"],
                      tag_latency=l2["hit"], data_latency=l2["hit"], response_latency=l2["resp"],
                      sequential_access=False,          # tag và data song song: hit = l2.hit
                      replacement_policy=globals()[REPL[l2["repl"]]](),
                      clusivity=l2["clusivity"], writeback_clean=l2["writeback_clean"],
                      prefetcher=NULL, mshrs=l2["mshrs"], tgts_per_mshr=l2["tgts_per_mshr"],
                      write_buffers=l2["write_buffers"])
    system.membus = SystemXBar()

    for cpu in system.cpu:
        cpu.icache = _cache(p["l1i"], is_read_only=True)
        cpu.dcache = _cache(p["l1d"])
        cpu.icache_port = cpu.icache.cpu_side
        cpu.dcache_port = cpu.dcache.cpu_side
        cpu.icache.mem_side = system.noc.cpu_side_ports
        cpu.dcache.mem_side = system.noc.cpu_side_ports
        cpu.createInterruptController()
    system.l2.cpu_side = system.noc.mem_side_ports
    system.l2.mem_side = system.membus.cpu_side_ports

    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = globals()[p["dram"]]()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports
    system.system_port = system.membus.cpu_side_ports

    system.workload = SEWorkload.init_compatible(binary)
    for i, cpu in enumerate(system.cpu):
        proc = Process(pid=100 + i)
        proc.cmd = [binary] + [str(a) for a in cmd_per_core[i]]
        cpu.workload = proc
        cpu.createThreads()
    return system


# ------------------------------------------------------------------------------
# CHẠY VÀ ĐO HIỆU NĂNG
# ------------------------------------------------------------------------------
def _read_stats(path):
    stats = {}
    with open(path) as f:
        for line in f:
            if line.startswith("---------- Begin"):
                stats = {}                  # chỉ giữ lần dump cuối
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("-"):
                try:
                    stats[parts[0]] = float(parts[1])
                except ValueError:
                    pass
    return stats


def compute_metrics(stats, p):
    """Measured: số đếm, độ trễ; Computed: AMAT. Stat đếm vắng mặt = 0 (gem5 bỏ stat bằng 0)."""
    tpc = 1e3 * p["ns_per_cycle"]                       # tick (1 ps) / chu kỳ
    g = lambda k: stats.get(k, 0.0)                     # noqa: E731
    cyc, ins, l1a, l1m, l1i, lat_w = [], [], 0, 0, 0, 0
    for i in range(p["num_cores"]):
        c = f"system.cpu{i}"
        cyc.append(g(f"{c}.numCycles"))
        ins.append(stats.get(f"{c}.committedInsts", g(f"{c}.commitStats0.numInsts")))
        m = g(f"{c}.dcache.demandMisses::total")
        l1a += g(f"{c}.dcache.demandAccesses::total")
        l1m += m
        l1i += g(f"{c}.icache.demandMisses::total")
        lat_w += m * g(f"{c}.dcache.demandAvgMissLatency::total")
    div = lambda a, b: a / b if b else None              # noqa: E731
    insts, l2a, l2m = sum(ins), g("system.l2.demandAccesses::total"), g("system.l2.demandMisses::total")
    m1, lat = div(l1m, l1a), div(div(lat_w, l1m) or 0, tpc)
    return {
        "cycles": max(cyc), "insts": insts,
        "ipc_mean": div(sum(div(a, b) or 0 for a, b in zip(ins, cyc)), p["num_cores"]),
        "l1d_miss_rate": m1, "l2_miss_rate": div(l2m, l2a),
        "l1d_mpki": div(1000 * l1m, insts), "l2_mpki": div(1000 * l2m, insts),
        "l1d_miss_lat_cyc": lat, "amat_l1d_cyc": 1 + m1 * lat if m1 is not None and lat else None,
        "l2_accesses": l2a, "l2_misses": l2m,
        "l2_mshr_hits": g("system.l2.demandMshrHits::total"),
        "l2_upgrade_misses": g("system.l2.UpgradeReq.misses::total"),
        "l1d_writebacks": sum(g(f"system.cpu{i}.dcache.writebacks::total")
                              for i in range(p["num_cores"])),
        "sanity_l2acc_over_l1miss": div(l2a, l1m + l1i),
    }


def run_and_report(system, p, tag=""):
    """Warm-up, reset stats, đo trong cửa sổ, rồi ghi summary.json vào thư mục -d."""
    Root(full_system=False, system=system)
    m5.instantiate()
    ticks = lambda cyc: int(math.floor(cyc * p["ns_per_cycle"] * 1e3 + 0.5))   # noqa: E731
    limit = "simulate() limit reached"
    if p["warmup_cycles"] > 0:
        ev = m5.simulate(ticks(p["warmup_cycles"]))
        if ev.getCause() != limit:
            raise SystemExit(f"[!] Dừng trong warm-up: {ev.getCause()}")
        m5.stats.reset()
    ev = m5.simulate(ticks(p["measure_cycles"])) if p["measure_cycles"] > 0 else m5.simulate()
    m5.stats.dump()
    valid = p["measure_cycles"] == 0 or ev.getCause() == limit

    out = m5.options.outdir
    m = compute_metrics(_read_stats(os.path.join(out, "stats.txt")), p)
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump({"tag": tag, "valid": valid, "exit_cause": ev.getCause(),
                   "params": p, "metrics": m}, f, indent=2, ensure_ascii=False)
    f_ = lambda x, s: "n/a" if x is None else format(x, s)      # noqa: E731
    print(f"[*] {ev.getCause()}{'' if valid else '  [!] có core xong giữa cửa sổ đo -> KHÔNG hợp lệ'}")
    print(f"[*] cycles={m['cycles']:.0f} IPC={f_(m['ipc_mean'], '.3f')} "
          f"L1D miss={f_(m['l1d_miss_rate'], '.2%')} L2 miss={f_(m['l2_miss_rate'], '.2%')} "
          f"L2 MPKI={f_(m['l2_mpki'], '.3f')} L1D miss lat={f_(m['l1d_miss_lat_cyc'], '.1f')} "
          f"AMAT={f_(m['amat_l1d_cyc'], '.3f')} chu kỳ")
    print(f"[*] Sanity L2 acc / Σ L1 miss = {f_(m['sanity_l2acc_over_l1miss'], '.3f')} (≈1); "
          f"đã ghi {out}/summary.json")
    return m


# ------------------------------------------------------------------------------
# CHẠY TRỰC TIẾP BẰNG gem5 (gem5 chạy script với __name__ == "__m5_main__")
# ------------------------------------------------------------------------------
if __name__ in ("__m5_main__", "__main__"):
    ap = argparse.ArgumentParser(description="Baseline cụm 4 core CVA6 + L2 chia sẻ")
    ap.add_argument("--binary", required=True, help="chương trình RISC-V (link static)")
    ap.add_argument("--args", default="cap {fp} 64 {core} 1 0 8",
                    help="tham số cho mỗi core; {core} = số core, {fp} = footprint mỗi core")
    ap.add_argument("--footprint", default="768KiB", help="footprint TỔNG của 4 core")
    ap.add_argument("--clock", default="100MHz", choices=list(CLOCK_PRESETS))
    ap.add_argument("--set", action="append", default=[], metavar="KHÓA=GIÁ_TRỊ",
                    help="ghi đè thông số, vd --set l2.active_ways=8 --set l2.repl=fifo")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    over = {}
    for s in a.set:
        k, v = s.split("=", 1)
        try:
            over[k] = json.loads(v)
        except json.JSONDecodeError:
            over[k] = v
    params = make_params(a.clock, over)
    fp = _bytes(a.footprint) // params["num_cores"]
    cmds = [a.args.format(core=i, fp=fp).split() for i in range(params["num_cores"])]

    print("=" * 72)
    print(f"Baseline 4 core CVA6 @ {params['clock']} ({params['ns_per_cycle']:g} ns/chu kỳ); "
          f"L2 {params['l2_bytes'] // 1024} KiB / {params['l2_assoc']}w / {params['l2_sets']} set, "
          f"hit {params['l2']['hit']} chu kỳ, repl {params['l2']['repl']}")
    print(f"Workload: {a.binary} {' '.join(cmds[0])}  (core 0)")
    print("=" * 72)
    run_and_report(build_system(params, a.binary, cmds), params, a.tag)
