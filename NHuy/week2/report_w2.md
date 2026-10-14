# Chốt các thông số production: dung lượng L2, replacement policy, inclusion policy
Vì đây là các thông số của sản phẩm đang thực hiện nên cần biết chính xác mới có thể tiếp tục các bước tiếp theo và trong phần description của project chưa đề cập đến. Và sau khi hỏi ý kiến thì có được các thông số như sau:
| # | Thông số | Giá trị| Lý do |
|---|---|---|---|
| 1 | Line size | 64 B |  |
| 2 | Số way | 16 | |
| 3 | Dung lượng | 1 MiB → 1024 set, alias stride 64 KiB | Bên baseline báo 1 MiB; L2 / tổng L1 = 1024 / 192 KiB ≈ 5.3 |
| 8 | Prefetcher L2 | Không | Tách riêng ảnh hưởng của số way |
| 9 | Granularity tắt way | Từng way (W = 1..16) | Điểm chính 16, 12, 8, 4, 2; phụ 14, 10, 6 |
| 10 | Độ trễ L2 | Giữ theo baseline | Không ảnh hưởng miss rate |
| 11 | MSHR L2 | 32, cố định | Từ Quyên |
| 12 | Clock, DRAM | 1 GHz, DDR4-2400 | Theo baseline |
| 13 | Node (chỉ khi cần năng lượng) | 22 nm, 85 °C | CVA6 (Ariane) từng tape-out trên GF 22FDX; CACTI hỗ trợ 22 nm |

- Tại sao lại có i-cache và d-cache?
  - Cơ bản là mọi CPU cần phải có L1 vì nếu không có L1 thì mọi lần lấy lệnh và đọc dữ liệu đều xuống thẳng L2 và đa phần là các lần lấy lệnh dễ (dùng lại ngay) dẫn đến việc đo miss rate L2 không còn ý nghĩa gì nữa. Khi có L1, L2 chỉ nhận những gì mà L1 không giữ được -> traffic mà việc tắt way sẽ tác động đến
  - CPU vừa thực hiện lấy lệnh và đọc dữ liệu trong cùng một chu kỳ nên MinorCPU có 2 cổng riêng là icache_port và dcache_port

# Workload sử dụng

- Workload sử dụng trong bài này và có phần dự đoán khi tắt way

| Workload | Thuật toán | Để làm gì? | Footprint (4 core) | Khi tắt way |
|---|---|---|---|---|
| loop | Quét mảng tuần tự, lặp lại 100 lần | Vòng lặp trên cùng một tập dữ liệu | 768 KiB | Vách đứng tại W12 (đã đo) |
| stream | `c[i] = a[i] + k*b[i]` trên 3 mảng lớn | Xử lý luồng dữ liệu, vector/DSP | 6 MiB | Miss ~100% ở mọi W |
| temporal | Đọc ngẫu nhiên, 90% vào vùng nóng nhỏ | Dữ liệu nóng được dùng thường xuyên | 512 KiB nóng + 4 MiB lạnh | Miss tăng mạnh khi W ≤ 8 |
| graph | Đi ngẫu nhiên trên đồ thị theo con trỏ | Duyệt cây, đồ thị, danh sách liên kết | 2 MiB | Miss tăng dần theo W |

- Thông số CPU_WIDTH = 1: mỗi tầng mỗi chu kỳ chỉ xử lý được 1 lệnh
```text
Chu kỳ:   1    2    3    4    5    6    7
I1:      Lấy  Mã   exc  Xong
I2:           Lấy  Mã   exc  Xong
I3:                Lấy  Mã   exc  Xong
I4:                     Lấy  Mã   exc  Xong
```
```text
Chu kỳ:      1    2    3    4    5    6    7
I1,I2:      Lấy  Mã   exc  Xong
I3,I4:           Lấy  Mã   exc  Xong
```
  - Vì sao chọn 1. CVA6 ở cấu hình mặc định là core single-issue: mỗi chu kỳ chỉ phát 1 lệnh. MinorCPU mặc định dùng width 2, nên phải hạ xuống 1 cho giống CVA6.
  - WIDTH đổi tốc độ core sinh ra request gửi xuống L2 -> thời gian và thứ tự bị thay đổi
- Thực chất thì việc chạy mô phỏng như này không phải một kiểu mô phỏng đa luồng như chạy 1 chương trình mỗi core sẽ thực hiện 1 phần của chương trình được cái đó cần chúng ta phải chia luồng ra. Ở đây chỉ mô phỏng việc 4 cores cùng khởi động 1 loop và dùng chung L2 cần khảo sát xem về việc lệnh tranh nhau chỗ trong L2 -> dẫn đến các thông số cần đo miss rate , .....

# Sweep chọn replacement policy
- LRU (Least Recently Used): đuổi line lâu nhất chưa được dùng
- Random (LFSR): chọn line ngẫu nhiên để đuổi ra
- Tree-PLRU (Pseudo-LRU dạng cây): xấp xỉ LRU bằng ít bit. LRU thật tốn nhiều bit và mỗi lần hit phải sửa nhiều bộ đếm. Tree-PLRU thay bằng một cây nhị phân có W − 1 bit (16 way thì 15 bit). Mỗi bit chỉ nhớ một điều: “nửa nào cũ hơn”
- NMRU(Not Most Recently Used): ngẫu nhiên, nhưng trừ line vừa dùng
- FIFO (first in first out): đuổi line vào cache sớm nhất
- Thực ra trong mỗi way = [ valid | dirty | tag | dữ liệu 64 byte ] thì tag chỉ giúp ta biết được nó đang trong set nào chứ không biết được vị trí chính xác của cái line. Do đó có tồn tại 1 ô (mỗi set một ô) ô đó thể hiện vị trí chính xác của line trong set đó. Và tuỳ vào thuật toán thì 'Số bit' nó có độ dài khác nhau.Ví dụ với LRU nó cần lưu chính xác thứ tự của cả 16 way nên bộ counter = 4 bit (từ 0->15) nên số bit = 16*4, còn với NMRU nó chỉ lưu vị trí chính xác của line vừa dùng gần nhất nên chỉ cần 4 bit không cần lưu cả 16 way nên là số bit = 4,.... còn LRU thì hoạt động bằng cách search theo binary tree
```text
vd:         b0
          /    \
        b1       b2
        /  \    /  \
      w0   w1  w2   w3
```
- Missrate = số lần miss ÷ số lần truy cập vào L2 × 100,MPKI = số lần miss ÷ số lệnh đã chạy × 1000, tức là cứ 1000 lệnh thì có bao nhiêu lần miss.
  - Missrate cho biết policy nào tốt hơn bao nhiêu % nhưng MPKI lại xem cái hơn đó có ảnh hưởng đáng kể đến hiệu năng hay không? Ta có thể tính chu kỳ chờ/1000 lệnh = miss penalty(tg chờ lệnh) * MPKI
  - Ta không thể dùng MissRate để đánh giá được lưu lượng và năng lượng của DRAM nhưng MPKI thì có thể. MPKI tăng thì năng lượng DRAM tốn hơn
- Bảng Missrate/MPKI:

| workload | LRU | TreePLRU | FIFO | NMRU | Random | LFSR |
|---|---|---|---|---|---|---|
| temporal | 10.12 / 0.469 | 11.13 / 0.516 | 16.86 / 0.781 | 16.39 / 0.760 | 17.06 / 0.791 | 17.03 / 0.789 |
| graph | 40.52 / 3.798 | 40.92 / 3.835 | 42.81 / 4.013 | 42.52 / 3.987 | 42.66 / 4.000 | 42.70 / 4.005 |
| stream | 100 | 100 | 100 | 99.83 | 99.78 | 99.73 |
| loop | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 |

-> Chọn Tree-PLRU làm replacement policy chính cho project này vì trade-off Missrate và phần cứng tốt nhất. Thay vì trong 16 ways lưu 64bit thì chỉ cần 15bit. Nhược điểm của nó là khi mà chọn đuổi line thì sẽ chọn random - đi theo các bit của tre tức là xấp xỉ LRU nên không đúng nhưng nó vẫn tốt hơn NMRU - chọn random thì bất kỳ thằng nào trong set đó nhưng PLRU thì khó mà đuổi line sử dụng gần đây do tổ chức PLRU theo binary tree (qua việc vẽ cây để hình dung). Với working set lớn hơn số way thì missrate gần như là 100%. Ví dụ vòng lặp 1 working set {A,B,C,D,E} liên tục và có 4 ways thì ban đầu miss hết sau đó nạp 4 line vào. Tiếp theo cần dùng E thì nó đuổi A ra nạp E vào. Nhưng tiếp theo lặp lại cần dùng A thì nó lại đuổi B ra và nạp A vào cứ tiếp tục như vậy dẫn đến việc Missrate 100%. Ngoài ra thì khi hit việc phải ghi lại cũng ảnh hướng. Ví dụ LRU Khi ta đuổi 1 line thì cần duyệt đến line đó đuổi ra rồi tiêp theo phải fix lại 4 counter trong 4 way -> tốn kém. Trong khi đó tree-PLRU chỉ cần truy cập 4 nút để thay đổi những nhánh liên quan đến line đó là xong
# Sweep chọn inclusion policy
- inclusive: mọi line trong L1 bắt buộc nằm trong L2 (khi L2 miss -> chép vào cả L2 và L1)
- non-inclusive: line có thể có ở cả hai hoặc chỉ ở một (khi L2 miss -> chép vào cả L2 và L1)
- exclusive: một line chỉ nằm ở một nơi (ở L1 hoặc L2) (khi L2 miss -> chỉ vào L1,L2 không giữ)
- Bảng tóm tắt

|Kiểu|	Quy tắc|	Khi L2 miss, line lấy từ DRAM về	|Khi L1 đuổi một line|
|---|---|---|---|
|Inclusive (bao hàm)	|Mọi line trong L1 bắt buộc có trong L2	|chép vào cả L2 và L1|	không cần gửi về L2 nếu line sạch, vì L2 đã có|
|Non-inclusive (NINE)|	Không ép gì: line có thể có ở cả hai, hoặc chỉ ở một	|chép vào cả L2 và L1|	gửi về L2 chỉ khi line dirty|
|Exclusive (loại trừ)|	Một line chỉ nằm ở một nơi: L1 hoặc L2	|chỉ vào L1, L2 không giữ|	gửi về L2 kể cả khi sạch. L2 hoạt động như “kho chứa line bị L1 đuổi” (victim cache)|

- Bảng số liệu từ gem5

| workload | L2 miss% nonincl / excl | MPKI nonincl / excl | cycles excl/nonincl | ghi L1->L2 nonincl / excl |
|---|---|---|---|---|
| graph | 40.52 / 39.74 | 3.798 / 3.725 (-1.9%) | 0.996 | 41k / 1.98M |
| temporal | 10.12 / 10.09 | 0.469 / 0.468 | 1.000 | 18.9k / 2.87M |
| stream | 100 / 100 | 5.342 / 5.341 | 1.000 | 370k / 894k |
| loop | 0.01 / 0.01 | ~0 | 1.000 | 1.22M / 1.22M (dirty migration từ vòng init) |

- Trong gem5 thực tế chỉ có 2 option về mục này là: mostly_incl (thực chất là non-inclusive) và mostly_excl (L1 sẽ bật writeback_clean=true để gửi line sạch về L2 kiểu như khi L1 đuổi thì L2 là chỗ nhận)
- Về dung lượng:
  - incl & non-incl: Dung lượng hiệu dụng ≈ dung lượng L2.
  - excl: = (tổng L1) + L2
- Với project này thì đề xuất nên sử dụng non-inclusive vì non-incl đơn giản hơn nhiều vì trong way shutdown line sạch thì bỏ đi line dirty thì ghi xuống DRAM nhiều line vẫn còn ở D1 nên mất mát ít hơn && so sánh thông số với exclusive ở các workload thì có thể thấy rõ là không chênh lệch nhiều nhưng ở phần ghi L1->L2 thì exclusive bị nhiều quá về số lần L1 gửi line xuống L2 như ở stream 370k/894k và với project quan tâm đến năng lượng như project này thì excl gần như không có cửa so ta đang cố gắng khảo sát shutdown way cho việc giảm leakage power nhưng excl mặc dù sẽ tăng way nhưng đồng thời năng lượng của nó cũng tăng theo dẫn đến hiện tượng bù trừ -> không có lợi ích
- Và tại sao excl có nhiều số lần ghi như vậy là vì khi line bị L1 đuổi,kể cả line sạch, đều phải ghi lại vào L2, vì L2 đã xóa bản sao khi chuyển line lên L1. Do đó mỗi lần L2 hit trở thành một vòng L2 → L1 → L2, tốn thêm một lần ghi L2 -> số lần ghi nó phình to ra
# Sweep ways shutdown
- Cụ thể trong lần nay ta sẽ khảo sát way shutdown với số set không đổi ở L2 để xem nó có thực sự giảm leakage power hay không?

- Bảng kết quả sweep với cấu hình 4 cores, LRU, non-incl, L2 1 MiB, loop

| W | C(W) | L2 miss % | MPKI | L1D miss lat (cyc) | cycles/W16 | L2 leakage (mJ) |
|---|---|---|---|---|---|---|
| 16 | 1024K | 0.04 | 0.002 | 12.0 | 1.000 | 13.84 (100%) |
| 14 | 896K | 0.05 | 0.002 | 12.0 | 1.000 | --- |
| 13 | 832K | 0.05 | 0.002 | 12.0 | 1.000 | --- |
| 12 | 768K | 23.7 | 0.989 | 24.2 | 1.040 | --- |
| 11 | 704K | 80.0 | 3.333 | 51.5 | 1.128 | --- |
| 10 | 640K | 100 | 4.169 | 61.3 | 1.159 | --- |
| 8 | 512K | 100 | 4.169 | 61.3 | 1.160 | 8.78 (63.4%) |
| 6 | 384K | 100 | 4.169 | 61.3 | 1.159 | --- |
| 4 | 256K | 100 | 4.169 | 61.2 | 1.160 | 5.38 (38.9%) |
| 2 | 128K | 100 | 4.169 | 61.2 | 1.159 | 3.85 (27.8%) |
| 1 | 64K | 100 | 4.169 | 61.3 | 1.159 | 2.95 (21.3%) |

- Bảng kết quả sweep với cấu hình 4 cores, LRU, non-incl, L2 1 MiB, stream

| W | C(W) | L2 miss % | MPKI | L1D miss lat (cyc) | cycles/W16 | L2 leakage (mJ) |
|---|---|---|---|---|---|---|
| 16 | 1024K | 100 | 5.209 | 96.7 | 1.000 | 10.07 (100%) |
| 8 | 512K | 100 | 5.210 | 96.8 | 1.000 | 5.51 (54.7%) |
| 4 | 256K | 100 | 5.209 | 96.6 | 1.000 | 3.38 (33.6%) |
| 2 | 128K | 100 | 5.210 | 96.6 | 0.998 | 2.41 (23.9%) |
| 1 | 64K | 100 | 5.210 | 96.3 | 0.997 | 1.85 (18.4%) |

- Kết quả cùng cấu hình trên nhưng replacement là Tree-PLRU, loop

| W | C(W) | L2 miss % | MPKI | L1D miss lat (cyc) | cycles/W16 | L2 leakage (mJ) |
|---|---|---|---|---|---|---|
| 16 | 1024K | 0.04 | 0.002 | 12.0 | 1.000 | 13.84 (100%) |
| 8 | 512K | 97.86 | 4.080 | 60.5 | 1.158 | 8.77 (63.4%) |
| 4 | 256K | 100 | 4.169 | 61.2 | 1.160 | 5.38 (38.9%) |
| 2 | 128K | 100 | 4.169 | 61.2 | 1.159 | 3.85 (27.8%) |
| 1 | 64K | --- | --- | --- | --- | --- |

- Note: 
  - Trong bảng sẽ có một số chỗ tính năng lượng bị khuyết là do McPAT chỉ chạy được với W=2^n thôi nên 14,12,10... thì không thể chạy với McPAT nếu muốn thì ta có thể dùng phương pháp nội suy từ các power đã có số liệu ở mức xấp xỉ
  - McPAT không mô hình bit trạng thái repl nên LRU và Tree-PLRU cùng leakage power; chênh lệch chỉ đến từ thời gian chạy

## Đánh giá kết quả
- Từ số liệu của sweep với LRU ta thấy là từ W13 trở đi thì missrate bắt đầu tăng mạnh (0.05 -> 23.7) và đến W10 thì thrash luôn. Lí do là vì tổng footprint là 4 core x 192KB = 768KB mà 1 W chứa 64KB nên giới hạn là ở W 768/64 = 12. Loop quét vòng 12 line mỗi set.Khi W < 12, LRU luôn đuổi đúng line sắp được dùng -> miss 100%. Nhưng ở W12 vừa đúng bằng footprint nhưng vẫn có MR=23.7, ngoài mảng dữ liệu L2 còn phải chứa code,stack và biên khác của 4 cores và không thể đảm bảo rằng các line chia đều tuyệt đối vào 1024 set dẫn đến sẽ có set nhiều hơn 12 line và bị thrash -> cần chừa ít nhất 1 way dư.
- Ở W13 có vẻ là điểm tối ưu khi mà missrate xấp xỉ với W14,16 nhưng leakage power có thể giảm (không có số liệu thật nhưng mà có thể suy ra). Do ở W13 thì footprint là 832KB > 768KB -> 3W bị tắt không chứa dữ liệu nào đang được dùng 
- Với Tree-PLRU thì ở mọi W không lệch với LRU nhiều ở mọi chỉ số -> có thể dùng để giảm chi phí phần cứng nên lúc ở trên phần repl có đề xuất sử dụng PLRU là đúng
- Còn ở workload stream, mỗi mảng = 512KB, mỗi core = 3 * 512 =1.5MB -> footprint = 4 core * 1.5 =6MB -> 6MB/64KB = 96 line/set >> 16. Quét tuần tự mỗi line dùng 1 lần -> MR = 100% ở mọi W 

## Kiểm chứng kết quả với dự đoán ở đầu ở 2 workload loop và stream
1. **Footprint khớp số đo**: loop ở W10 có 287 058 truy cập L2 mỗi core = 3 072 line × 93.4 lượt (100 lượt trừ phần nằm trong warmup)
2. **Đơn điệu theo W**: với LRU và số set cố định, miss rate không tăng khi tăng W. Bảng loop thỏa ở mọi điểm
3. **Tree-PLRU 2 way = LRU**: cây 2 way chỉ có 1 bit, chính là LRU thật. Số đo W2 của hai policy trùng nhau
4. **Miss chia đều 4 core**: loop W10 ~287k miss mỗi core, khớp với 4 core chạy cùng chương trình
-> ta hoàn toàn có thể dự đoán được missrate dựa trên dữ liệu cấu hình


- Đề xuất phương án cải tiến cho lần report kế tiếp:
  - Không tắt way khi working set nằm sát dung lượng còn lại. Như đã thấy, khi working set lớn hơn số way đang bật một chút (loop ở W8), Tree-PLRU cũng rơi xuống 100% miss như LRU, trong khi LFSR chỉ khoảng 60%. Cách xử lý là dùng chính MPKI làm tín hiệu: đếm miss trên mỗi khoảng N lệnh, nếu MPKI vượt ngưỡng thì bật lại way. Nhờ vậy, MPKI vừa là thước đo để chọn policy, vừa là tín hiệu điều khiển way shutdown lúc chạy
  - Thuật toán dynamic way shutdown để cái leakage power giảm nhưng vẫn giữ được hiệu năng miss rate thấp nhất có thể có. Tiếp tục đọc và nghiên cứu các công trình có sẵn đồng thời kiểm chứng lại qua gem5 và McPAT để tìm ra được phương án tối ưu nhất và phù hợp nhất
