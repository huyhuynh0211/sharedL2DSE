import argparse
import json
import os
import shlex
import sys

import m5
import m5.objects as objs
from m5.objects import *
from m5.util.convert import toMemorySize

NUM_CORES = 4
CLOCK_HZ = 1_000_000_000
LINE = 64
L2_SETS_PROD = 1024

CPU_WIDTH = 1
L1I = dict(size="16KiB", assoc=4)
L1D = dict(size="32KiB", assoc=8)
L1_LAT = dict(tag_latency=1, data_latency=1, response_latency=1)
L1_MSHRS = 1
XBAR = dict(width=16, frontend_latency=2, forward_latency=0, response_latency=2)
L2_LAT = dict(tag_latency=2, data_latency=6, response_latency=2)
L2_MSHRS = 32

REPL_CLASSES = {
    "LRU": "LRURP",
    "Random": "RandomRP",
    "LFSR": "LFSRRP",
    "NMRU": "NMRURP",
    "FIFO": "FIFORP",
    "TreePLRU": "TreePLRURP",
    "DRRIP": "DRRIPRP",
}

parser = argparse.ArgumentParser()
parser.add_argument("--cores", type=int, default=NUM_CORES)
parser.add_argument("--repl", default="LRU", choices=list(REPL_CLASSES))
parser.add_argument("--incl", default="nonincl", choices=["nonincl", "excl"])
parser.add_argument("--ways", type=int, default=16)
parser.add_argument("--size", default="1024KiB")
parser.add_argument("--warmup", type=int, default=10_000_000)
parser.add_argument("--cmd", action="append", required=True)
args = parser.parse_args()
NUM_CORES = args.cores

if len(args.cmd) > NUM_CORES:
    sys.exit("err")
cmds = [shlex.split(c) for c in args.cmd]
cmds += [cmds[-1]] * (NUM_CORES - len(cmds))
for c in cmds:
    if not os.path.isfile(c[0]):
        sys.exit("err")

ways = args.ways
size = toMemorySize(args.size) if args.size else L2_SETS_PROD * LINE * ways
sets = size // (LINE * ways)
if sets * LINE * ways != size or sets & (sets - 1):
    sys.exit("err")

repl_name = args.repl
repl_cls = getattr(objs, REPL_CLASSES[repl_name], None)
if repl_name == "TreePLRU" and ways & (ways - 1):
    sys.exit("err")

if repl_name == "DRRIP":
    repl_obj = repl_cls(constituency_size=sets * ways // 32, team_size=ways)
else:
    repl_obj = repl_cls()

if args.incl == "nonincl":
    l2_clusivity, l1_wb_clean = "mostly_incl", False
else:
    l2_clusivity, l1_wb_clean = "mostly_excl", True

system = System()
system.clk_domain = SrcClockDomain(clock=f"{CLOCK_HZ}Hz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("2GiB")]
system.cache_line_size = LINE

system.membus = SystemXBar()
system.l2bus = L2XBar(**XBAR)

system.l2cache = Cache(size=f"{size}B", assoc=ways, mshrs=L2_MSHRS, tgts_per_mshr=16,
                       write_buffers=16, replacement_policy=repl_obj,
                       clusivity=l2_clusivity, writeback_clean=False, **L2_LAT)
system.l2cache.cpu_side = system.l2bus.mem_side_ports
system.l2cache.mem_side = system.membus.cpu_side_ports

system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(NUM_CORES)]
for cpu in system.cpu:
    cpu.decodeInputWidth = CPU_WIDTH
    cpu.executeInputWidth = CPU_WIDTH
    cpu.executeIssueLimit = CPU_WIDTH
    cpu.executeCommitLimit = CPU_WIDTH
    icache = Cache(mshrs=L1_MSHRS, tgts_per_mshr=8, write_buffers=4,
                   replacement_policy=LRURP(), is_read_only=True,
                   writeback_clean=l1_wb_clean, **L1I, **L1_LAT)
    dcache = Cache(mshrs=L1_MSHRS, tgts_per_mshr=8, write_buffers=8,
                   replacement_policy=LRURP(), writeback_clean=l1_wb_clean,
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

warmup = args.warmup
valid = True
if warmup > 0:
    ev = m5.simulate(warmup * m5.ticks.fromSeconds(1.0 / CLOCK_HZ))
    if ev.getCause() != "simulate() limit reached":
        valid = False
    else:
        m5.stats.reset()
if valid:
    ev = m5.simulate()

with open(os.path.join(m5.options.outdir, "run_meta.json"), "w") as f:
    json.dump({"valid": valid, "repl": repl_name, "incl": args.incl,
               "size": size, "ways": ways, "sets": sets, "warmup": warmup,
               "cmds": [" ".join(c) for c in cmds]}, f, indent=2)
