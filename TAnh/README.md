# Baseline cụm 4 core CVA6 + L2 chia sẻ (gem5)

Một file `cva6_baseline.py`: 4 core MinorCPU chỉnh theo CVA6, L1I/L1D riêng, NoC (`L2XBar`),
L2 chia sẻ 1 MiB / 16 way / 1024 set và DDR4-2400. Chạy gem5 classic, SE mode, xung nhịp
**100 MHz** (mặc định) hoặc **50 MHz**. File vừa chạy trực tiếp được, vừa import được như
một "core" để các bạn gắn phần của mình vào.

## Chạy

```bash
make workload                     # build/l2_workloads (riscv64-linux-gnu-g++)
make run                          # cap, footprint tổng 768 KiB, 16 way @ 100 MHz
make run CLOCK=50MHz SET="l2.active_ways=8" ARGS="rand {fp} 64 {core} 1 0 8"
make check                        # tự kiểm tra bằng gem5 giả, không cần gem5
```

Hoặc chạy thẳng gem5:

```bash
gem5.opt -d out/x cva6_baseline.py --binary build/l2_workloads \
    --args "cap {fp} 64 {core} 1 0 8" --clock 100MHz --set l2.active_ways=8
```

- `--args` là tham số cho mỗi core: `{core}` được thay bằng số thứ tự core, `{fp}` bằng
  footprint mỗi core (`--footprint` chia 4). Dùng được với chương trình bất kỳ, không riêng
  `l2_workloads`.
- `--set khóa=giá_trị` ghi đè thông số trong bảng `BASELINE`, ví dụ `l2.repl=fifo`,
  `l2.size=512KiB`, `l1d.assoc=4`, `measure_cycles=0`. Gõ sai tên khóa thì báo lỗi ngay.

Kết quả nằm trong thư mục `-d`: `stats.txt` và `summary.json`. Trong `summary.json` có:
- **Đo (Measured):** cycles, IPC, miss rate L1D/L2, MPKI, độ trễ miss L1D, số MSHR hit, upgrade miss, writeback.
- **Tính (Computed):** AMAT.
- **Kiểm tra:** tỷ lệ L2 accesses / Σ L1 miss, phải ≈ 1.

## Chạy nhiều cấu hình để làm bảng báo cáo: `sweep.py`

```bash
make sweep PLAN=ways JOBS=3              # (1) số way hoạt động: W = 16..2, giữ 1024 set
make sweep PLAN=capacity                 # (2) dung lượng 256 KiB..2 MiB, 16 way
make sweep PLAN=assoc                    # (3) associativity 1..32 way, 1 MiB
make sweep PLAN=all CLOCK=50MHz          # cả ba, ở 50 MHz
make sweep PLAN=all QUICK=1              # cửa sổ ngắn để thử trước (số liệu chưa ổn định)
```

Mỗi plan chạy 3 workload (`cap`, `rand`, `write`), song song `JOBS` lần, và bỏ qua lần đã có
kết quả: dừng giữa chừng thì chạy lại lệnh cũ để làm tiếp. Kết quả nằm trong `results/<clock>/`:
- `<plan>.csv` để vẽ hình hoặc xử lý tiếp.
- `<plan>.md`: bảng Markdown dán thẳng vào báo cáo, kèm dòng giả định độ trễ và nhãn
  Measured / Computed / Assumed. Các cột: L2 miss, MPKI, IPC, độ trễ miss L1D, AMAT, cycles
  và cycles so với 1 MiB / 16 way.

Muốn đổi danh sách cấu hình hoặc workload thì sửa `PLANS` và `WORKLOADS` ở đầu `sweep.py`.
`python3 sweep.py --plan ways --table-only` chỉ gom lại bảng mà không chạy.

## Dùng làm "core" cho phần của bạn

Xem `example_custom.py`. Đặt script cạnh `cva6_baseline.py` rồi viết:

```python
from cva6_baseline import make_params, build_system, run_and_report

p = make_params("50MHz", {"l2.repl": "fifo", "l2.active_ways": 8})   # chỉ đổi phần của mình
system = build_system(p, "build/l2_workloads", cmds_cho_từng_core)
system.l2.mshrs = 16          # muốn sửa thêm SimObject thì sửa ở đây, trước khi chạy
run_and_report(system, p, tag="ten_lan_chay")
```

Chạy bằng `gem5.opt -d out/y my_script.py`.

## Thông số và nguồn

| Thành phần | Giá trị | Nguồn |
|---|---|---|
| Core | MinorCPU 1-issue, commit 2 | RTL CVA6 |
| L1I / L1D | 16 KiB 4-way / 32 KiB 8-way, 1 chu kỳ, 1 MSHR, thay thế ngẫu nhiên | RTL CVA6 (LFSR ≈ random) |
| NoC | `L2XBar`, 16 B/chu kỳ, 1/1/1 chu kỳ | Giả định |
| L2 | 1 MiB, 16 way, 1024 set, LRU, non-inclusive, 32 MSHR, không prefetch | Spec đề nghị |
| L2 hit | 2 chu kỳ @ 100 MHz, 1 chu kỳ @ 50 MHz (khoảng 14 ns) | Giả định |
| DRAM | DDR4-2400 (gem5 tính theo ns, đúng ở mọi clock) | Base model |
| Đo | Warm-up 2 M chu kỳ, rồi đo 10 M chu kỳ khi cả 4 core cùng chạy | |

Độ trễ phụ thuộc clock nằm trong `CLOCK_PRESETS`. Có thông số chip thật thì sửa ở đó.

## Workload `workloads/l2_workloads.cpp`

`l2_workloads <mode> <bytes_per_core> <stride> <core_id> <seed> <iters> [width]`

Các mode: `cap`, `cap_rand`, `rand`, `binv`, `write`, `rmw`. Đặt `iters = 0` để chạy mãi,
gem5 sẽ dừng theo cửa sổ đo.

## `make check`

Chạy baseline bằng m5 giả ở 100 MHz, ở 50 MHz và qua `example_custom.py`. Bước này bắt được
lỗi cấu hình và lỗi Python, nhưng **không** bắt được tên tham số sai của gem5 thật, và
**số liệu của nó là đồ chơi**. Lần đầu chạy gem5 thật, nếu `summary.json` có metric bằng
`null`, hãy kiểm tra tên stat trong `stats.txt` rồi sửa hàm `compute_metrics`.
