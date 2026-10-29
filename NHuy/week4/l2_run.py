# 4 CVA6-like cores + private L1I/L1D + shared L2 (1 MiB, 16 way, 4 bank)
# mode: static (W-way L2) | fixed (16 way, W on) | dynamic (ATD + controller) | drowsy
import argparse
import json
import math
import os
import shlex
import sys

import m5
from m5.objects import *
from m5.params import NULL

NUM_CORES = 4
LINE = 64              # gem5 classic: one line size for every cache (RTL L1 line = 16 B)
MEM_SIZE = "2GiB"

# part 1: arguments
parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="static", choices=["static", "fixed", "dynamic", "drowsy"])
parser.add_argument("--ways", type=int, default=16)
parser.add_argument("--banks", type=int, default=4, choices=[1, 2, 4, 8])
parser.add_argument("--repl", default="treeplru", choices=["treeplru", "lru"])
parser.add_argument("--clock-mhz", type=int, default=100)
parser.add_argument("--mem-ns", type=float, default=25.0)     # L2 -> DRAM latency, assumed
parser.add_argument("--l1-mshrs", type=int, default=8)
parser.add_argument("--warmup", type=int, default=0)
parser.add_argument("--cmd", action="append", required=True)
parser.add_argument("--interval", type=int, default=1_000_000)
parser.add_argument("--smax", type=float, default=0.01)
parser.add_argument("--tmem", type=float, default=None)       # from tmem_calc.py
parser.add_argument("--margin", type=int, default=1)
parser.add_argument("--wmin", type=int, default=1)
parser.add_argument("--k", type=int, default=3)
parser.add_argument("--idle", type=int, default=0)
parser.add_argument("--window", type=int, default=4000)
parser.add_argument("--wake-lat", type=int, default=1)
args = parser.parse_args()

if not 1 <= args.ways <= 16:
    sys.exit("--ways must be in 1..16")
if args.mode == "static" and args.repl == "treeplru" and args.ways & (args.ways - 1):
    sys.exit("static Tree-PLRU needs a power-of-2 number of ways (use --mode fixed)")
if args.mode == "dynamic" and args.tmem is None:
    sys.exit("dynamic mode needs --tmem (run tmem_calc.py first)")

cmds = [shlex.split(c) for c in args.cmd]
cmds += [cmds[-1]] * (NUM_CORES - len(cmds))
for c in cmds:
    if not os.path.isfile(c[0]):
        sys.exit(f"file not found: {c[0]}")

MHZ = args.clock_mhz


def cyc(ns, lo=1):
    return max(lo, int(ns * MHZ / 1000 + 0.5))


# part 2: latencies (ns -> cycles at the chosen clock)
L1_LAT = dict(tag_latency=1, data_latency=1, response_latency=1)
L2_LAT = dict(tag_latency=cyc(2), data_latency=cyc(6), response_latency=cyc(2))
NOC = dict(width=8,                                                  # CVA6 AXI data = 64 bit
           frontend_latency=cyc(2, 0), forward_latency=0, response_latency=cyc(2, 0))
MEMBUS = dict(width=16,
              frontend_latency=cyc(0.4 * args.mem_ns, 0),
              forward_latency=cyc(0.2 * args.mem_ns, 0),
              response_latency=cyc(0.4 * args.mem_ns, 0))

L2_SETS = 1024
L2_WAYS = 16
L2_MSHRS_TOTAL = 32


# part 3: CVA6 core (cv64a6_imafdc_sv39)
class CVA6IntFU(MinorFU):
    opClasses = minorMakeOpClassSet(["IntAlu"])
    timings = [MinorFUTiming(description="Int", srcRegsRelativeLats=[0])]
    opLat = 1


class CVA6MulFU(MinorFU):
    opClasses = minorMakeOpClassSet(["IntMult"])
    timings = [MinorFUTiming(description="Mul", srcRegsRelativeLats=[0])]
    opLat = 2


class CVA6DivFU(MinorFU):            # serial divider, 32 cycles assumed
    opClasses = minorMakeOpClassSet(["IntDiv"])
    opLat = 32
    issueLat = 32


class CVA6FUPool(MinorFUPool):
    funcUnits = [CVA6IntFU(), CVA6MulFU(), CVA6DivFU(), MinorDefaultFloatSimdFU(),
                 MinorDefaultPredFU(), MinorDefaultMemFU(), MinorDefaultMiscFU()]


def cva6_bp():
    return BranchPredictor(conditionalBranchPred=LocalBP(localPredictorSize=256, localCtrBits=2),
                           btb=SimpleBTB(numEntries=32, associativity=1),
                           ras=ReturnAddrStack(numEntries=2),
                           indirectBranchPred=NULL)


def make_repl():
    return TreePLRURP() if args.repl == "treeplru" else LRURP()


# part 4: system, L2 banks, cores, DRAM
system = System()
system.clk_domain = SrcClockDomain(clock=f"{MHZ}MHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange(MEM_SIZE)]
system.cache_line_size = LINE
system.work_begin_exit_count = NUM_CORES      # ROI starts when all 4 programs called work_begin

system.membus = SystemXBar(**MEMBUS)
system.l2bus = L2XBar(**NOC)

# bank bits = top bits of the set index (bits 14-15): same sets as a 1-bank L2
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
    cpu.decodeInputWidth = 1
    cpu.executeInputWidth = 1
    cpu.executeIssueLimit = 1
    cpu.executeCommitLimit = 2
    cpu.decodeToExecuteForwardDelay = 2
    cpu.executeMaxAccessesInMemory = 2
    cpu.executeLSQStoreBufferSize = 4
    cpu.executeFuncUnits = CVA6FUPool()
    cpu.branchPred = cva6_bp()
    icache = Cache(size="16KiB", assoc=4, mshrs=args.l1_mshrs, tgts_per_mshr=8,
                   write_buffers=8, replacement_policy=LFSRRP(), is_read_only=True,
                   writeback_clean=False, **L1_LAT)
    dcache = Cache(size="32KiB", assoc=8, mshrs=args.l1_mshrs, tgts_per_mshr=8,
                   write_buffers=8, replacement_policy=LFSRRP(),
                   writeback_clean=False, **L1_LAT)
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
TICKS_PER_CYCLE = m5.ticks.fromSeconds(1.0 / (MHZ * 1e6))


def set_ways(w):
    for bank in banks:
        bank.setActiveWays(w)


cur = L2_WAYS
if args.mode == "fixed":
    cur = args.ways
    set_ways(cur)

# part 5: run init, then start the ROI
ev = m5.simulate()
if ev.getCause() != "work started count reach":
    sys.exit(f"ROI not reached ({ev.getCause()}): workloads must call m5 work_begin")
if args.warmup > 0:
    ev = m5.simulate(args.warmup * TICKS_PER_CYCLE)
    if ev.getCause() != "simulate() limit reached":
        sys.exit("program exited during warmup")
m5.stats.reset()
if args.mode == "drowsy":
    for bank in banks:
        bank.resetDrowsyCounters()

# part 6: dynamic controller (or plain run for the other modes)
t0 = m5.curTick()
ways_turned_on = 0
if args.mode == "dynamic":
    sampled_sets = sum(bank.getSampledSets() for bank in banks)
    SCALE = L2_SETS / sampled_sets
    allowed = args.smax * args.interval * NUM_CORES / args.tmem   # extra L2 misses allowed per interval

    def choose_target(hits, acc):
        if acc * SCALE < args.idle:
            return args.wmin
        h16 = sum(hits)
        if h16 * SCALE <= allowed:
            return args.wmin
        for w in range(args.wmin, L2_WAYS + 1):
            if (h16 - sum(hits[:w])) * SCALE <= allowed:
                return min(L2_WAYS, w + args.margin)
        return L2_WAYS

    def read_atd():
        h = [sum(bank.getWayHit(p) for bank in banks) for p in range(L2_WAYS)]
        return h, sum(bank.getSampledAccesses() for bank in banks)

    log = open(os.path.join(m5.options.outdir, "dyn_log.csv"), "w")
    log.write("tick,ways,sampled_acc," + ",".join(f"h{p}" for p in range(L2_WAYS)) + "\n")
    # ATD counters only grow: use per-interval deltas, smoothed (EMA 0.5)
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
            ways_turned_on += target - cur
            cur = target
            set_ways(cur)
            counter = 0
        elif target < cur:                   # shrink: only after k intervals in a row
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

# part 7: write run_meta.json
meta = dict(vars(args))
meta.update(ticks_measured=t1 - t0, cycles_measured=(t1 - t0) // TICKS_PER_CYCLE,
            cause=ev.getCause(), bank_sets=bank_sets, bank_ways=bank_ways,
            intlv_high_bit=INTLV_HIGH_BIT, cmds=[" ".join(c) for c in cmds],
            l2_lat=L2_LAT, noc=NOC, membus=MEMBUS)
if args.mode in ("fixed", "dynamic"):
    meta["way_off_writebacks"] = sum(bank.getWayOffWritebacks() for bank in banks)
if args.mode == "dynamic":
    meta["ways_turned_on"] = ways_turned_on
    meta["sampled_sets"] = sampled_sets
if args.mode == "drowsy":
    meta["num_blocks"] = sum(bank.getDrowsyNumBlocks() for bank in banks)
    meta["drowsy_hit_wakes"] = sum(bank.getDrowsyHitWakes() for bank in banks)
    meta["drowsy_fill_wakes"] = sum(bank.getDrowsyFillWakes() for bank in banks)
    meta["drowsy_awake_ticks"] = sum(bank.getDrowsyAwakeTicks() for bank in banks)
    meta["awake_fraction"] = meta["drowsy_awake_ticks"] / (meta["num_blocks"] * meta["ticks_measured"])

with open(os.path.join(m5.options.outdir, "run_meta.json"), "w") as f:
    json.dump(meta, f, indent=2)
print(f"[l2_run] mode {args.mode}, {MHZ} MHz, cause: {ev.getCause()}")
