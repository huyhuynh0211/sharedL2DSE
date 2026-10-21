# example_custom.py - ví dụ cho các bạn khác: lấy baseline làm "core", chỉ đổi phần của mình.
#
#   gem5.opt -d out/huy_fifo example_custom.py
#
# gem5 tự thêm thư mục của script vào sys.path, nên đặt file này cạnh cva6_baseline.py.
from cva6_baseline import build_system, make_params, run_and_report

# Ví dụ: bạn làm L2 thử FIFO với 8 way, workload ngẫu nhiên, ở 50 MHz
params = make_params("50MHz", {"l2.repl": "fifo", "l2.active_ways": 8})

binary = "build/l2_workloads"
footprint_per_core = 768 * 1024 // params["num_cores"]
cmds = [["rand", footprint_per_core, 64, core, 1, 0, 8] for core in range(params["num_cores"])]

system = build_system(params, binary, cmds)
# (có thể sửa thêm SimObject trước khi chạy, ví dụ: system.l2.mshrs = 16)
run_and_report(system, params, tag="huy_fifo_8w_50MHz")
