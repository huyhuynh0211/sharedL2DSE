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

class L1Cache(Cache):
    tag_latency = 2
    data_latency = 2
    response_latency = 2
    mshrs = 4
    tgts_per_mshr = 20

class L2Cache(Cache):
    tag_latency = 10
    data_latency = 10
    response_latency = 10
    mshrs = 32
    tgts_per_mshr = 12

#System
system = System()
system.clk_domain = SrcClockDomain(clock="1GHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("512MiB")]
system.cache_line_size = 64

#CPUs
system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(NUM_CPUS)]

#Private L1s, all connected to the shared L2 bus
system.l2bus = L2XBar()
for cpu in system.cpu:
    cpu.icache = L1Cache(size="16KiB", assoc=4)
    cpu.dcache = L1Cache(size="32KiB", assoc=8)
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

#Start sim
root = Root(full_system=False, system=system)
m5.instantiate()

print("Beginning simulation")
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")