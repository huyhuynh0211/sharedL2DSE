# 4 CVA6-like cores + private L1I/L1D + shared L2 (1 MiB, 16 way, --banks banks)
# mode: static | fixed | dynamic | drowsy
import argparse
import json
import math
import os
import shlex
import sys

import m5
from m5.objects import *

NUM_CORES = 4
CLOCK_HZ = 1_000_000_000
LINE = 64
MEM_SIZE = "2GiB"

CPU_WIDTH = 1
COMMIT_WIDTH = 2
DEC_TO_EXE_DELAY = 2

L1I = dict(size="16KiB", assoc=4)
L1D = dict(size="32KiB", assoc=8)
L1_LAT = dict(tag_latency=1, data_latency=1, response_latency=1)
L1_MSHRS = 1

XBAR = dict(width=16, frontend_latency=2, forward_latency=0, response_latency=2)

L2_SETS = 1024
L2_WAYS = 16
L2_LAT = dict(tag_latency=2, data_latency=6, response_latency=2)
L2_MSHRS_TOTAL = 32
SAMPLED_SETS = 32

parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="static", choices=["static", "fixed", "dynamic", "drowsy"])
parser.add_argument("--ways", type=int, default=16)
parser.add_argument("--banks", type=int, default=4, choices=[1, 2, 4, 8])
parser.add_argument("--repl", default="treeplru", choices=["treeplru", "lru"])
parser.add_argument("--warmup", type=int, default=10_000_000)
parser.add_argument("--cmd", action="append", required=True)
parser.add_argument("--interval", type=int, default=1_000_000)
parser.add_argument("--smax", type=float, default=0.01)
parser.add_argument("--tmem", type=float, default=49.0)
parser.add_argument("--margin", type=int, default=1)
parser.add_argument("--wmin", type=int, default=1)
parser.add_argument("--k", type=int, default=3)
parser.add_argument("--idle", type=int, default=1000)
parser.add_argument("--window", type=int, default=4000)
parser.add_argument("--wake-lat", type=int, default=1)
args = parser.parse_args()

if not 1 <= args.ways <= L2_WAYS:
    sys.exit("--ways must be in 1..16")
if args.mode == "static" and args.repl == "treeplru" and args.ways & (args.ways - 1):
    sys.exit("static Tree-PLRU needs a power-of-2 number of ways")

cmds = [shlex.split(c) for c in args.cmd]
cmds += [cmds[-1]] * (NUM_CORES - len(cmds))
for c in cmds:
    if not os.path.isfile(c[0]):
        sys.exit(f"file not found: {c[0]}")


def make_repl():
    return TreePLRURP() if args.repl == "treeplru" else LRURP()


system = System()
system.clk_domain = SrcClockDomain(clock=f"{CLOCK_HZ}Hz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange(MEM_SIZE)]
system.cache_line_size = LINE

system.membus = SystemXBar()
system.l2bus = L2XBar(**XBAR)

# bank bits = top bits of the set index -> same miss rate as a 1-bank L2
bank_sets = L2_SETS // args.banks
bank_ways = args.ways if args.mode == "static" else L2_WAYS
intlv_bits = int(math.log2(args.banks))
INTLV_HIGH_BIT = int(math.log2(LINE)) + int(math.log2(L2_SETS)) - 1

banks = []
for b in range(args.banks):
    if args.banks == 1:
        rng = AddrRange(0, size=MEM_SIZE)
    else:
        rng = AddrRange(0, size=MEM_SIZE, intlvHighBit=INTLV_HIGH_BIT,
                        intlvBits=intlv_bits, intlvMatch=b)
    extra = {}
    if args.mode in ("fixed", "dynamic"):
        extra["way_monitor"] = True
    if args.mode == "drowsy":
        extra["drowsy_window"] = args.window
        extra["drowsy_wake_latency"] = args.wake_lat
    banks.append(Cache(size=f"{bank_sets * bank_ways * LINE}B", assoc=bank_ways,
                       addr_ranges=[rng],
                       mshrs=L2_MSHRS_TOTAL // args.banks, tgts_per_mshr=16,
                       write_buffers=16, replacement_policy=make_repl(),
                       clusivity="mostly_incl", writeback_clean=False,
                       **extra, **L2_LAT))
system.l2bank = banks
for bank in system.l2bank:
    bank.cpu_side = system.l2bus.mem_side_ports
    bank.mem_side = system.membus.cpu_side_ports

system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(NUM_CORES)]
for cpu in system.cpu:
    cpu.decodeInputWidth = CPU_WIDTH
    cpu.executeInputWidth = CPU_WIDTH
    cpu.executeIssueLimit = CPU_WIDTH
    cpu.executeCommitLimit = COMMIT_WIDTH
    cpu.decodeToExecuteForwardDelay = DEC_TO_EXE_DELAY
    icache = Cache(mshrs=L1_MSHRS, tgts_per_mshr=8, write_buffers=8,
                   replacement_policy=LRURP(), is_read_only=True,
                   writeback_clean=False, **L1I, **L1_LAT)
    dcache = Cache(mshrs=L1_MSHRS, tgts_per_mshr=8, write_buffers=8,
                   replacement_policy=LRURP(), writeback_clean=False,
                   **L1D, **L1_LAT)
    cpu.addPrivateSplitL1Caches(icache, dcache)
    cpu.createInterruptController()
    cpu.connectAllPorts(system.l2bus.cpu_side_ports,
                        system.membus.cpu_side_ports,
                        system.membus.mem_side_ports)

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR4_2400_8x8(range=system.mem_ranges[0])
system.mem_ctrl.port = system.membus.mem_side_ports
system.system_port = system.membus.cpu_side_ports

system.workload = SEWorkload.init_compatible(cmds[0][0])
for i, cpu in enumerate(system.cpu):
    cpu.workload = Process(pid=100 + i, cmd=cmds[i], env=["MALLOC_MMAP_MAX_=0"])
    cpu.createThreads()

root = Root(full_system=False, system=system)
m5.instantiate()

banks = list(system.l2bank)
TICKS_PER_CYCLE = m5.ticks.fromSeconds(1.0 / CLOCK_HZ)
SCALE = L2_SETS // SAMPLED_SETS


def set_ways(w):
    for bank in banks:
        bank.setActiveWays(w)


def choose_target(hits, acc):
    if acc * SCALE < args.idle:
        return args.wmin
    allowed = args.smax * args.interval * NUM_CORES / args.tmem   # extra misses allowed per interval
    h16 = sum(hits)
    if h16 * SCALE <= allowed:
        return args.wmin
    for w in range(args.wmin, L2_WAYS + 1):
        if (h16 - sum(hits[:w])) * SCALE <= allowed:
            return min(L2_WAYS, w + args.margin)
    return L2_WAYS


cur = L2_WAYS
if args.mode == "fixed":
    cur = args.ways
    set_ways(cur)

if args.warmup > 0:
    ev = m5.simulate(args.warmup * TICKS_PER_CYCLE)
    if ev.getCause() != "simulate() limit reached":
        sys.exit("program exited during warmup")
    m5.stats.reset()
    if args.mode == "drowsy":
        for bank in banks:
            bank.resetDrowsyCounters()

t0 = m5.curTick()
if args.mode == "dynamic":
    log = open(os.path.join(m5.options.outdir, "dyn_log.csv"), "w")
    log.write("tick,ways,sampled_acc," + ",".join(f"h{p}" for p in range(L2_WAYS)) + "\n")

    def read_atd():
        h = [sum(bank.getWayHit(p) for bank in banks) for p in range(L2_WAYS)]
        return h, sum(bank.getSampledAccesses() for bank in banks)

    # ATD counters only grow: use per-interval deltas, smoothed as floats
    prev_h, prev_a = read_atd()
    ema_h, ema_a = None, None
    counter = 0
    while True:
        ev = m5.simulate(args.interval * TICKS_PER_CYCLE)
        if ev.getCause() != "simulate() limit reached":
            break
        now_h, now_a = read_atd()
        d_h = [n - q for n, q in zip(now_h, prev_h)]
        d_a = now_a - prev_a
        prev_h, prev_a = now_h, now_a
        if ema_h is None:
            ema_h, ema_a = [float(x) for x in d_h], float(d_a)
        else:
            ema_h = [0.5 * e + 0.5 * x for e, x in zip(ema_h, d_h)]
            ema_a = 0.5 * ema_a + 0.5 * d_a
        target = choose_target(ema_h, ema_a)
        if target > cur:                     # grow: apply now
            cur = target
            set_ways(cur)
            counter = 0
        elif target < cur:                   # shrink: wait k intervals
            counter += 1
            if counter >= args.k:
                cur = target
                set_ways(cur)
                counter = 0
        else:
            counter = 0
        log.write(f"{m5.curTick()},{cur},{d_a}," + ",".join(str(x) for x in d_h) + "\n")
    log.close()
else:
    ev = m5.simulate()
t1 = m5.curTick()

meta = dict(vars(args))
meta.update(ticks_measured=t1 - t0, cause=ev.getCause(),
            bank_sets=bank_sets, bank_ways=bank_ways, intlv_high_bit=INTLV_HIGH_BIT,
            cmds=[" ".join(c) for c in cmds])
if args.mode in ("fixed", "dynamic"):
    meta["way_off_writebacks"] = sum(bank.getWayOffWritebacks() for bank in banks)
if args.mode == "drowsy":
    meta["num_blocks"] = sum(bank.getDrowsyNumBlocks() for bank in banks)
    meta["drowsy_hit_wakes"] = sum(bank.getDrowsyHitWakes() for bank in banks)
    meta["drowsy_fill_wakes"] = sum(bank.getDrowsyFillWakes() for bank in banks)
    meta["drowsy_awake_ticks"] = sum(bank.getDrowsyAwakeTicks() for bank in banks)
    meta["awake_fraction"] = meta["drowsy_awake_ticks"] / (meta["num_blocks"] * meta["ticks_measured"])

with open(os.path.join(m5.options.outdir, "run_meta.json"), "w") as f:
    json.dump(meta, f, indent=2)
print(f"[l2_run] mode {args.mode}, {args.banks} bank, cause: {ev.getCause()}")
