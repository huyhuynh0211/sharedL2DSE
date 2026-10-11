# Huỳnh Ngọc Huy - HCMUS - Intern: L2 Cache & Way-Shutdown Specialist (P1)
# What
## Concept
* Target Hardware
```text
  Tile0: Core0 -> L1 Cache \
  Tile1: Core1 -> L1 Cache ->
                             ------> Crossbar/NoC -----> L2 Cache ------> Memory controller -----> DRAM
  Tile2: Core2 -> L1 Cache ->
  Tile3: Core3 -> L1 Cache /
```
* Cache
  * Là toàn bộ hệ thống nhớ SRAM tốc độ cao đặt sát CPU, lưu trữ tạm thời các khối dữ liệu thường dùng từ DRAM để CPU không phải chờ đợi lâu
  * Một cache lớn chia thành nhiều Banks. Mỗi Bank có cổng giải mã và đường đọc/ghi riêng --> Tăng hiệu suất nhờ parallelism, tránh bottleneck
  * Cache organization: Set-associative
  ```text
               | way0  | way1  | way2  | .....
      set0|      line0 | line1 | line2 | .....
      set1|      line3 | .....................
      set2|
      ....|
  ```
  * Các (set,way) sẽ là 1 cache line. Cache line có kích thước 64 bytes sẽ chứa 4 phần:
    * Valid bit: 1: có dữ liệu, 0:đang trống 
    * Dirty bit: 1: đã sửa, 0: chưa sửa
    * Tag: lưu các bit địa chỉ cao để nhận diện dữ liệu này thuộc địa chỉ nào của RAM
    * Data block: lưu dữ liệu lấy từ DRAM lên
  * Cache miss: CPU không tìm thấy lệnh trong cache. 4 loại miss: compulsory(chưa từng có trong cache), capacity (cache không đủ lớn để chứa tất cả dữ liệu), conflict (nhiều dữ liệu cùng một set), coherence (line bị invalidate vì core khác ghi vào cùng địa chỉ (nhiều core có private cache) )
  * Cache hit: CPU tìm thấy lệnh trong cache. Với điều kiện: đúng set, trùng Tag và valid bit = 1
  * Cache write:
    * Write-through: ghi cả cache và bộ nhớ, đơn giản, giữ nhất quán dễ, nhưng tốn băng thông. Thường đi kèm write buffer
    * Write-back: chỉ ghi cache, đặt dirty bit, khi bị đuổi mới ghi xuống. Tiết kiệm băng thông nhưng phức tạp hơn.
    * Khi ghi miss:
      * Write-allocate: nạp block vào cache rồi ghi (thường đi cùng write-back)
      * No-write-allocate: ghi thẳng xuống bộ nhớ (thường đi cùng write-through)
* NoC
  * Một chip (4 core RISCV) có nhiều khối -> nếu nối tất cả vào 1 bus -> bị tắc nghẽn -> Cần xây mạng trên chip (Router sao cho tối ưu có nhiều đường đi song song tăng hiệu suất của CPU và tránh bị tắc nghẽn, xung đột)
  * Tool: FlooNoC
* Workload
  * Là chương trình cùng dữ liệu đầu vào được chạy trên hệ thống để đánh giá. Với cache, các đặc trưng chính là footprint, kiểu truy cập, tỉ lệ đọc/ghi và locality
  * Workload tính toán đơn giản, các instruction ở gần nhau -> RAM load lên ít -> Way shutdown tiết kiệm power (mục tiêu trong project này)
  * Workload phức tạp hơn (recursive), liên tục load instruction lên, full cache thì lại đẩy xuống RAM rồi sau đó load lên lại vào cache
  * Synthetic traffic generator: sinh ra chuỗi địa chỉ có stride,footprint dùng để mô phỏng workload thực tế
    * Stride: bước nhảy. Stride=64B = duyệt tuần tự từng line
    * Footprint: tổng (line * 64B) mà workload chạm tới. Nếu footprint > L1 -> L1 miss -> Tràn xuống L2
## gem5
* Một tool dùng để mô phỏng, nó cho phép dựng lên 1 hệ thống gồm CPU,cache,bộ nhớ rồi sau đó chạy chương trình trên hệ thống đó để đo các số liệu (missrate,latency,...)
* Ví dụ: em đã thử chạy 1 chương trình đơn giản (hello world) thông qua gem5 thì sẽ thu được file stats.txt các thông số như simSeconds,*Misses,*Accesses,\*Hit,... -> ta sẽ dùng các thông số đó để tính ra các số liệu yêu cầu cho việc đánh giá hệ thống
* Trong project này ta sẽ sử dụng ISA:RISCV và CPU:MinorCPU: một mô hình CPU in-order (theo thứ tự) khác với O3CPU (mô hình CPU out-of-order)
  * MinorCPU:
    ```text
      load A miss ---- chờ 100ns ---- xong mới tới load B miss ---- chờ 100ns 
    ```
  * O3CPU: 
    ```text
      load A miss \
                   ------ chờ chung 100ns
      load B miss /
    ```
* gem5 có Standard Library - Cấu trúc module hóa 4 thành phần chính:
  * Board: bo mạch chủ kết nối toàn bộ hệ thống (ví dụ SimpleBoard, X86Board, RiscvBoard).
  * Processor: định nghĩa loại CPU, số nhân và tập lệnh ISA.
  * Memory: thiết lập phân vùng và chuẩn DRAM (Single/Dual Channel DDR3/DDR4, LPDDR).
  * CacheHierarchy: lớp phân cấp bộ nhớ đệm (NoCache, Classic PrivateL1PrivateL2, Ruby).
* Có 2 chế độ chạy là SE (syscall emulation: không cần OS) và FS (full system: boot cả OS vào để chạy). Trong thực tế thì sẽ ưu tiên FS hơn vì nó cho phép mô hình hoá chi tiết giữa OS & Hardware, device behavior & các tác động system-level -> cho kết quả sát thực tế hơn SE. Còn SE thì chỉ chạy workload thông qua syscall được gem5 simulate
## FlooNoC
* Các khối trên chip giao tiếp với nhau qua giao thức AXI (5 channel: AW, W, B, AR, R). FlooNoC là một NoC sinh ra để carry AXI4 transactions từ tile này sang tile khác
* Giả sử core ở tile (0,0) đọc 64 B từ memory controller ở tile (3,0):
    * Core phát AXI AR (yêu cầu đọc)
    * Chimney nguồn đóng AR vào một flit trên link req, ghi đích vào header
    * Flit đi qua các router theo từng hop. Mỗi router đọc header rồi chuyển flit sang đúng hướng
    * Chimney đích mở flit, đưa AR cho memory controller dưới dạng AXI transaction
    * Memory controller trả dữ liệu R. Chimney đích đóng từng beat vào flit (dữ liệu wide đi trên link wide) và gửi ngược về
    * Chimney nguồn nhận flit, kiểm tra thứ tự (có thể dùng RoB) rồi trả R cho core
# Why
## gem5
* Nghiên cứu cấp hệ thống: thay đổi một thành phần (kích thước L2, số core, kiểu CPU) ảnh hưởng đến cả hệ thống -> gem5 cho phép khảo sát các tương tác đó, ví dụ hệ đa lõi, hệ nhớ, trade off giữa các chỉ số hiệu năng
* Đánh giá hiệu năng: gem5 xuất ra rất nhiều thống kê (số chu kỳ, CPI, miss rate từng cache, băng thông bộ nhớ…) -> tính thời gian thực thi và tìm điểm nghẽn
* Khảo sát không gian thiết kế (Design Space Exploration): vì cấu hình bằng Python nên có thể sinh và chạy hàng loạt cấu hình (đổi cache, CPU, workload), thu thập thống kê rồi so sánh để chọn thiết kế phù hợp với mục tiêu
## FlooNoC
* Link rộng: gửi cả thông điệp (header + dữ liệu) trong một flit, xong trong một chu kỳ nếu không nghẽn. Cache line 64 B (512 bit) vừa một beat
* AXI4 đầy đủ: kể cả ATOP
* Tách rời: phần phức tạp ở chimney, router đơn giản -> nhờ đó mở rộng được nhiều core (phù hợp với project 4 cores hiện tại)
* Tách luồng: dữ liệu khối đi link wide, điều khiển đi link hẹp riêng để tránh bị chặn
* Module hóa: FlooGen ghép router, link, chimney thành topology theo yêu cầu. Ta dùng mesh nhỏ để thử vị trí L2 và memory controller, lấy số hop thật
# When
* Sử dụng các tool trên vào giai đoạn khảo sát trước khi chốt đặc tính hệ thống, khi sửa thiết kế còn rẻ. Sau khi chế tạo, sửa lỗi rất tốn kém, còn thử cấu hình trong mô phỏng chỉ tốn thời gian chạy. Đó là lí do tại sao trong quy trình chế tạo chip thì có rất nhiều bước simulation thà tốn thơi gian chạy chứ đã chốt để tape-out rồi thì khó sửa và có thể đánh đổi bằng rất nhiều tiền
* gem5: khi cần so sánh nhiều cấu hình (số way, dung lượng, associativity, workload) mà chưa có RTL. Không dùng để lấy công suất hay diện tích, và không thay được kiểm chứng RTL
* FlooNoC: dùng khi cần đo độ trễ và băng thông NoC trên RTL
* Có thể hình dung như này: gem5 sinh ra lưu lượng và FlooNoC nhận và xử lý lưu lượng đó (xem nó sẽ xử lý như thế nào)
# Who
* Kỹ sư kiến trúc máy tính/SoC: sẽ so sánh cấu hình của CPU,cache,bộ nhớ trước khi chốt đặc tính hệ thống
* Kỹ sư về bộ nhớ và cache: đánh giá missrate, misspenalty, replacement ,way shutdown với các loại DRAM khác
* Kỹ sư interconnect/NoC: đo độ trễ và băng thông qua FlooNoC
* Kỹ sư phân tích hiệu năng và công suất: các thống kê từ gem5 + tool phân tích năng lượng
* Researcher: các ý tưởng mới về mảng bộ nhớ/cache
# How
## Way shutdown: đo ảnh hưởng của việc giảm số way hoạt động của shared L2 (16 → 8 → 4 → 2) lên miss rate, từ đó tìm số way tối thiểu mà miss rate chưa tăng quá ngưỡng cho từng workload. Và quan trọng nhất là khảo sát xem liệu có thể power-gate các way khi workload nhẹ để giảm leakage power không?
Sử dụng tool gem5: giữ nguyên số set, giảm số way, nên dung lượng giảm theo (dung lượng = set × way × 64 B). Ví dụ với 1024 set: 16-way = 1 MB, 8-way = 512 KB, 4-way = 256 KB, 2-way = 128 KB. gem5 không mô phỏng power-gate thật (do gem5 không có phần power-gate cho từng way) -> chỉ xấp xỉ còn ước lượng leakage power thì dùng tool khác (theo em tìm hiểu thì có McPAT dùng để mô phỏng power maybe có thể kết hợp được với gem5 ở phần này(chưa test))

* Dựng baseline có cache: lần chạy hello world trước dùng hệ không có cache (NoCache), nên stats.txt chưa có thống kê L2. Và sau khi đổi sang cache hierarchy có private L1 và shared L2, 1 core MinorCPU RISC-V, L2 16-way, line 64 B. Chạy thử và kiểm tra stats.txt đã có accesses, misses, miss rate của L2 từ đó so sánh giữa 2 file stats.txt có thể thấy các thông số cpi,numberCycles,simSeconds giảm mạnh (vì đã lấy lệnh hit (cache read hit) ở L1) và các thông số liên quan đến mem_ctrl cũng vậy vì chỉ khi miss ở L2 mới xuống RAM lấy lệnh.
  * Các bước em đã thực hiện để chạy được gem5:
    * Viết file code C
    * Compile sang RISC-V (có dạng *.riscv)
    * Cấu hình cho hệ thống để chạy có thể chạy bằng file python và sử dụng các standard lib nên viết file cấu hình rất dễ (dùng Simpleboard)
    * Chạy SE với gem5 đã build trước đó (chạy đơn giản để test đọc thử file stats.txt)
* Kiểm tra cấu hình: kiểm tra xem cái mình cấu hình có giống với cái gem5 thực sự dựng không? tính số set, bit offset/index/tag cho từng cấu hình, rồi đối chiếu với kết quả của gem5 (không có trực tiếp trong file config.ini sẽ chứa thông số size,assoc để tính số set)
* Tham tham số hóa số way: thay đổi way 16 -> 8 -> 4 -> 2, giữ set cố định, dung lượng thay đổi theo way
* Dự đoán trước khi chạy: với mỗi workload (stride, footprint), tính số line khác nhau rơi vào mỗi set. Nếu số line mỗi set ≤ số way thì sau lượt đầu gần như không miss, nếu lớn hơn thì miss gần hết (xét LRU)
* Chạy và lưu lại: mỗi cấu hình × mỗi workload. Warm-up rồi mới reset stats để loại miss lần đầu (lấy lúc ổn định vì miss lần đầu không phục thuộc vào số way). Lấy L2 accesses, misses, miss rate, và lưu lại cấu hình cùng seed lí do cần chạy FS và có 1 folder riêng chứa tất cả để lưu lại cấu hình sau mỗi lần chạy
* So sánh với dự đoán: dùng python tính trước (ví dụ với LRU thì bằng cách so sánh số line mỗi set <> số way -> missrate chỉ có 2 mức là 0% hoặc xấp xỉ 100%), điểm khớp thì ghi nhận, điểm lệch thì tìm nguyên nhân (warm-up, replacement, prefetcher, mapping)
* Kết luận P1: lập bảng số way tối thiểu cho từng workload theo ngưỡng chấp nhận được. Chỗ này cần đánh giá trade-off cẩn thận về 3 thông số N way --- miss rate --- leakage power trong cùng 1 workload
