# cva6_cluster_baseline.py
# 4-Core RISC-V MinorCPU
# Private L1I/L1D, Shared L2, L2XBar cluster interconnect, DDR4 memory
# gem5 tested environment: gem5 25.1.0.1 (RISCV build)

import argparse
import os

import m5
from m5.objects import *

# Command-line arguments
parser = argparse.ArgumentParser(description="4-core RISC-V Shared-L2 baseline configuration")
parser.add_argument("--binary", type=str, default=None, help="Path to RISC-V SE workload binary")
parser.add_argument("--l2_size", type=str, default="1MiB", help="Shared L2 size (default: 1MiB)")
parser.add_argument("--l2_assoc", type=int, default=16, help="Shared L2 associativity / number of ways (default: 16)")
parser.add_argument("--footprint", type=str, default="2097152", help="Reserved for future workload interface; default = 2MiB")
parser.add_argument("--stride", type=str, default="64", help="Reserved for future workload interface; default = 64B")
args = parser.parse_args()

# Cache definitions
class L1Cache(Cache):
    # Project baseline: 32KiB, 4-way, nominal 1-cycle latency
    assoc = 4
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    # L1 MSHRs are local to each private L1 cache
    mshrs = 8
    tgts_per_mshr = 20

class L1ICache(L1Cache):
    size = "32KiB"
    def connectCPU(self, cpu):
        self.cpu_side = cpu.icache_port
    def connectBus(self, bus):
        self.mem_side = bus.cpu_side_ports

class L1DCache(L1Cache):
    size = "32KiB"
    def connectCPU(self, cpu):
        self.cpu_side = cpu.dcache_port
    def connectBus(self, bus):
        self.mem_side = bus.cpu_side_ports

class SharedL2Cache(Cache):
    # Shared L2 cache for all 4 cores. 
    # Note: mshrs = 32 applies to THIS L2 cache only, not a system-wide pool.
    tag_latency = 14
    data_latency = 14
    response_latency = 1
    mshrs = 32
    tgts_per_mshr = 20

    def connectCPUSideBus(self, bus):
        self.cpu_side = bus.mem_side_ports
    def connectMemSideBus(self, bus):
        self.mem_side = bus.cpu_side_ports

# Cluster interconnect
class ClusterNoC(L2XBar):
    # Approximation of the cluster interconnect using gem5 L2XBar.
    # Target: 128-bit datapath = 16 bytes, approx 2-cycle delay.
    width = 16
    frontend_latency = 2
    forward_latency = 2
    response_latency = 2

# System initialization
system = System()

# Clock and voltage
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = "1GHz"
system.clk_domain.voltage_domain = VoltageDomain()

system.mem_mode = "timing"
system.mem_ranges = [AddrRange("512MiB")]
system.cache_line_size = 64

# Instantiate 4 RISC-V MinorCPU cores
system.cpu = [RiscvMinorCPU(cpu_id=i) for i in range(4)]
system.cluster_noc = ClusterNoC()

# Setup Private L1 caches and connect to cores/interconnect
for cpu in system.cpu:
    cpu.icache = L1ICache()
    cpu.dcache = L1DCache()

    cpu.icache.connectCPU(cpu)
    cpu.dcache.connectCPU(cpu)

    cpu.icache.connectBus(system.cluster_noc)
    cpu.dcache.connectBus(system.cluster_noc)
    cpu.createInterruptController()

# Setup Shared L2
system.l2 = SharedL2Cache()
system.l2.size = args.l2_size
system.l2.assoc = args.l2_assoc
system.l2.connectCPUSideBus(system.cluster_noc)

# Setup System memory bus
system.membus = SystemXBar()
system.l2.connectMemSideBus(system.membus)

# Setup Memory controller & DDR4
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR4_2400_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports
system.system_port = system.membus.cpu_side_ports

# SE Workload setup
if args.binary is not None:
    if not os.path.isfile(args.binary):
        raise FileNotFoundError(f"Workload binary not found: {args.binary}")

    system.workload = SEWorkload.init_compatible(args.binary)

    for i, cpu in enumerate(system.cpu):
        process = Process(pid=100 + i)
        
        # Current safe baseline: only pass the executable itself.
        # Can be expanded later with footprint/stride args if needed.
        process.cmd = [args.binary]
        cpu.workload = process
        cpu.createThreads()

root = Root(full_system=False, system=system)

# Print configuration summary
print("\n--- 4-Core RISC-V Shared-L2 Baseline ---")
print(f"CPU model          : RiscvMinorCPU")
print(f"Number of cores    : {len(system.cpu)}\n")

print("Private L1:")
print(f"  L1I / L1D size   : 32KiB")
print(f"  associativity    : 4-way")
print(f"  MSHRs per L1     : 8\n")

print("Shared L2:")
print(f"  size             : {args.l2_size}")
print(f"  associativity    : {args.l2_assoc}-way")
print(f"  MSHRs            : 32")
print(f"  cache line       : 64B\n")

print("Interconnect:")
print(f"  model            : L2XBar")
print(f"  width            : 16B / 128-bit\n")

print("Memory:")
print(f"  capacity         : 512MiB")
print(f"  model            : DDR4_2400_8x8\n")

print(f"Clock              : 1GHz\n")

if args.binary is None:
    print("Workload           : NONE")
    print("NOTE: Hardware topology has been configured.")
    print("No SE workload was provided, so simulation will not be started.")
    print("Use --binary when a RISC-V workload is available.\n")
    print("[INFO] Waiting for a RISC-V SE workload before simulation.")
else:
    print(f"Workload           : {args.binary}\n")
    print("[INFO] Instantiating gem5 system...")
    m5.instantiate()
    
    print("[INFO] Starting simulation...")
    exit_event = m5.simulate()
    
    print("\n--- Simulation finished ---")
    print(f"Tick   : {m5.curTick()}")
    print(f"Cause  : {exit_event.getCause()}")

