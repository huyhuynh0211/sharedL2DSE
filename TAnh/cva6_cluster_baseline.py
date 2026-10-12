# ==============================================================================
# PROJECT: Shared L2 Design Space Exploration
# SCRIPT: cva6_cluster_baseline.py
# ROLE: SoC & Interconnect Architect (Tiến Anh)
# DESCRIPTION: STABLE 4-Core CVA6 (6-stage latency) + 128-bit NoC + Shared L2 + DDR4
# ==============================================================================

import argparse
import sys
import os
import m5
from m5.objects import *

# ------------------------------------------------------------------------------
# BƯỚC 1: KHAI BÁO CÁC THAM SỐ DÒNG LỆNH
# ------------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="4-core CVA6 RISC-V Cluster Baseline")

parser.add_argument("--binary", type=str, required=True, help="Đường dẫn tới file chạy")
parser.add_argument("--l2_size", type=str, default="1MB", help="Dung lượng Shared L2 Cache")
parser.add_argument("--l2_assoc", type=int, default=16, help="Số Way của L2 Cache")
parser.add_argument("--footprint", type=str, default="2097152", help="Vùng nhớ làm việc")
parser.add_argument("--stride", type=str, default="64", help="Bước nhảy truy cập bộ nhớ")

args = parser.parse_args()


# ------------------------------------------------------------------------------
# BƯỚC 2: ĐỊNH NGHĨA VI KIẾN TRÚC CVA6 (STABLE MAPPING)
# ------------------------------------------------------------------------------
class CVA6_Core(RiscvMinorCPU):
    """
    Sử dụng MinorCPU làm nền tảng.
    Áp dụng Parameterization (Bù trễ) để map 4-stage thành 6-stage của CVA6.
    Không can thiệp sâu vào FUPool để tránh Deadlock pipeline.
    """
    # Bù trễ để giả lập 6 tầng (PC -> Fetch -> Decode -> Issue -> Execute -> Commit)
    fetch1ToFetch2ForwardDelay = 1   
    fetch2ToDecodeForwardDelay = 1   
    decodeToExecuteForwardDelay = 2  # Bù trễ cho tầng Issue


# ------------------------------------------------------------------------------
# BƯỚC 3: ĐỊNH NGHĨA HỆ THỐNG BỘ NHỚ & MẠNG LIÊN KẾT
# ------------------------------------------------------------------------------
class L1Cache(Cache):
    assoc = 4
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 4
    tgts_per_mshr = 8

class L1ICache(L1Cache):
    size = '32KiB'
    def connectCPU(self, cpu):
        self.cpu_side = cpu.icache_port
    def connectBus(self, bus):
        self.mem_side = bus.cpu_side_ports

class L1DCache(L1Cache):
    size = '32KiB'
    def connectCPU(self, cpu):
        self.cpu_side = cpu.dcache_port
    def connectBus(self, bus):
        self.mem_side = bus.cpu_side_ports

class SharedL2Cache(Cache):
    tag_latency = 14
    data_latency = 14
    response_latency = 14
    mshrs = 32                  
    tgts_per_mshr = 12
    write_buffers = 16

    def __init__(self, size='1MB', assoc=16, **kwargs):
        super(SharedL2Cache, self).__init__(**kwargs)
        self.size = size
        self.assoc = assoc

    def connectCPUSideBus(self, bus):
        self.cpu_side = bus.mem_side_ports
    def connectMemSideBus(self, bus):
        self.mem_side = bus.cpu_side_ports

class ClusterNoC(L2XBar):
    width = 32                
    frontend_latency = 2       
    forward_latency = 2
    response_latency = 2


# ------------------------------------------------------------------------------
# BƯỚC 4: KHỞI TẠO HỆ THỐNG VÀ ĐẤU NỐI
# ------------------------------------------------------------------------------
system = System()

system.clk_domain = SrcClockDomain(clock='1GHz', voltage_domain=VoltageDomain())
system.mem_mode = 'timing'
system.cache_line_size = 64
system.mem_ranges = [AddrRange('512MiB')]

num_cores = 4
system.cpu = [CVA6_Core(cpu_id=i) for i in range(num_cores)]

system.noc = ClusterNoC()
system.l2cache = SharedL2Cache(size=args.l2_size, assoc=args.l2_assoc)
system.membus = SystemXBar()

for i in range(num_cores):
    core = system.cpu[i]
    
    # Gắn Cache
    core.icache = L1ICache()
    core.dcache = L1DCache()

    core.icache.connectCPU(core)
    core.dcache.connectCPU(core)
    core.icache.connectBus(system.noc)
    core.dcache.connectBus(system.noc)
    
    # MMU & Ngắt
    core.mmu = RiscvMMU()
    core.createInterruptController()

system.l2cache.connectCPUSideBus(system.noc)
system.l2cache.connectMemSideBus(system.membus)

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR5_8400_4x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports
system.system_port = system.membus.cpu_side_ports


# ------------------------------------------------------------------------------
# BƯỚC 5: GÁN TIẾN TRÌNH LÀM VIỆC
# ------------------------------------------------------------------------------
system.workload = SEWorkload.init_compatible(args.binary)

processes = []
for i in range(num_cores):
    process = Process(pid=100 + i)
    process.cmd = [args.binary, args.footprint, args.stride, str(i)]
    processes.append(process)

for i in range(num_cores):
    system.cpu[i].workload = processes[i]
    system.cpu[i].createThreads()


# ------------------------------------------------------------------------------
# BƯỚC 6: CHẠY MÔ PHỎNG
# ------------------------------------------------------------------------------
root = Root(full_system=False, system=system)
m5.instantiate()

print("=" * 70)
print("[*] KHOI DONG HE THONG 4-CORE CVA6 (STABLE BASELINE v25)")
# ... (các lệnh print)
print("=" * 70)

exit_event = m5.simulate()
print(f"[*] Mo phong ket thuc tai tick {m5.curTick()}. Ly do: {exit_event.getCause()}")

# >>> THÊM ĐÚNG 1 DÒNG NÀY VÀO ĐÂY <<<
m5.stats.dump() 
# Lệnh này ép gem5 xả toàn bộ số liệu từ RAM xuống file stats.txt ngay lập tức!

# ------------------------------------------------------------------------------
# BƯỚC 7: TỰ ĐỘNG HÓA TRÍCH XUẤT SỐ LIỆU
# ------------------------------------------------------------------------------
out_dir = m5.options.outdir
stats_file_path = os.path.join(out_dir, 'stats.txt')
summary_file_path = os.path.join(out_dir, 'summary_report.csv')

metrics_to_hunt = {
    "simTicks": "Total_Ticks",
    "system.cpu0.ipc": "IPC_Core0",
    "system.l2cache.overallMissRate::total": "L2_Miss_Rate",
    "system.l2cache.overallAvgMissLatency::total": "L2_Avg_Miss_Latency",
    "system.noc.snoop_filter.totRequests": "NoC_Total_Requests",
    "system.mem_ctrl.dram.avgMemAccLat": "DDR4_Avg_Latency",
    "system.mem_ctrl.dram.busUtil": "DDR4_Bus_Utilization(%)"
}

extracted_data = {v: "N/A" for v in metrics_to_hunt.values()}

try:
    with open(stats_file_path, 'r') as f:
        for line in f:
            if not line.strip() or line.startswith('---'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                metric_name = parts[0]
                if metric_name in metrics_to_hunt:
                    extracted_data[metrics_to_hunt[metric_name]] = parts[1]

    file_exists = os.path.isfile(summary_file_path)
    with open(summary_file_path, 'a') as f_out:
        if not file_exists:
            header = "L2_Size,L2_Assoc,Footprint," + ",".join(metrics_to_hunt.values())
            f_out.write(header + "\n")
        
        values = f"{args.l2_size},{args.l2_assoc},{args.footprint}," + ",".join([extracted_data[v] for v in metrics_to_hunt.values()])
        f_out.write(values + "\n")

    print(f"[*] THÀNH CÔNG: Đã xuất số liệu tự động ra file -> {summary_file_path}")

except Exception as e:
    print(f"[!] Lỗi khi trích xuất số liệu: {e}")