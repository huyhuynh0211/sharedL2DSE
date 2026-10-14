# Huỳnh Ngọc Huy - HCMUS - Intern: L2 Cache & Way-Shutdown Specialist (P1)
## Báo cáo tuần 1 (bản sửa)

Ghi chú về giả định: dung lượng L2 production và replacement policy thật chưa được xác nhận. Trong báo cáo này dùng giả định **L2 = 1 MiB, 16-way, line 64 B, LRU**. Các con số phụ thuộc giả định này được đánh dấu *(giả định)*.

---

# 1. What

## 1.1. Hệ thống mục tiêu

```text
Tile0: Core0 -> L1I/L1D \
Tile1: Core1 -> L1I/L1D  \
                          ---> Crossbar/NoC ---> Shared L2 ---> Memory controller ---> DRAM
Tile2: Core2 -> L1I/L1D  /                          ^
Tile3: Core3 -> L1I/L1D /                           |
                                     Vector/DSP unit (mô phỏng bằng synthetic traffic generator)
```

- 4 core RISC-V in-order, mô hình bằng MinorCPU trong gem5 (gần với CVA6 hơn O3CPU).
- Mỗi core có L1I và L1D riêng (private). L2 dùng chung (shared) cho cả 4 core.
- Khối vector/DSP được xấp xỉ bằng traffic generator gắn vào phía L2, truy cập L2 không qua L1.
- L2: line 64 B, 16 way. Số MSHR nằm ngoài phạm vi mô phỏng (giữ cố định).

## 1.2. Cache

**Định nghĩa.** Cache là bộ nhớ SRAM nhỏ, nhanh, đặt gần CPU, giữ bản sao các block dữ liệu và lệnh hay dùng từ DRAM để giảm thời gian chờ bộ nhớ.

**Tổ chức set-associative.**

```text
            way0    way1    ...    way15
set0      | line  | line  | ...  | line  |
set1      | line  | line  | ...  | line  |
...
set1023   | line  | line  | ...  | line  |
```

- Một địa chỉ chỉ được đặt vào đúng một set (xác định bởi bit index), nhưng có thể nằm ở bất kỳ way nào trong set đó.
- Số set = dung lượng / (line size × số way).
- Ví dụ *(giả định)*: 1 MiB / (64 B × 16) = 1024 set.

**Một line gồm hai phần:**
- Data: 64 B dữ liệu. "Line size 64 B" chỉ phần này.
- Metadata (nằm ở tag array riêng, là phần cộng thêm): valid bit, dirty bit, tag, các bit phục vụ replacement policy.

**Tách địa chỉ (address split).**

| Phần | Số bit | Ví dụ (1024 set, line 64 B) |
|---|---|---|
| Offset | log2(line size) | 6 bit |
| Index | log2(số set) | 10 bit |
| Tag | phần còn lại | (độ rộng địa chỉ − 16) bit |

Hệ quả: hai địa chỉ cách nhau một bội số của `số set × line size = 1024 × 64 B = 64 KiB` rơi vào cùng một set. Đây là **aliasing stride**. Workload có stride bằng bội số của 64 KiB chỉ dùng một set và miss rất nhiều.

**Hit và miss.**
- Hit: đúng set, tag khớp, valid = 1.
- Miss: không tìm thấy block chứa địa chỉ cần truy cập (lệnh hoặc dữ liệu). Phân loại:
  - Compulsory: block chưa từng được nạp.
  - Capacity: tổng dữ liệu đang dùng lớn hơn dung lượng cache.
  - Conflict: nhiều block cùng rơi vào một set, vượt quá số way, dù cache còn chỗ ở set khác.
  - Coherence: line bị invalidate vì core khác ghi vào cùng địa chỉ.
- Way shutdown làm tăng chủ yếu capacity miss và conflict miss, vì mỗi set còn ít way hơn.

**Chính sách ghi.**
- Write-through: ghi cả cache và tầng dưới. Đơn giản, tốn băng thông, thường có write buffer.
- Write-back: chỉ ghi cache, đặt dirty = 1, ghi xuống khi line bị đuổi (eviction). Tiết kiệm băng thông.
- Khi ghi miss: write-allocate (nạp block rồi ghi, thường đi với write-back) hoặc no-write-allocate (ghi thẳng xuống, thường đi với write-through).

**Replacement policy.** Khi set đã đầy, chọn line nào để đuổi:
- LRU: đuổi line lâu nhất chưa được dùng. Chính xác nhưng tốn bit khi số way lớn.
- Tree-PLRU: xấp xỉ LRU bằng cây nhị phân, rẻ hơn, phổ biến trong phần cứng thật.
- Random: chọn ngẫu nhiên.

Policy quan trọng với P1 vì cách mô hình way shutdown (mục 5.2) chỉ tương đương chính xác khi dùng LRU.

**Inclusion policy** (quan hệ giữa L1 và L2):
- Inclusive: mọi line ở L1 đều có ở L2.
- Exclusive: một line chỉ ở L1 hoặc L2.
- Non-inclusive: không ràng buộc.

Cần ghi rõ policy đang dùng và giữ cố định qua mọi cấu hình.

**Bank.** Cache lớn thường chia thành nhiều bank, mỗi bank có mạch giải mã và đường đọc/ghi riêng, cho phép phục vụ song song. gem5 classic không mô hình bank của L2, nên điểm này chỉ ghi nhận về mặt khái niệm.

## 1.3. Chỉ số đánh giá

- **Miss rate (local)** = số miss tại cache đó / số truy cập tới cache đó.
- **Miss rate (global)** = số miss tại cache đó / tổng số truy cập bộ nhớ của CPU.
- **MPKI** = số miss / (số lệnh commit / 1000). Dùng để so sánh giữa các workload có số truy cập khác nhau.
- **AMAT** (thời gian truy cập bộ nhớ trung bình):

```text
AMAT = t_L1 + m_L1 × (t_NoC_req + t_L2 + m_L2 × t_mem + t_NoC_resp)
```

  Trong đó m_L1, m_L2 là local miss rate. Miss rate lấy từ mô phỏng. Các độ trễ t_* là giả định có nguồn, lấy từ datasheet, mô hình NoC hoặc RTL.

## 1.4. Way shutdown

**Định nghĩa.** Way shutdown là tắt nguồn (power-gating) một số way của cache set-associative khi workload không cần toàn bộ dung lượng. Số set và cách index giữ nguyên; chỉ số way khả dụng giảm.

**Cơ chế phần cứng.** Gated-Vdd: thêm transistor ngắt nguồn cho mảng SRAM của way bị tắt. Khi bị ngắt, way đó gần như không tiêu thụ leakage và mất dữ liệu.

**Mục đích.** Giảm leakage power, tức công suất rò khi transistor không chuyển trạng thái. Ở node công nghệ nhỏ, SRAM dung lượng lớn như L2 có leakage chiếm phần đáng kể trong tổng công suất cache.

**Cái giá phải trả.**
- Dung lượng hiệu dụng giảm, nên miss tăng, nên AMAT tăng.
- Chi phí chuyển trạng thái: trước khi tắt, các dirty line trong way bị tắt phải được ghi về bộ nhớ. Sau khi bật lại, way trống nên có thêm miss để nạp lại.
- Cần cơ chế quyết định khi nào tắt hay bật (phần mềm, firmware hoặc phần cứng tự theo dõi miss).

**Tài liệu nền tảng:**
- D. H. Albonesi, "Selective Cache Ways: On-Demand Cache Resource Allocation", MICRO 1999.
- M. Powell et al., "Gated-Vdd: A Circuit Technique to Reduce Leakage in Deep-Submicron Cache Memories", ISLPED 2000.

## 1.5. Workload và synthetic traffic

**Workload** là chương trình cùng dữ liệu đầu vào chạy trên hệ thống để đánh giá. Với cache, các đặc trưng chính:
- **Footprint**: số line khác nhau được truy cập × 64 B.
- **Reuse distance**: số line khác nhau được truy cập giữa hai lần dùng lại cùng một line.
- **Kiểu truy cập**: tuần tự, có stride, ngẫu nhiên.
- **Tỉ lệ đọc/ghi**: ảnh hưởng số dirty line, tức ảnh hưởng writeback và chi phí khi tắt way.

**Liên hệ với way shutdown.** Một workload phù hợp để tắt way khi working set của nó vừa với dung lượng còn lại sau khi tắt. Tiêu chí là footprint và reuse distance so với dung lượng, không phải độ "đơn giản" hay "phức tạp" của chương trình. Một vòng lặp đơn giản quét mảng 2 MiB vẫn miss gần hết trên L2 1 MiB.

**Synthetic traffic generator** sinh chuỗi địa chỉ theo tham số để mô phỏng khối vector/DSP:
- Stride: khoảng cách giữa hai truy cập liên tiếp. Stride 64 B là duyệt tuần tự từng line.
- Footprint: vùng địa chỉ được truy cập.
- Tỉ lệ đọc/ghi, tốc độ phát request (injection rate), số luồng, seed.

Generator được gắn ở phía L2, nên toàn bộ traffic của nó đi thẳng vào L2. Đây là một xấp xỉ.

## 1.6. gem5

**Định nghĩa.** gem5 là simulator kiến trúc máy tính mã nguồn mở, viết bằng C++ và cấu hình bằng Python. Nó cho phép dựng hệ thống gồm CPU, cache, interconnect và bộ nhớ, chạy chương trình trên hệ thống đó, rồi xuất thống kê (stats.txt) và cấu hình thực tế (config.ini).

**CPU model dùng trong project.**
- **MinorCPU**: in-order, pipeline 4 tầng, gần với CVA6.
- **O3CPU**: out-of-order. Có thể có nhiều miss đang chờ cùng lúc, tức memory-level parallelism (MLP) cao.

```text
MinorCPU:  load A miss ---- chờ ----> load B miss ---- chờ ---->
O3CPU:     load A miss ----\
                            chờ chung (chồng lấp)
           load B miss ----/
```

MinorCPU vẫn có load/store queue và có thể có một vài miss đang chờ, nhưng MLP thấp hơn O3 nhiều. Dùng O3 sẽ tạo áp lực bộ nhớ không giống CVA6.

**Standard library** gồm 4 thành phần:
- Board: kết nối toàn hệ thống (SimpleBoard, RiscvBoard...).
- Processor: loại CPU, số core, ISA.
- Memory: loại DRAM và số kênh.
- CacheHierarchy: NoCache, các hierarchy classic, hoặc Ruby.

Với project cần hierarchy có **L1 private và L2 shared** (ví dụ `PrivateL1SharedL2CacheHierarchy` trong classic). Không dùng `PrivateL1PrivateL2`, vì hierarchy đó tạo một L2 riêng cho mỗi core.

**Hai chế độ chạy.**
- **SE (syscall emulation)**: chạy binary trực tiếp, gem5 giả lập system call. Nhanh, không cần kernel hay disk image. Đủ cho workload multi-programmed (4 chương trình độc lập, mỗi core một chương trình).
- **FS (full system)**: boot kernel Linux. Cần khi workload đa luồng phụ thuộc OS hoặc khi cần đo tác động của OS. Chậm hơn nhiều và cần kernel/disk image RISC-V.

Project này dùng SE. FS là hướng mở rộng nếu sau này cần workload đa luồng.

**Memory system.**
- Classic: crossbar, nhanh, phù hợp cho sweep số lượng lớn.
- Ruby + Garnet: mô hình coherence protocol và NoC chi tiết, chậm hơn.

Miss rate không phụ thuộc nhiều vào chi tiết NoC, nên sweep chạy trên classic. Độ trễ NoC đưa vào AMAT bằng mô hình giải tích.

## 1.7. DRAMSim3

**Định nghĩa.** DRAMSim3 là simulator DRAM cycle-accurate do University of Maryland phát triển. Nó mô hình bank, bank group, row buffer, refresh, các ràng buộc timing (tRCD, tCL, tRP...) và hỗ trợ DDR3, DDR4, LPDDR3/4, GDDR5/6, HBM. Có thể chạy độc lập với trace, hoặc ghép vào gem5 làm memory backend (gem5 có wrapper; cần kiểm tra ở phiên bản gem5 đã pin).

**Khác với DRAM model có sẵn của gem5.** gem5 có memory controller và DRAM interface riêng, đủ dùng trong nhiều trường hợp. DRAMSim3 chi tiết hơn và đã được kiểm chứng với các chuẩn DRAM cụ thể.

**Vai trò trong P1.** Số miss của L2 gần như không phụ thuộc DRAM model. DRAM model ảnh hưởng tới:
- t_mem trong công thức AMAT.
- Timing của hệ thống, qua đó gián tiếp ảnh hưởng thứ tự truy cập vào L2 dùng chung (xem mục 5.6).

## 1.8. NoC và FlooNoC (phần liên quan tới P1)

- Nhiều khối trên chip dùng chung một bus sẽ gây nghẽn. NoC dùng router và link để có nhiều đường truyền song song.
- **FlooNoC** (nhóm PULP, ETH Zurich) là NoC ở mức RTL (SystemVerilog), truyền giao dịch AXI4. Nó có link rộng cho dữ liệu và link hẹp cho request/điều khiển. Chimney là network interface chuyển AXI thành flit.
- Chi tiết NoC thuộc phần việc của Quyên và Ngọc. Với P1, chỉ cần số hop × độ trễ mỗi hop để có t_NoC_req và t_NoC_resp trong AMAT.
- gem5 và FlooNoC không ghép trực tiếp: gem5 là simulator C++, FlooNoC là RTL. Muốn dùng traffic từ gem5 cho FlooNoC phải xuất trace rồi chuyển thành stimulus cho testbench RTL.

## 1.9. Công cụ ước lượng công suất

- **CACTI**: mô hình diện tích, độ trễ, năng lượng động và leakage của mảng SRAM/cache theo dung lượng, số way, line size và node công nghệ.
- **McPAT**: mô hình công suất mức chip (core, cache, NoC). Phần cache của McPAT dùng CACTI bên dưới.

Với P1, chạy CACTI trực tiếp cho L2 là đủ để ước lượng leakage per way.

---

# 2. Why

**gem5**
- Đánh giá tác động ở mức hệ thống: thay đổi L2 ảnh hưởng tới miss của từng core, traffic xuống DRAM và thời gian chạy.
- Thử nhiều cấu hình nhanh: cấu hình bằng Python nên sinh và chạy hàng loạt cấu hình (số way, dung lượng, associativity, workload) được.
- Có thống kê chi tiết theo từng cache và từng requestor (core0–3, generator).
- Chưa cần RTL vẫn đánh giá được.

**DRAMSim3**
- Cần độ trễ DRAM sát thực tế (row buffer hit/miss, tranh chấp bank) để t_mem trong AMAT có cơ sở.
- Dùng làm nguồn tham chiếu cho giá trị low/nominal/high của t_mem.

**CACTI / McPAT**
- gem5 không mô hình power-gating theo way và không tính leakage. Cần công cụ riêng để có con số công suất, đặt cạnh miss rate khi đánh giá trade-off.

**FlooNoC**
- Cho độ trễ và băng thông NoC đo trên RTL thật, thay vì tự giả định.

**Way shutdown (lý do tồn tại của P1)**
- L2 có leakage lớn và tiêu tốn liên tục kể cả khi workload không dùng hết dung lượng.
- Nếu nhiều workload chỉ cần một phần L2, tắt bớt way giảm được leakage với mức tăng miss chấp nhận được.
- P1 cần số liệu để biết mức "chấp nhận được" đó nằm ở đâu.

---

# 3. When

| Công cụ | Dùng khi | Không dùng khi |
|---|---|---|
| gem5 | So sánh nhiều cấu hình cache/CPU ở giai đoạn trước khi chốt kiến trúc, chưa có RTL | Cần công suất, diện tích; cần kiểm chứng chức năng RTL |
| DRAMSim3 | Cần độ trễ, băng thông DRAM chi tiết; nhiều requestor tranh chấp DRAM | Chỉ cần đếm miss L2 (DRAM model không ảnh hưởng nhiều) |
| CACTI/McPAT | Cần ước lượng leakage, năng lượng mỗi truy cập, diện tích của cache | Cần số đo công suất chính xác sau layout |
| FlooNoC | Cần độ trễ, băng thông NoC đo trên RTL; quyết định topology, vị trí L2 và memory controller | Sweep số lượng lớn cấu hình cache (quá chậm) |

**Trường hợp cụ thể trong project:**
- Giai đoạn M0–M1: dùng gem5 dựng baseline 4 core và chạy microbenchmark để kiểm tra.
- Giai đoạn M3–M4: dùng gem5 chạy sweep (1) số way active, (2) dung lượng, (3) associativity.
- Giai đoạn M5: dùng độ trễ từ FlooNoC hoặc mô hình hop và DRAMSim3 để tính AMAT; dùng CACTI để ước lượng leakage tiết kiệm được.

**Nguyên tắc chung.** Mô phỏng được dùng ở giai đoạn đầu vì thay đổi thiết kế lúc này rẻ. Sau tape-out, sửa lỗi kiến trúc rất tốn kém.

---

# 4. Who

| Vị trí | Dùng công cụ nào | Để làm gì |
|---|---|---|
| Kỹ sư kiến trúc SoC/CPU | gem5 | So sánh cấu hình CPU, cache, bộ nhớ trước khi chốt spec |
| Kỹ sư memory/cache | gem5, CACTI | Đánh giá miss rate, replacement, way shutdown |
| Kỹ sư memory controller/DRAM | DRAMSim3, gem5 | Đánh giá scheduling, độ trễ, băng thông DRAM |
| Kỹ sư interconnect/NoC | FlooNoC, Garnet | Đo độ trễ, băng thông NoC, chọn topology |
| Kỹ sư hiệu năng và công suất | gem5 + McPAT/CACTI | Kết hợp thống kê hoạt động với mô hình công suất |
| Nhà nghiên cứu | Tất cả | Thử ý tưởng mới về hệ thống nhớ |


---

# 5. How (phần P1)

## 5.1. Mục tiêu P1

Trả lời ba câu hỏi:
1. Khi giảm số way active của L2 từ 16 xuống 2, miss rate và MPKI của từng workload tăng thế nào? Điểm gãy (knee) nằm ở đâu?
2. Với cùng dung lượng, tắt way có tệ hơn một cache được thiết kế nhỏ ngay từ đầu không, và tệ hơn bao nhiêu?
3. Leakage tiết kiệm được là bao nhiêu so với chi phí (miss, AMAT, chi phí chuyển trạng thái)?

## 5.2. Mô hình way shutdown trong gem5

gem5 không có power-gating theo way. Trạng thái ổn định khi có W way active được mô hình bằng một L2 có:
- `assoc = W`
- `size = sets × 64 × W`
- `sets` giữ cố định = C_prod / (64 × 16)

Điều kiện tương đương:
- Đúng với LRU: LRU trên W way giống LRU trên 16 way bị che (mask) còn W way.
- Với tree-PLRU: chỉ là xấp xỉ, phải ghi vào phần giới hạn mô hình.
- Cách kiểm tra chéo: dùng partitioning policy theo way của gem5 (`WayPartitioningPolicy`, nếu có ở phiên bản đã pin) để giới hạn cấp phát vào W way trên cache 16 way vật lý, rồi so sánh với cách mô hình trên ở vài điểm.

Cách này không mô hình:
- Chi phí chuyển trạng thái (ước lượng giải tích, mục 5.7).
- Công suất (ước lượng bằng CACTI, mục 5.8).

## 5.3. Bảng cấu hình *(giả định C_prod = 1 MiB)*

**Sweep (1): số way active, giữ 1024 set**

| Config | W | Size | Sets | Offset/Index bit | Aliasing stride |
|---|---|---|---|---|---|
| S1-W16 | 16 | 1024 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W14 | 14 | 896 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W12 | 12 | 768 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W10 | 10 | 640 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W8 | 8 | 512 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W6 | 6 | 384 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W4 | 4 | 256 KiB | 1024 | 6 / 10 | 64 KiB |
| S1-W2 | 2 | 128 KiB | 1024 | 6 / 10 | 64 KiB |

Số set không đổi nên W không cần là lũy thừa của 2.

**Sweep (2): dung lượng, giữ 16 way** (số set thay đổi, phải là lũy thừa của 2)

| Config | Size | Ways | Sets | Index bit | Aliasing stride |
|---|---|---|---|---|---|
| S2-1M | 1024 KiB | 16 | 1024 | 10 | 64 KiB |
| S2-512K | 512 KiB | 16 | 512 | 9 | 32 KiB |
| S2-256K | 256 KiB | 16 | 256 | 8 | 16 KiB |
| S2-128K | 128 KiB | 16 | 128 | 7 | 8 KiB |

**Các cặp so sánh cùng dung lượng** (kết quả chính của P1):

| Dung lượng | Tắt way (sweep 1) | Thiết kế nhỏ (sweep 2) | Khác biệt |
|---|---|---|---|
| 512 KiB | S1-W8: 1024 set × 8 way | S2-512K: 512 set × 16 way | Nhiều set hơn nhưng ít way hơn mỗi set |
| 256 KiB | S1-W4: 1024 set × 4 way | S2-256K: 256 set × 16 way | |
| 128 KiB | S1-W2: 1024 set × 2 way | S2-128K: 128 set × 16 way | |

Chênh lệch miss giữa hai cột cho biết chi phí của việc giảm dung lượng bằng tắt way thay vì thiết kế sẵn cache nhỏ. Dự kiến: với workload có nhiều conflict (stride xấu), cấu hình ít way chịu thiệt hơn.

## 5.4. Các bước thực hiện

**Bước 1. Môi trường** (đã làm một phần)
- Build gem5 cho RISC-V. Ghi lại phiên bản hoặc commit gem5 và dùng cố định cho cả nhóm.
- Đã làm: viết chương trình C, cross-compile sang RISC-V, cấu hình bằng stdlib (SimpleBoard), chạy SE, đọc stats.txt.
- Đã so sánh NoCache với hierarchy có cache: numCycles, simSeconds và số truy cập mem_ctrl giảm mạnh khi có cache, vì phần lớn truy cập hit ở L1 và chỉ miss ở L2 mới xuống DRAM.
- Lưu ý: hello world rất ngắn, hầu hết miss là compulsory, nên không dùng được để đánh giá L2. Chỉ dùng làm smoke test.

**Bước 2. Baseline 4 core với L2 dùng chung** (phụ thuộc Tiến Anh, Quyên)
- 4 MinorCPU, L1I/L1D private, một L2 shared 16-way, line 64 B.
- Tắt prefetcher. Cố định replacement policy, inclusion policy và số MSHR trên mọi cấu hình.
- Kiểm tra trong config.ini: chỉ có **một** L2; size, assoc, replacement đúng như cấu hình.

**Bước 3. Kiểm tra cấu hình**
- Từ size và assoc trong config.ini tính số set, offset/index/tag bit, rồi so với bảng 5.3.
- Kiểm tra chéo: L2 accesses ≈ tổng L1 misses + L1 writebacks + request của generator.

**Bước 4. Microbenchmark dự đoán được** (kiểm tra mô hình trước khi chạy workload thật)

Chạy một stream đơn, truy cập tuần tự có chu kỳ với stride s (bội số của 64 B) và footprint F:
- Số line: N = F / 64
- k = s / 64 (stride tính theo line)
- Số set được dùng: S_used = sets / gcd(sets, k)
- Số line mỗi set: L = N / S_used

Với LRU và truy cập lặp có chu kỳ:
- L ≤ W: sau lượt đầu gần như 0% miss.
- L > W: gần như 100% miss (LRU luôn đuổi đúng line sắp được dùng lại).

Dự đoán nhị phân này chỉ đúng cho một stream, LRU, truy cập có chu kỳ. Dùng để kiểm tra mô hình, không dùng cho workload thật. Nếu kết quả lệch, kiểm tra: warm-up, replacement policy, prefetcher, address mapping, ảnh hưởng của L1.

Ví dụ: sets = 1024, stride 64 KiB (k = 1024) thì S_used = 1, tất cả line dồn vào một set. Footprint 16 line: 0% miss với W = 16, gần 100% miss với W = 8.

**Bước 5. Chạy sweep (1)** (phụ thuộc Ngọc, Choi)
- Mỗi lần chạy: một cấu hình × một workload mix × một seed. Tối thiểu 3 seed cho cấu hình có generator.
- Chạy warm-up, reset stats, rồi đo trong vùng quan tâm (ROI) cố định hoặc số lệnh cố định mỗi core.
- Lưu cho mỗi lần chạy: commit gem5, hash file cấu hình, toàn bộ tham số (JSON), workload, seed, thời gian chạy. Mỗi lần chạy một thư mục riêng.

**Bước 6. Thống kê cần lấy** (tên cụ thể phụ thuộc phiên bản gem5, cần kiểm tra trong stats.txt)
- L2: demand accesses, hits, misses, miss rate (tổng và theo từng requestor: cpu0–3 inst/data, generator).
- L2 writebacks (xuống DRAM).
- Số lệnh commit mỗi core (để tính MPKI).
- L1 misses mỗi core (để kiểm tra chéo).
- Độ trễ miss trung bình của gem5 (ghi là "mô phỏng, phụ thuộc mô hình").

**Bước 7. Kiểm tra hợp lý**
- Với LRU và số set cố định, tăng số way thì số miss không được tăng. Nếu tăng, kiểm tra thay đổi interleaving hoặc lỗi cấu hình trước khi kết luận.
- Spread giữa các seed phải nhỏ hơn chênh lệch giữa các cấu hình cần so sánh.

**Bước 8. Sweep (2) và so sánh cùng dung lượng** (mục 5.3)

## 5.5. Ngưỡng chấp nhận (chốt trước khi xem kết quả)

Đề xuất, cần nhóm và người hướng dẫn thống nhất:
- Ngưỡng theo miss: MPKI của L2 tăng không quá X% so với S1-W16.
- Ngưỡng theo hiệu năng: AMAT nominal tăng không quá Y% so với S1-W16.
- Knee của một workload = W nhỏ nhất vẫn thỏa ngưỡng.

Chốt X, Y trước khi chạy để kết luận không bị điều chỉnh theo số liệu.

## 5.6. Ảnh hưởng của timing tới miss rate

Với một stream vào một cache, miss rate chỉ phụ thuộc chuỗi địa chỉ và cấu hình cache. Với L2 dùng chung, chuỗi địa chỉ đến L2 là sự đan xen của 4 core (đã qua L1) và generator, và thứ tự đan xen phụ thuộc timing. Do đó miss rate đo được phụ thuộc vào:
- Mô hình CPU (MinorCPU khác CVA6).
- Cấu hình L1.
- Injection rate của generator.
- Độ trễ NoC và DRAM.

Cách kiểm tra: chạy lại vài cấu hình chính (ví dụ S1-W16, S1-W8, S1-W4) với timing thay đổi (đổi injection rate, đổi seed, hoặc đổi sang TimingSimpleCPU) và báo cáo độ lệch. Nếu độ lệch nhỏ so với chênh lệch giữa các cấu hình thì thứ hạng cấu hình đáng tin.

## 5.7. Chi phí chuyển trạng thái (ước lượng giải tích)

Khi tắt từ 16 xuống W way:
```text
T_flush ≈ N_dirty × t_writeback      (hoặc N_dirty × 64 B / băng thông ghi)
N_dirty ≈ số line dirty trong (16 − W) way bị tắt
```
- N_dirty ước lượng từ tỉ lệ dirty line trong L2 lúc chạy (lấy từ gem5 hoặc ước lượng theo tỉ lệ ghi của workload).
- Khi bật lại way: thêm khoảng (số line cần dùng lại) lần miss để nạp lại.
- Kết luận: way shutdown chỉ có lợi khi thời gian ở trạng thái tắt đủ dài để phần leakage tiết kiệm được lớn hơn năng lượng tiêu tốn cho flush và nạp lại.

## 5.8. Ước lượng leakage

- Chạy CACTI cho L2 (1 MiB, 16-way, 64 B, node công nghệ giả định) để lấy leakage của data array và tag array.
- Leakage tiết kiệm khi tắt (16 − W) way ≈ leakage data array × (16 − W) / 16.
- Giả định cần ghi rõ: tag array và mạch ngoại vi (decoder, sense amp) có thể không tắt được; transistor gating có overhead diện tích và leakage riêng.
- Kết quả gắn nhãn Estimated (ước lượng), không phải Measured.

## 5.9. Sản phẩm của P1

1. Bảng miss rate và MPKI theo W cho từng workload (Measured).
2. Đồ thị miss rate theo W, có spread qua seed, đánh dấu knee.
3. Bảng so sánh cùng dung lượng: tắt way và thiết kế nhỏ.
4. Bảng AMAT low/nominal/high theo W (Computed).
5. Ước lượng leakage tiết kiệm và chi phí chuyển trạng thái (Estimated).
6. Bảng số way tối thiểu cho từng workload theo ngưỡng 5.5, kèm trade-off W / miss / AMAT / leakage.
7. Danh sách giới hạn mô hình (mục 6).

## 5.10. Mốc và phụ thuộc

| Mốc | Nội dung | Phụ thuộc |
|---|---|---|
| M0 | Pin phiên bản gem5, smoke test | Cả nhóm |
| M1 | Baseline 4 core + L2 shared đã kiểm tra | Tiến Anh, Quyên |
| M2 | Generator đã kiểm tra | Ngọc |
| M3 | Sweep (1) + microbenchmark kiểm tra | Choi (runner, parser) |
| M4 | Sweep (2), (3) + kiểm tra ảnh hưởng timing | Choi |
| M5 | AMAT, leakage, giới hạn mô hình, kết luận P1 | Quyên, Ngọc (độ trễ) |

Việc làm được ngay khi chờ M1: chốt C_prod và replacement policy thật, hoàn thiện bảng 5.3, viết script microbenchmark ở bước 4, chạy thử CACTI.

---

# 6. Giới hạn mô hình

| Nhãn | Nội dung |
|---|---|
| Measured | Miss rate, MPKI, số writeback của L2 trong mô hình gem5 (điều kiện: đúng với interleaving đã mô phỏng) |
| Approximated | MinorCPU thay cho CVA6; synthetic traffic thay cho kernel vector thật; way shutdown mô hình bằng cache W-way ở trạng thái ổn định; tree-PLRU bị che nếu production dùng PLRU |
| Computed | AMAT, từ miss rate đo được và độ trễ giả định |
| Assumed | Dung lượng L2 production (1 MiB), độ trễ NoC và DRAM, node công nghệ cho CACTI |
| Estimated | Leakage tiết kiệm, chi phí chuyển trạng thái |
| Out of scope | Giới hạn MSHR (ảnh hưởng độ trễ và băng thông nhiều hơn số miss); cơ chế quyết định khi nào tắt/bật way; power-gating trong mô phỏng |

