import m5
from m5.objects import *
import argparse

REPL = {
    "LRU":      LRURP,
    "FIFO":     FIFORP,
    "Random":   RandomRP,
    "TreePLRU": TreePLRURP,
}

parser = argparse.ArgumentParser()
parser.add_argument("--l1d_size", default="16KiB")
parser.add_argument("--l1d_assoc", type=int, default=4)
parser.add_argument("--l1d_repl", choices=REPL.keys(), default="LRU")
args = parser.parse_args()

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
    mshrs = 20
    tgts_per_mshr = 12

#System
system = System()
system.clk_domain = SrcClockDomain(clock="1GHz", voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.mem_ranges = [AddrRange("512MiB")]
system.cache_line_size = 64

#CPU
system.cpu = RiscvMinorCPU()

#L1 Caches
system.cpu.icache = L1Cache(size="16KiB", assoc=4)
system.cpu.dcache = L1Cache(size=args.l1d_size, assoc=args.l1d_assoc, replacement_policy=REPL[args.l1d_repl]())
system.cpu.icache.cpu_side = system.cpu.icache_port
system.cpu.dcache.cpu_side = system.cpu.dcache_port

#L2 Caches and Bus
system.l2bus = L2XBar()
system.cpu.icache.mem_side = system.l2bus.cpu_side_ports
system.cpu.dcache.mem_side = system.l2bus.cpu_side_ports

system.l2cache = L2Cache(size="256KiB", assoc=16)
system.l2cache.cpu_side = system.l2bus.mem_side_ports

#DRAM and Bus
system.membus = SystemXBar()
system.l2cache.mem_side = system.membus.cpu_side_ports

system.cpu.createInterruptController()
system.system_port = system.membus.cpu_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

#Running workload
binary = "dse/test/workload"
system.workload = SEWorkload.init_compatible(binary)

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

#Start sim
root = Root(full_system=False, system=system)
m5.instantiate()

print("Beginning simulation")
exit_event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")