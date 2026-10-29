import m5
from m5.objects import *
import argparse
from pathlib import Path

REPL = {
    "LRU":      LRURP,
    "FIFO":     FIFORP,
    "Random":   RandomRP,
    "TreePLRU": TreePLRURP,
}

NUM_CPUS = 4
CLOCK = "100MHz"
NS_PER_CYCLE = 10            # 100 MHz -> 10 ns per cycle
WARMUP_CYCLES = 2_000_000
MEASURE_CYCLES = 10_000_000

parser = argparse.ArgumentParser()
parser.add_argument("--l2_size", default="1MiB")
parser.add_argument("--l2_assoc", type=int, default=16)
parser.add_argument("--l2_repl", choices=REPL.keys(), default="LRU")
parser.add_argument("--bin_dir", default=".",
                    help="folder that holds the workload binaries")
parser.add_argument("--workload", nargs=NUM_CPUS, required=True, metavar="BINARY",
                    help="one binary per core, e.g. --workload loop loop empty empty")
args = parser.parse_args()

binaries = [str(Path(args.bin_dir) / (name + ".riscv")) for name in args.workload]

# L1 caches (CVA6 baseline; MSHRs corrected to 4)
class L1Cache(Cache):
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 4
    tgts_per_mshr = 8
    write_buffers = 8
    writeback_clean = False

# Shared L2 (CVA6 baseline, latencies for 100 MHz)
class L2Cache(Cache):
    tag_latency = 2
    data_latency = 2
    response_latency = 1
    sequential_access = False
    clusivity = "mostly_incl"
    writeback_clean = False
    mshrs = 32
    tgts_per_mshr = 12
    write_buffers = 16

#System
system = System()
system.clk_domain = SrcClockDomain(clock=CLOCK, voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("512MiB")]
system.cache_line_size = 64

#CPUs, tuned toward CVA6
system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(NUM_CPUS)]
for cpu in system.cpu:
    cpu.decodeInputWidth = 1
    cpu.executeInputWidth = 1
    cpu.executeIssueLimit = 1
    cpu.executeCommitLimit = 2
    cpu.decodeToExecuteForwardDelay = 2

#Crossbar between the L1s and the L2
system.l2bus = L2XBar(width=16, frontend_latency=1,
                      forward_latency=1, response_latency=1)

#Private L1s
for cpu in system.cpu:
    cpu.icache = L1Cache(size="16KiB", assoc=4, is_read_only=True,
                         replacement_policy=RandomRP())
    cpu.dcache = L1Cache(size="32KiB", assoc=8,
                         replacement_policy=RandomRP())
    cpu.icache.cpu_side = cpu.icache_port
    cpu.dcache.cpu_side = cpu.dcache_port
    cpu.icache.mem_side = system.l2bus.cpu_side_ports
    cpu.dcache.mem_side = system.l2bus.cpu_side_ports
    cpu.createInterruptController()

#Shared L2
system.l2cache = L2Cache(size=args.l2_size, assoc=args.l2_assoc,
                         replacement_policy=REPL[args.l2_repl]())
system.l2cache.cpu_side = system.l2bus.mem_side_ports

#DRAM and Bus
system.membus = SystemXBar()
system.l2cache.mem_side = system.membus.cpu_side_ports
system.system_port = system.membus.cpu_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR4_2400_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

#Workloads, one process per core
system.workload = SEWorkload.init_compatible(binaries[0])
for i, cpu in enumerate(system.cpu):
    process = Process(pid=100 + i)
    process.cmd = [binaries[i]]
    cpu.workload = process
    cpu.createThreads()

#Start sim: warm up, reset stats, then measure a fixed window
root = Root(full_system=False, system=system)
m5.instantiate()

def ticks(cycles):
    return cycles * NS_PER_CYCLE * 1000     # 1 tick = 1 ps

print("Warming up")
exit_event = m5.simulate(ticks(WARMUP_CYCLES))
if exit_event.getCause() != "simulate() limit reached":
    raise SystemExit(f"stopped during warm-up: {exit_event.getCause()}")
m5.stats.reset()

print("Measuring")
exit_event = m5.simulate(ticks(MEASURE_CYCLES))
m5.stats.dump()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")