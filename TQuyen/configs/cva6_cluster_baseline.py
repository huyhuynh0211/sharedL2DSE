# ==============================================================================
# cva6_cluster_baseline.py
#
# 4-Core RISC-V MinorCPU
# Private L1I/L1D
# Shared L2
# L2XBar cluster interconnect
# DDR4 memory
#
# gem5 tested environment:
#   gem5 25.1.0.1
#   RISCV build
#
# ==============================================================================

import argparse
import os

import m5
from m5.objects import *


# ==============================================================================
# STEP 1: COMMAND-LINE ARGUMENTS
# ==============================================================================

parser = argparse.ArgumentParser(
    description="4-core RISC-V Shared-L2 baseline configuration"
)

parser.add_argument(
    "--binary",
    type=str,
    default=None,
    help="Path to RISC-V SE workload binary"
)

parser.add_argument(
    "--l2_size",
    type=str,
    default="1MiB",
    help="Shared L2 size (default: 1MiB)"
)

parser.add_argument(
    "--l2_assoc",
    type=int,
    default=16,
    help="Shared L2 associativity / number of ways (default: 16)"
)

parser.add_argument(
    "--footprint",
    type=str,
    default="2097152",
    help="Reserved for future workload interface; default = 2MiB"
)

parser.add_argument(
    "--stride",
    type=str,
    default="64",
    help="Reserved for future workload interface; default = 64B"
)

args = parser.parse_args()


# ==============================================================================
# STEP 2: CACHE DEFINITIONS
# ==============================================================================

class L1Cache(Cache):
    """
    Common parameters for private L1 caches.

    Project baseline:
      - 32KiB
      - 4-way
      - nominal 1-cycle cache latency
    """

    assoc = 4

    tag_latency = 1
    data_latency = 1
    response_latency = 1

    # L1 MSHRs are local to each private L1 cache.
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
    """
    Shared L2 cache for all 4 cores.

    Important:
      mshrs = 32 applies to THIS L2 cache only.
      It is not a system-wide MSHR pool.
    """

    # These are baseline timing parameters.
    # We will validate actual observed hit timing separately.
    tag_latency = 14
    data_latency = 14
    response_latency = 1

    mshrs = 32
    tgts_per_mshr = 20

    def connectCPUSideBus(self, bus):
        self.cpu_side = bus.mem_side_ports

    def connectMemSideBus(self, bus):
        self.mem_side = bus.cpu_side_ports


# ==============================================================================
# STEP 3: CLUSTER INTERCONNECT
# ==============================================================================

class ClusterNoC(L2XBar):
    """
    Approximation of the cluster interconnect using gem5 L2XBar.

    Target:
      - 128-bit datapath = 16 bytes
      - approximately 2-cycle forwarding/response delay
    """

    width = 16

    frontend_latency = 2
    forward_latency = 2
    response_latency = 2


# ==============================================================================
# STEP 4: SYSTEM INITIALIZATION
# ==============================================================================

system = System()

# ----------------------------------------------------------------------
# Clock / voltage
# ----------------------------------------------------------------------

system.clk_domain = SrcClockDomain()
system.clk_domain.clock = "1GHz"
system.clk_domain.voltage_domain = VoltageDomain()


# ----------------------------------------------------------------------
# Timing simulation
# ----------------------------------------------------------------------

system.mem_mode = "timing"


# ----------------------------------------------------------------------
# Physical address space
# ----------------------------------------------------------------------

system.mem_ranges = [
    AddrRange("512MiB")
]


# ----------------------------------------------------------------------
# Cache line
# ----------------------------------------------------------------------

system.cache_line_size = 64


# ==============================================================================
# STEP 5: 4 RISC-V MINORCPU CORES
# ==============================================================================

system.cpu = [
    RiscvMinorCPU(cpu_id=i)
    for i in range(4)
]


# ==============================================================================
# STEP 6: CLUSTER INTERCONNECT
# ==============================================================================

system.cluster_noc = ClusterNoC()


# ==============================================================================
# STEP 7: PRIVATE L1 CACHES
# ==============================================================================

for cpu in system.cpu:

    # Create private instruction/data caches
    cpu.icache = L1ICache()
    cpu.dcache = L1DCache()

    # CPU -> private L1
    cpu.icache.connectCPU(cpu)
    cpu.dcache.connectCPU(cpu)

    # Private L1 -> shared cluster interconnect
    cpu.icache.connectBus(system.cluster_noc)
    cpu.dcache.connectBus(system.cluster_noc)

    # Required CPU-side interrupt-controller objects
    cpu.createInterruptController()


# ==============================================================================
# STEP 8: SHARED L2
# ==============================================================================

system.l2 = SharedL2Cache()

system.l2.size = args.l2_size
system.l2.assoc = args.l2_assoc

# Cluster NoC -> Shared L2
system.l2.connectCPUSideBus(system.cluster_noc)


# ==============================================================================
# STEP 9: SYSTEM MEMORY BUS
# ==============================================================================

system.membus = SystemXBar()

# Shared L2 -> system memory bus
system.l2.connectMemSideBus(system.membus)


# ==============================================================================
# STEP 10: MEMORY CONTROLLER + DDR4
# ==============================================================================

system.mem_ctrl = MemCtrl()

system.mem_ctrl.dram = DDR4_2400_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]

# MemCtrl -> memory side of system bus
system.mem_ctrl.port = system.membus.mem_side_ports


# gem5 system port used for functional accesses
system.system_port = system.membus.cpu_side_ports


# ==============================================================================
# STEP 11: SE WORKLOAD
# ==============================================================================

if args.binary is not None:

    if not os.path.isfile(args.binary):
        raise FileNotFoundError(
            f"Workload binary not found: {args.binary}"
        )

    # Automatically select a compatible SE workload object
    system.workload = SEWorkload.init_compatible(args.binary)

    for i, cpu in enumerate(system.cpu):

        process = Process(
            pid=100 + i
        )

        # Current safe baseline:
        # only pass the executable itself.
        #
        # Once dsp_traffic interface is confirmed, this may become:
        #
        # process.cmd = [
        #     args.binary,
        #     args.footprint,
        #     args.stride,
        # ]
        #
        process.cmd = [
            args.binary
        ]

        cpu.workload = process

        # Create thread context for this core
        cpu.createThreads()


# ==============================================================================
# STEP 12: ROOT
# ==============================================================================

root = Root(
    full_system=False,
    system=system
)


# ==============================================================================
# STEP 13: CONFIGURATION SUMMARY
# ==============================================================================

print("")
print("============================================================")
print("  4-Core RISC-V Shared-L2 Baseline")
print("============================================================")

print(f"CPU model          : RiscvMinorCPU")
print(f"Number of cores    : {len(system.cpu)}")

print("")
print("Private L1:")
print(f"  L1I size         : 32KiB")
print(f"  L1D size         : 32KiB")
print(f"  associativity    : 4-way")
print(f"  MSHRs per L1     : 8")

print("")
print("Shared L2:")
print(f"  size             : {args.l2_size}")
print(f"  associativity    : {args.l2_assoc}-way")
print(f"  MSHRs            : 32")
print(f"  cache line       : 64B")

print("")
print("Interconnect:")
print(f"  model            : L2XBar")
print(f"  width            : 16B / 128-bit")

print("")
print("Memory:")
print(f"  capacity         : 512MiB")
print(f"  model            : DDR4_2400_8x8")

print("")
print(f"Clock              : 1GHz")

if args.binary is None:
    print("")
    print("Workload           : NONE")
    print("NOTE:")
    print("  Hardware topology has been configured.")
    print("  No SE workload was provided, so simulation will not be")
    print("  started. Use --binary when a RISC-V workload is available.")

else:
    print("")
    print(f"Workload           : {args.binary}")

print("============================================================")
print("")


# ==============================================================================
# STEP 14: INSTANTIATE / SIMULATE
# ==============================================================================

if args.binary is None:

    # No workload yet.
    # Stop here instead of calling m5.simulate() with no runnable process.
    print("[INFO] Baseline configuration completed.")
    print("[INFO] Waiting for a RISC-V SE workload before simulation.")

else:

    print("[INFO] Instantiating gem5 system...")

    m5.instantiate()

    print("[INFO] Starting simulation...")

    exit_event = m5.simulate()

    print("")
    print("============================================================")
    print("Simulation finished")
    print("============================================================")
    print(f"Tick   : {m5.curTick()}")
    print(f"Cause  : {exit_event.getCause()}")
    print("============================================================")

