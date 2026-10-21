# Makefile - baseline cụm 4 core CVA6 (gem5)
#
#   make workload                              build workload RISC-V -> build/l2_workloads
#   make run                                   cap, 768 KiB, 16 way @ 100 MHz
#   make run CLOCK=50MHz SET="l2.active_ways=8" ARGS="rand {fp} 64 {core} 1 0 8"
#   make sweep PLAN=ways JOBS=3              quét nhiều cấu hình -> results/<clock>/<plan>.csv/.md
#   make sweep PLAN=all CLOCK=50MHz QUICK=1
#   make check                                 tự kiểm tra bằng gem5 GIẢ (không cần gem5)
#   make clean
#
# Biến: GEM5, CROSS, CLOCK (100MHz | 50MHz), SET, ARGS, FOOTPRINT, OUT

GEM5      ?= $(HOME)/gem5/build/RISCV/gem5.opt
CROSS     ?= riscv64-linux-gnu-
CLOCK     ?= 100MHz
FOOTPRINT ?= 768KiB
ARGS      ?= cap {fp} 64 {core} 1 0 8
SET       ?=
OUT       ?= m5out/run_$(CLOCK)
BIN       := build/l2_workloads

.PHONY: all workload run sweep check clean help
PLAN ?= ways
JOBS ?= 3
QUICK ?=
all: workload
workload: $(BIN)

$(BIN): workloads/l2_workloads.cpp
	@mkdir -p build
	$(CROSS)g++ -std=c++17 -O2 -static -o $@ $<

run: $(BIN)
	$(GEM5) -d $(OUT) cva6_baseline.py --binary $(BIN) --clock $(CLOCK) \
	  --footprint $(FOOTPRINT) --args "$(ARGS)" $(foreach s,$(SET),--set $(s))

sweep: $(BIN)
	python3 sweep.py --plan $(PLAN) --clock $(CLOCK) -j $(JOBS) --gem5 "$(GEM5)" $(if $(QUICK),--quick)

# ---- gem5 giả: dựng hệ thống bằng đúng code baseline, số liệu là mô hình đồ chơi ----
FAKE := python3 tests/fake_gem5.py
build/l2_workloads.host: workloads/l2_workloads.cpp
	@mkdir -p build
	g++ -std=c++17 -O2 -o $@ $<

check: build/l2_workloads.host
	./build/l2_workloads.host cap 1048576 64 0 1 3 | grep "sink=49152" > /dev/null
	$(FAKE) -d build/check/100 cva6_baseline.py --binary build/l2_workloads.host > build/check.log
	$(FAKE) -d build/check/50 cva6_baseline.py --binary build/l2_workloads.host --clock 50MHz \
	  --set l2.active_ways=8 --set l2.repl=fifo | grep "50MHz (20 ns" > /dev/null
	cp build/l2_workloads.host build/l2_workloads && $(FAKE) -d build/check/ex example_custom.py \
	  | grep "Sanity" > /dev/null; rm -f build/l2_workloads
	python3 sweep.py --plan all -j 4 --gem5 "$(FAKE)" --binary build/l2_workloads.host --out build/check/sweep > /dev/null
	test -s build/check/sweep/100MHz/ways.md
	@echo "== OK: baseline, 50 MHz, example_custom.py và sweep chạy được (số liệu là đồ chơi)"

clean:
	rm -rf build m5out

help:
	@sed -n '2,11p' Makefile
