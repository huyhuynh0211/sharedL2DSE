Đề tài của bạn là một bài toán kinh điển nhưng rất thực tế trong **Architectural Exploration** (Thăm dò kiến trúc vi mạch) trước khi bước vào giai đoạn RTL (viết Verilog/SystemVerilog). 

Để tiếp cận bài toán một cách bài bản từ góc nhìn kỹ sư thiết kế vi mạch (Microarchitecture/SoC Designer), dưới đây là phân tích chi tiết từng khái niệm khó, được chia theo 4 cụm kiến thức:

---

### Cụm 1: Mô hình hóa CPU & Bản chất luồng truy xuất bộ nhớ

#### 1. In-order vs. Out-of-Order (MinorCPU vs. O3CPU vs. CVA6)
* **Khái niệm:**
  * **In-order (Thứ tự):** CPU nạp, giải mã và thực thi lệnh theo đúng thứ tự viết trong chương trình. Nếu một lệnh bị trễ (ví dụ: chờ đọc dữ liệu từ RAM), toàn bộ pipeline đằng sau thường phải dừng lại (stall).
  * **Out-of-Order (O3 - Trái thứ tự):** CPU có thể tự đảo thứ tự thực thi của các lệnh độc lập để tận dụng chu kỳ nhàn rỗi trong khi chờ dữ liệu.
* **Tại sao lại dùng `MinorCPU` và nhắc đến `CVA6`?**
  * **CVA6** (tiền thân là Ariane) là một RISC-V core 64-bit in-order rất phổ biến trong giới thiết kế chip công nghiệp và học thuật.
  * Trong trình mô phỏng **gem5**:
    * `MinorCPU`: Là mô hình in-order pipeline 4 giai đoạn, mô phỏng hành vi rất sát với các core như CVA6.
    * `O3CPU`: Là mô hình out-of-order cực kỳ phức tạp.
  * Nếu dùng `O3CPU` để khảo sát L2, kết quả sẽ bị sai lệch vì CPU O3 "giấu" được độ trễ bộ nhớ tốt hơn rất nhiều so với chip in-order thực tế mà bạn định nhắm tới.

#### 2. Memory-Level Parallelism (MLP - Tính song song ở mức bộ nhớ)
* **Khái niệm:** Khả năng hệ thống có thể phát đi và duy trì **nhiều yêu cầu truy xuất bộ nhớ cùng một lúc** (concurrent/outstanding memory requests) đến L2 hoặc DRAM.
* **Ý nghĩa trong bài:** CPU Out-of-Order có MLP rất cao (nó liên tục quét tìm các lệnh load/store phía xa để ném vào hàng đợi). Trái lại, In-order CPU có MLP rất thấp (thường chỉ 1 hoặc một vài yêu cầu bay ra ngoài cùng lúc). Nếu dùng mô hình sai (O3), bạn sẽ vô tình đẩy MLP lên quá cao, làm L2 bị quá tải giả tạo hoặc che lấp hiện tượng nghẽn cổ chai thực tế của core in-order.

---

### Cụm 2: Kiến trúc Cache L2 & Kỹ thuật Thiết kế Vi mạch

#### 3. Shared L2 Cache (Cache L2 chia sẻ)
* **Khái niệm:** 4 core RISC-V mỗi core có L1 riêng (L1 Instruction, L1 Data), nhưng cùng truy xuất vào một khối Cache L2 chung duy nhất trước khi đi ra bộ nhớ ngoài (DRAM).
* **Vấn đề thiết kế:** L2 phải xử lý tranh chấp (contention) giữa 4 luồng dữ liệu khác nhau đổ dồn về cùng một cổng hoặc cùng một ngân hàng nhớ (bank).

#### 4. Hình học Cache (Cache Geometry): Line size & Associativity (Way)
* **Line size 64 Byte:** Đơn vị vận chuyển dữ liệu nhỏ nhất giữa L2 và DRAM. 
* **16-way Set-Associative:** Bộ nhớ cache được chia thành nhiều "Set" (tập hợp). Mỗi Set chứa 16 "Way" (16 vị trí để chứa line dữ liệu). Khi một địa chỉ ánh xạ vào một Set, nó có thể nằm ở bất kỳ way nào trong 16 way đó.
* **Dung lượng (Capacity):** $Capacity = Num\_Sets \times Associativity (Ways) \times Line\_Size$.

#### 5. Way Shutdown (Kỹ thuật P1)
* **Khái niệm:** Kỹ thuật quản trị năng lượng trong thiết kế vi mạch (Low-power design). Ở mức mạch vật lý, các khối SRAM của cache tiêu tốn rất nhiều năng lượng rò rỉ (static/leakage power). 
* **Cơ chế:** Khi chip chạy các tác vụ nhẹ, phần cứng hoặc firmware có thể **tắt nguồn (power-gate) một số way** (ví dụ: từ 16 way hạ xuống chạy 8 way hoặc 4 way). 
* **Mục tiêu khảo sát:** Khi bạn tắt bớt way (giảm dung lượng hiệu dụng và giảm độ liên kết), **Miss rate sẽ tăng lên bao nhiêu?** Đề tài muốn bạn quét số way hoạt động (ví dụ: 2, 4, 8, 12, 16 ways) để tìm điểm cân bằng giữa năng lượng tiết kiệm được và hiệu năng bị suy giảm.

#### 6. MSHR (Miss Status Holding Register)
* **Khái niệm:** Khi một truy xuất L2 bị "trượt" (cache miss) và phải đi tìm dữ liệu ở DRAM, cache không thể đứng chờ (nếu là Non-blocking Cache). Nó cần các thanh ghi phần cứng gọi là **MSHR** để lưu lại trạng thái: *"Ai đã yêu cầu? Đang chờ block địa chỉ nào? Khi DRAM trả về thì trả cho ai?"*.
* **Tại sao "nằm ngoài phạm vi mô phỏng"?** Số lượng thanh ghi MSHR giới hạn số lượng miss đang chờ xử lý đồng thời. Bằng cách cố định hoặc bỏ qua tắc nghẽn MSHR, bạn cô lập bài toán: kết quả trượt hay trúng chỉ hoàn toàn phụ thuộc vào **cấu trúc cache** (dung lượng, way) chứ không bị nhiễu bởi hàng đợi MSHR bị đầy.

---

### Cụm 3: Mô hình hóa Tải (Traffic Modeling)

#### 7. Synthetic Traffic Generator (Bộ sinh lưu lượng tổng hợp)
* **Khái niệm:** Thay vì biên dịch cả một hệ điều hành Linux và chạy phần mềm benchmark thật (rất tốn thời gian mô phỏng, có thể mất hàng ngày trên gem5), người ta dùng một khối phần cứng ảo chuyên tạo ra các chuỗi địa chỉ đọc/ghi (Read/Write trace) theo quy luật định sẵn.
* **Vector / DSP Traffic:** Các thuật toán xử lý tín hiệu số (DSP) hay tính toán vector (AI/Matrix) thường không truy xuất ngẫu nhiên mà truy xuất theo mảng dữ liệu cực lớn, liên tục hoặc cách đều.

#### 8. Stride & Memory Footprint
* **Footprint (Dấu chân bộ nhớ):** Tổng kích thước vùng nhớ mà chương trình truy quét qua (ví dụ: mảng dữ liệu 2MB, 8MB hay 64MB). So sánh Footprint với dung lượng L2 sẽ thấy ngay tính trượt: nếu Footprint >> L2 Size, miss rate sẽ vọt lên.
* **Stride (Bước nhảy địa chỉ):** Khoảng cách giữa hai lần truy xuất liên tiếp. 
  * *Stride = 1 (hoặc nhỏ hơn 64B):* Rất thân thiện với cache, nạp 1 line 64B dùng được nhiều lần (tận dụng Spatial Locality).
  * *Stride lớn (ví dụ bước nhảy 1024B):* Cứ mỗi lệnh đọc lại trượt vào một line mới, làm cache nhanh chóng bị "ô nhiễm" và trượt liên tục.

---

### Cụm 4: Số đo & Đánh giá Hiệu năng

#### 9. Miss Rate (Tỷ lệ trượt) vs. AMAT (Average Memory Access Time)
Đây là hai đầu ra quan trọng nhất của bài:

* **Miss Rate ($MR$):**
  $$MR = \frac{\text{Số lần Miss}}{\text{Tổng số truy xuất}}$$
  * Đây là **số đo trực tiếp và tin cậy tuyệt đối** từ simulator: Với một chuỗi địa chỉ cố định chạy qua một cấu hình Cache (Size, Way, Line), thuật toán thay thế (LRU) sẽ cho ra số lần Hit/Miss chính xác 100% về mặt toán học.

* **AMAT (Thời gian truy xuất bộ nhớ trung bình):**
  $$AMAT = \text{Hit Time}_{L2} + MR_{L2} \times \text{Miss Penalty}_{L2}$$
  * Trong đó: $\text{Miss Penalty}_{L2} = \text{Latency}_{NoC} + \text{Latency}_{DRAM}$.
  * Đây là **giá trị tính toán/ước lượng theo mô hình**: $\text{Hit Time}$, độ trễ mạng nội chip (NoC - Network-on-Chip) và độ trễ DRAM là các con số bạn **giả định** (ví dụ: L2 Hit = 8 cycles, NoC = 10 cycles, DRAM = 50ns/150 cycles). 

---

### Tóm tắt bức tranh toàn cảnh bài toán của bạn:
Bạn đang dùng một công cụ mô phỏng kiến trúc (**gem5**) chạy 4 core CPU loại đơn giản (**MinorCPU / RISC-V in-order**) nhằm tái hiện chuẩn xác năng lực phát lệnh của lõi như **CVA6**. Bạn bơm vào hệ thống một luồng tải giả lập tính chất của chip xử lý ma trận/DSP (**Synthetic traffic** với **Stride/Footprint** xác định). 

Sau đó, bạn "thử nghiệm" L2 cache bằng cách:
1. Thử tắt dần các Way (từ 16 $\rightarrow$ 8 $\rightarrow$ 4 $\rightarrow$ 2) xem Miss Rate tăng phi mã ở mốc nào để làm tính năng **Way Shutdown**.
2. Thử thay đổi dung lượng tổng và Associativity.
3. Thu thập **Miss rate** (số liệu chính xác từ kiến trúc cache) rồi nhân với các **thông số trễ giả định** (NoC, DRAM) để tính ra **AMAT**. Cuối cùng viết báo cáo tách bạch rõ: cái gì là **đo đạc**, cái gì là **giả lập xấp xỉ**, cái gì là **công thức tính tay**.

# Bộ Công Cụ (Toolchain) Khảo Sát Không Gian Thiết Kế L2 Chia Sẻ Bằng gem5

Tài liệu này đặc tả toàn bộ ngăn xếp công nghệ (tech stack), công cụ phụ trợ và các mô hình toán học giải tích phục vụ quá trình Thăm dò Không gian Thiết kế (Design Space Exploration - DSE) cho hệ thống Cache L2 dùng chung trên vi kiến trúc 4 lõi RISC-V in-order.

---

## 1. Nền tảng hệ điều hành & Môi trường lập trình (Base Environment)

* **Hệ điều hành:** `Ubuntu Linux` (khuyến nghị phiên bản 22.04 LTS hoặc 24.04 LTS).
  * Mô phỏng kiến trúc trên gem5 chạy ổn định và tối ưu nhất trên môi trường Linux gốc.
  * Nếu dùng Windows, bắt buộc sử dụng **WSL2 (Ubuntu)** hoặc thiết lập Dual-boot.
* **SCons & Trình biên dịch (GCC/Clang):**
  * `SCons`: Hệ thống xây dựng (build system) nền tảng của gem5.
  * `gcc / g++` (phiên bản $\ge 11$) hoặc `clang`: Dùng để biên dịch mã nguồn C++ của simulator.
* **Môi trường phát triển tích hợp (IDE):**
  * **VS Code** với các tiện ích mở rộng khuyến nghị:
    * *Remote - WSL* / *Remote - SSH* (nếu chạy máy chủ từ xa).
    * *Python* & *Pylance*.
    * *C/C++* & *CMake Tools*.
    * *GitLens* (quản lý phiên bản mã nguồn).

---

## 2. Trái tim mô phỏng: gem5 Simulator

* **Mục tiêu biên dịch:** Kiến trúc RISC-V:
  ```bash
  scons build/RISCV/gem5.opt -j$(nproc)   # Dùng để debug và thử nghiệm
  scons build/RISCV/gem5.fast -j$(nproc)  # Dùng khi chạy quét tham số hàng loạt
  ```
  * `gem5.opt`: Giữ lại biểu tượng debug và assert, thích hợp cho giai đoạn dựng khung mô hình.
  * `gem5.fast`: Tối ưu hóa hiệu năng biên dịch, tắt toàn bộ assert và log debug nhằm tăng tốc độ mô phỏng khi chạy quét DSE.
* **Ngôn ngữ lõi:**
  * **Python 3:** Sử dụng API cấu hình của gem5 (`SimObject`) để kết nối các khối: 4 lõi `MinorCPU`, các cụm L1 độc lập, L2 Cache chia sẻ, Crossbar và Memory Controller.
  * **C++:** Đọc và tùy biến trực tiếp logic của hệ thống bộ nhớ (`src/mem/cache/`) nếu cần can thiệp thuật toán quản lý way (Way Shutdown / Dynamic Way Partitioning).

---

## 3. Công cụ sinh lưu lượng tải: gem5 TrafficGen

Nhằm xấp xỉ luồng truy xuất của các nhân tính toán Vector/DSP mà không tốn chi phí chạy toàn bộ hệ điều hành hay mã nhị phân phức tạp:

* **Công cụ sử dụng:** `gem5 TrafficGen` (kết hợp `PyTrafficGen`).
* **Cơ chế hoạt động:**
  * Bộ sinh tải hoạt động dựa trên đồ hình trạng thái (State Machine) hoặc cấu hình tham số.
  * Cho phép thiết lập luồng truy xuất bộ nhớ với **Bước nhảy (Stride)** cố định và giới hạn trong **Vùng nhớ truy xuất (Footprint)** xác định.
* **Công cụ phụ trợ (Tùy chọn):** `riscv64-unknown-elf-gcc` (RISC-V GNU Toolchain) để biên dịch các microbenchmark C/Assembly trần (bare-metal) nếu cần kiểm chứng tính đúng đắn trước khi bơm tải nhân tạo.

---

## 4. Tự động hóa quét không gian thiết kế (DSE Automation)

Không gian thăm dò bao gồm nhiều chiều: Số way hoạt động $\times$ Dung lượng $\times$ Độ kết hợp $\times$ Đặc trưng tải. Quá trình này bắt buộc phải tự động hóa:

* **Script điều khiển:** Viết bằng `Python` (`subprocess`, `argparse`) hoặc `Bash script` lồng các vòng lặp tham số:
  * Vòng lặp 1: Số active ways ($W \in \{2, 4, 8, 12, 16\}$).
  * Vòng lặp 2: Dung lượng Cache ($\text{Size} \in \{512\text{ KB}, 1\text{ MB}, 2\text{ MB}, 4\text{ MB}\}$).
  * Vòng lặp 3: Độ kết hợp (Associativity).
* **Quản lý tiến trình song song:** **`GNU Parallel`**
  * Tận dụng toàn bộ tài nguyên đa luồng của máy chủ mô phỏng:
  ```bash
  parallel -j $(nproc) python3 run_dse.py --way {1} --size {2} ::: 2 4 8 16 ::: 512kB 1MB 2MB
  ```

---

## 5. Trích xuất dữ liệu & Mô hình hóa giải tích AMAT

Mỗi kịch bản mô phỏng sinh ra một tập tin thống kê `stats.txt` (hoặc `stats.json`).

* **Trích xuất dữ liệu:** Sử dụng `Python` với thư viện `re` (Regex) hoặc `json` để bóc tách:
  * Số lượt truy xuất: `system.l2.overallAccesses::total`
  * Số lượt trượt: `system.l2.overallMisses::total`
  * Tỷ lệ trượt đo đạc: `system.l2.overallMissRate::total`
* **Cấu trúc lưu trữ:** Tổ chức kết quả bằng `Pandas DataFrame`.
* **Mô hình tính toán giải tích:**
  
  Dung lượng cache được xác định bởi hình học phần cứng:
  $$\text{Capacity} = N_{\text{sets}} \times \text{Associativity} \times \text{Line\_Size}$$

  Tỷ lệ trượt (kết quả đo đạc từ vết địa chỉ thực nghiệm):
  $$\text{Miss Rate}_{\text{L2}} = \frac{N_{\text{miss\_L2}}}{N_{\text{access\_L2}}}$$

  Thời gian truy xuất bộ nhớ trung bình (AMAT) dựa trên giả định độ trễ:
  $$\text{AMAT} = T_{\text{hit\_L2}} + \text{Miss Rate}_{\text{L2}} \times \left( T_{\text{NoC}} + T_{\text{DRAM}} \right)$$

  *Trong đó:*
  * $T_{\text{hit\_L2}}$: Thời gian trúng L2 (chu kỳ).
  * $T_{\text{NoC}}$: Độ trễ ước lượng qua mạng kết nối nội chip (chu kỳ).
  * $T_{\text{DRAM}}$: Độ trễ truy xuất bộ nhớ ngoài DRAM (chu kỳ hoặc ns).

---

## 6. Trực quan hóa dữ liệu & Soạn thảo báo cáo

* **Jupyter Notebook:** Môi trường tương tác để viết mã phân tích số liệu và hiển thị kết quả.
* **Matplotlib & Seaborn:** Xuất đồ thị chất lượng cao phục vụ báo cáo kỹ thuật:
  * *Line Plot:* Minh họa tương quan giữa $\text{Miss Rate}$ và số lượng active ways (xác định điểm gãy hiệu năng phục vụ Way Shutdown).
  * *Heatmap:* Biểu diễn $\text{AMAT}$ theo lưới ma trận (Dung lượng $\times$ Associativity).
* **Báo cáo kỹ thuật:** Định dạng bảng biểu bằng **LaTeX** hoặc xuất trực tiếp từ Pandas (`df.to_latex()`).

---

## 7. Bảng tổng hợp luồng công việc (Workflow Matrix)

| Giai đoạn | Công cụ chính | Nhiệm vụ kỹ thuật | Bản chất dữ liệu |
| :--- | :--- | :--- | :--- |
| **1. Mô hình hóa kiến trúc** | `gem5`, Python API | Cấu hình 4 lõi MinorCPU, cụm cache, bus kết nối | Thiết lập tham số phần cứng |
| **2. Kích thích tải** | `TrafficGen` | Phát sinh chuỗi truy xuất với Stride và Footprint | Xấp xỉ luồng tải thực tế |
| **3. Tự động hóa quét DSE** | `Bash`, `Python`, `GNU Parallel` | Thực thi hàng loạt kịch bản Size / Way song song | Tự động hóa tiến trình |
| **4. Bóc tách dữ liệu** | `Python` (`re`, `json`, `pandas`) | Trích xuất `stats.txt`, thu thập giá trị Miss Rate | **Số đo thực nghiệm** |
| **5. Tính toán hiệu năng** | `NumPy`, `Pandas` | Áp dụng công thức AMAT với giả định trễ NoC/DRAM | **Ước lượng giải tích** |
| **6. Trực quan hóa** | `Matplotlib`, `Seaborn` | Xuất đồ thị đánh giá trade-off (Năng lượng - Hiệu năng)| Trình bày trực quan |
```
