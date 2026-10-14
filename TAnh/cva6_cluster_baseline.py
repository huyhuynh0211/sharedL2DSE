# ==============================================================================
# PROJECT: Shared L2 Design Space Exploration
# SCRIPT: cva6_cluster_baseline.py
# ROLE: SoC & Interconnect Architect (Tiến Anh)
# DESCRIPTION: STABLE 4-Core CVA6 (6-stage latency) + 128-bit NoC + Shared L2 + DDR4
# ==============================================================================

import argparse
import json
import os
import re
 
import m5
from m5.objects import *
 
LINE = 64          # [SPEC] line 64 B
FULL_WAYS = 16     # [SPEC] 16 way
 
 
def parse_bytes(s):
    """'1MiB' / '512KiB' / '2097152' -> số byte."""
    m = re.fullmatch(r"\s*(\d+)\s*(B|KiB|KB|MiB|MB|GiB|GB)?\s*", str(s))
    if not m:
        raise ValueError(f"Không đọc được kích thước: {s}")
    mult = {None: 1, "B": 1, "KiB": 1024, "KB": 1024, "MiB": 1 << 20,
            "MB": 1 << 20, "GiB": 1 << 30, "GB": 1 << 30}[m.group(2)]
    return int(m.group(1)) * mult
 
 
# ------------------------------------------------------------------------------
# BƯỚC 1: THAM SỐ DÒNG LỆNH
# ------------------------------------------------------------------------------
p = argparse.ArgumentParser(description="4-core CVA6-like cluster, shared L2 DSE")
p.add_argument("--binary", required=True, help="chương trình RISC-V (link static)")
p.add_argument("--workload", default="cap",
               choices=["cap", "cap_rand", "binv", "write", "rmw"],
               help="chế độ của l2_workloads.c")
p.add_argument("--footprint", default="2MiB",
               help="TỔNG footprint của cả 4 core (mỗi core dùng 1/4)")
p.add_argument("--stride", type=int, default=64, help="bước nhảy (byte)")
p.add_argument("--seed", type=int, default=1, help="seed cho cap_rand")
 
# Hình học L2: mặc định là sweep (1) - tắt way, giữ nguyên số set
p.add_argument("--l2-prod-size", default="1MiB", help="[SPEC] dung lượng production")
p.add_argument("--l2-active-ways", type=int, default=FULL_WAYS,
               help="sweep (1): số way còn bật, số set giữ nguyên")
p.add_argument("--l2-size", default=None,
               help="sweep (2)/(3): đặt thẳng dung lượng (bỏ qua --l2-active-ways)")
p.add_argument("--l2-assoc", type=int, default=None,
               help="sweep (3): số way khi dùng --l2-size (mặc định 16)")
p.add_argument("--l2-tag-lat", type=int, default=14)
p.add_argument("--l2-data-lat", type=int, default=14)
p.add_argument("--l2-resp-lat", type=int, default=14)
 
# Cửa sổ đo: chỉ đo khi cả 4 core đang chạy
p.add_argument("--warmup-cycles", type=int, default=2_000_000)
p.add_argument("--measure-cycles", type=int, default=10_000_000)
args = p.parse_args()
 
# Hình học L2
prod_bytes = parse_bytes(args.l2_prod_size)
SETS_PROD = prod_bytes // (LINE * FULL_WAYS)
if args.l2_size is None:                                  # sweep (1)
    if not 1 <= args.l2_active_ways <= FULL_WAYS:
        raise ValueError("--l2-active-ways phải trong 1..16")
    l2_assoc = args.l2_active_ways
    l2_bytes = SETS_PROD * LINE * l2_assoc
    sweep = "active_ways"
else:                                                     # sweep (2) hoặc (3)
    l2_bytes = parse_bytes(args.l2_size)
    l2_assoc = args.l2_assoc or FULL_WAYS
    sweep = "capacity" if args.l2_assoc is None else "assoc"
l2_sets = l2_bytes // (LINE * l2_assoc)
if l2_sets * LINE * l2_assoc != l2_bytes or l2_sets & (l2_sets - 1):
    raise ValueError(f"Số set L2 = {l2_sets} không phải lũy thừa 2")
 
footprint = parse_bytes(args.footprint)
NUM_CORES = 4
 
 
# ------------------------------------------------------------------------------
# BƯỚC 2: CORE (MinorCPU chỉnh về phía CVA6)
# ------------------------------------------------------------------------------
class CVA6Core(RiscvMinorCPU):
    # [RTL] SuperscalarEn = 0 -> phát 1 lệnh/cycle. MinorCPU mặc định là 2-wide.
    decodeInputWidth = 1
    executeInputWidth = 1
    executeIssueLimit = 1
    # [RTL] NrCommitPorts = 2
    executeCommitLimit = 2
    # [APPROX] thêm 1 cycle giữa Decode và Execute, coi như tầng Issue của CVA6.
    # Chỉ làm tăng phạt khi đoán sai nhánh, không biến MinorCPU thành 6 tầng.
    decodeToExecuteForwardDelay = 2
    # TODO [RTL] branch predictor: CVA6 có BHT 128, BTB 32, RAS 2. Tên tham số
    # branchPred thay đổi giữa các bản gem5, nên tra bản đang pin rồi mới đặt.
 
 
# ------------------------------------------------------------------------------
# BƯỚC 3: CACHE, NoC, DRAM
# ------------------------------------------------------------------------------
class L1Cache(Cache):
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 1              # [BASE] RTL CVA6 có 1 read MSHR mỗi L1
    tgts_per_mshr = 8
    write_buffers = 8      # [RTL] WtDcacheWbufDepth = 8
 
 
class L1ICache(L1Cache):
    size = "16KiB"         # [RTL] IcacheByteSize = 16384
    assoc = 4              # [RTL] IcacheSetAssoc = 4
    is_read_only = True
    writeback_clean = False
 
 
class L1DCache(L1Cache):
    size = "32KiB"         # [RTL] DcacheByteSize = 32768
    assoc = 8              # [RTL] DcacheSetAssoc = 8
    # [APPROX] gem5 classic chỉ có write-back. RTL mặc định là WT; base model dùng
    # biến thể _wb. Line L1 trong RTL là 16 B, ở đây 64 B (gem5 dùng 1 line size).
 
 
class SharedL2Cache(Cache):
    mshrs = 32             # [BASE] cố định, ngoài phạm vi sweep
    tgts_per_mshr = 12
    write_buffers = 16
    clusivity = "mostly_incl"     # [SPEC] non-inclusive: KHÔNG có back-invalidation
    writeback_clean = False       # [SPEC]
    # Không gắn prefetcher [SPEC]; replacement đặt ở dưới.
 
 
class ClusterNoC(L2XBar):
    width = 16             # [BASE] 128-bit = 16 B/cycle (bản cũ đặt 32 = 256-bit)
    frontend_latency = 2
    forward_latency = 2
    response_latency = 2
 
 
# ------------------------------------------------------------------------------
# BƯỚC 4: DỰNG HỆ THỐNG
# ------------------------------------------------------------------------------
system = System()
system.clk_domain = SrcClockDomain(clock="1GHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.cache_line_size = LINE
system.mem_ranges = [AddrRange("512MiB")]
 
system.cpu = [CVA6Core(cpu_id=i) for i in range(NUM_CORES)]
system.noc = ClusterNoC()
system.l2cache = SharedL2Cache(
    size=f"{l2_bytes}B", assoc=l2_assoc,
    tag_latency=args.l2_tag_lat, data_latency=args.l2_data_lat,
    response_latency=args.l2_resp_lat,
    replacement_policy=LRURP())   # [SPEC] LRU: W way = cache W-way chính xác
system.membus = SystemXBar()
 
for core in system.cpu:
    core.icache = L1ICache()
    core.dcache = L1DCache()
    core.icache_port = core.icache.cpu_side
    core.dcache_port = core.dcache.cpu_side
    core.icache.mem_side = system.noc.cpu_side_ports
    core.dcache.mem_side = system.noc.cpu_side_ports
    core.createInterruptController()
 
system.l2cache.cpu_side = system.noc.mem_side_ports
system.l2cache.mem_side = system.membus.cpu_side_ports
 
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR4_2400_8x8()   # [BASE] DDR4-2400 (bản cũ dùng DDR5-8400)
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports
system.system_port = system.membus.cpu_side_ports
 
 
# ------------------------------------------------------------------------------
# BƯỚC 5: TIẾN TRÌNH (4 bản độc lập, SE mode)
# ------------------------------------------------------------------------------
system.workload = SEWorkload.init_compatible(args.binary)
for i, core in enumerate(system.cpu):
    proc = Process(pid=100 + i)
    # l2_workloads <mode> <footprint mỗi core> <stride> <core_id> <seed> <iters=0: chạy mãi>
    proc.cmd = [args.binary, args.workload, str(footprint // NUM_CORES),
                str(args.stride), str(i), str(args.seed + i), "0"]
    core.workload = proc
    core.createThreads()
 
 
# ------------------------------------------------------------------------------
# BƯỚC 6: CHẠY - warm-up rồi đo trong cửa sổ cố định
# ------------------------------------------------------------------------------
root = Root(full_system=False, system=system)
m5.instantiate()
 
CYCLE = m5.ticks.fromSeconds(1e-9)       # 1 GHz
LIMIT = "simulate() limit reached"
 
print(f"[*] L2 {l2_bytes // 1024} KiB, {l2_assoc}-way, {l2_sets} set ({sweep}); "
      f"workload={args.workload}, footprint={footprint} B tổng, stride={args.stride}")
 
ev = m5.simulate(args.warmup_cycles * CYCLE)
if ev.getCause() != LIMIT:
    raise SystemExit(f"[!] Dừng trong warm-up: {ev.getCause()} - cửa sổ đo không hợp lệ")
m5.stats.reset()
ev = m5.simulate(args.measure_cycles * CYCLE)
if ev.getCause() != LIMIT:
    raise SystemExit(f"[!] Có core kết thúc trong cửa sổ đo: {ev.getCause()}")
m5.stats.dump()
 
 
# ------------------------------------------------------------------------------
# BƯỚC 7: LƯU THAM SỐ + TRÍCH SỐ LIỆU CHÍNH (bảng tổng hợp do script sweep gom)
# ------------------------------------------------------------------------------
out_dir = m5.options.outdir
params = dict(vars(args), l2_bytes=l2_bytes, l2_assoc_eff=l2_assoc,
              l2_sets=l2_sets, sweep=sweep, footprint_bytes=footprint)
with open(os.path.join(out_dir, "run_params.json"), "w") as f:
    json.dump(params, f, indent=2)
 
WANTED = [  # regex; tên stat khác nhau giữa các bản gem5, thiếu thì báo
    r"system\.l2cache\.demand(Accesses|Hits|Misses|MissRate)::total",
    r"system\.l2cache\.demand(Accesses|Misses)::.*cpu\d.*",
    r"system\.l2cache\.writebacks::total",
    r"system\.cpu\d\.dcache\.(demandMisses|demandAccesses|writebacks)::total",
    r"system\.cpu\d\.icache\.demandMisses::total",
    r"system\.cpu\d\.(ipc|committedInsts|.*numInsts)",
    r"system\.mem_ctrl\.dram\.(avgMemAccLat|busUtil)",
    r"system\.mem_ctrl\.(readReqs|writeReqs)",
]
stats, hit = {}, {pat: 0 for pat in WANTED}
with open(os.path.join(out_dir, "stats.txt")) as f:
    for line in f:
        parts = line.split()
        if len(parts) < 2:
            continue
        for pat in WANTED:
            if re.fullmatch(pat, parts[0]):
                stats[parts[0]] = parts[1]
                hit[pat] += 1
for pat, n in hit.items():
    if n == 0:
        print(f"[!] Không có stat khớp '{pat}' - sửa theo tên trong stats.txt")
 
# Kiểm tra: số truy cập demand vào L2 ~ tổng miss L1 (I + D)
try:
    l1_miss = sum(float(stats[f"system.cpu{i}.{c}.demandMisses::total"])
                  for i in range(NUM_CORES) for c in ("icache", "dcache"))
    l2_acc = float(stats["system.l2cache.demandAccesses::total"])
    print(f"[*] Sanity: L2 demand accesses / Σ L1 misses = {l2_acc / l1_miss:.3f} (≈1)")
except (KeyError, ZeroDivisionError) as e:
    print(f"[!] Không kiểm tra được sanity: {e}")
 
with open(os.path.join(out_dir, "summary.json"), "w") as f:
    json.dump(dict(params=params, stats=stats), f, indent=2)
print(f"[*] Đã ghi {out_dir}/run_params.json và summary.json")
