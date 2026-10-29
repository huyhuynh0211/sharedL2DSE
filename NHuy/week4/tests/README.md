# tests/ — workload "code thật" trích từ cva6 và riscv-tests (2026-10-27)

Mục đích: dùng làm đối chứng bằng chương trình thật, đặt cạnh bộ synthetic `l2traffic`
(loop/stream/temporal/graph) trong DSE L2 chia sẻ. Đây là **bản trích nguyên gốc, chưa port**:
mọi chương trình vẫn là bare-metal (crt.S + syscalls.c, kết thúc qua `tohost`, đọc
`mcycle`/`minstret`/`mhartid`), nên chưa chạy được trên gem5 SE nếu chưa sửa.

## Nguồn
| Thư mục | Lấy từ | Phiên bản |
|---|---|---|
| `coremark/` | `cva6/verif/tests/custom/coremark/` | cva6 local (week4) |
| `dhrystone/` | `cva6/verif/tests/custom/dhrystone/` | cva6 local (week4) |
| `cva6_common/` | `cva6/verif/tests/custom/common/{crt.S,syscalls.c,util.h}` + `env/encoding.h` | runtime bare-metal mà 2 thư mục trên cần |
| `riscv-tests/benchmarks/` | github.com/riscv-software-src/riscv-tests | commit `3df703cd52d5` (2026-10-19) |

Submodule `verif/tests/riscv-tests` của cva6 chưa được clone trên máy, nên bộ benchmark lấy từ
upstream (chỉ giữ 7 benchmark đã chọn + `common/`; Makefile gốc đổi tên thành
`Makefile.upstream`, danh sách bmarks trong đó vẫn là bản đầy đủ). cva6 còn áp `verif/regress/riscv-tests.patch` lên bản của nó (chưa áp ở đây).

## Footprint dữ liệu mặc định (tính từ khai báo trong nguồn)
| Workload | Kích thước mặc định | Dữ liệu ≈ | Mẫu truy cập |
|---|---|---|---|
| coremark | TOTAL_DATA_SIZE 2000 B, MEM_STATIC | 2 KB | list con trỏ + matrix + state machine |
| dhrystone | — | < 1 KB | điều khiển, chuỗi ký tự |
| spmv | R=C=500, NNZ=2399, double | ~39 KB | CSR, x[idx[k]] gián tiếp |
| vvadd | DATA_SIZE 300 (`dataset1-large.h`: 1000) | 7–24 KB | streaming 3 mảng |
| mt-vvadd | DATA_SIZE 1000, double, đa luồng | 24 KB | streaming chia theo core |
| mm | khối CBM×CBN×CBK (rb.h), double | nhỏ | ma trận chia khối, có reuse |
| mt-matmul | 16×16 int, đa luồng | 3 KB | matmul chia theo core |
| qsort | 2048 phần tử | ~8–16 KB | sắp xếp, đệ quy |
| rsort | 2048 phần tử, base 2^8 | ~8–16 KB + bucket | histogram ngẫu nhiên |

Tất cả xấp xỉ L1D 32 KiB hoặc nhỏ hơn → L2 miss gần 0 ở cấu hình mặc định. Muốn đo độ nhạy
theo số way phải sinh lại dataset lớn hơn (`*_gendata.pl` / `*.scala`) hoặc nâng `TOTAL_DATA_SIZE`.

## Lệnh build gốc (bare-metal, tham khảo từ cva6/verif/regress)
- benchmark.sh: `-O3 --no-inline -static -mcmodel=medany -nostdlib -nostartfiles -lgcc
  -fno-tree-loop-distribute-patterns -DNOPRINT` + `common/crt.S common/syscalls.c`, linker
  `config/gen_from_riscv_config/linker/link.ld`.
- coremark.sh: như trên + `-funroll-all-loops -DITERATIONS=1 -DPERFORMANCE_RUN -DSKIP_TIME_CHECK`,
  ISA rv32imc_zba_zbb_zbc_zbs (target cv32a65x).

## Việc cần làm trước khi chạy trên gem5 SE
1. Bỏ crt.S/syscalls.c, dịch `riscv64-linux-gnu-gcc -static` có `main` bình thường (cùng mức -O
   với l2traffic để so MPKI).
2. Thay đọc `mcycle`/`minstret` (coremark `core_portme.c`, `util.h`, `mm_main.c`) bằng
   `clock_gettime` hoặc m5op ROI.
3. `mt-*`, `mm`: thay `thread_entry(cid, nc)` + barrier dựa `mhartid` bằng pthreads,
   hoặc chạy 4 tiến trình độc lập.
