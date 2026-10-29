# Sửa lại mô hình sau góp ý tuần 3
Ở tuần 3, kết quả dynamic tắt xuống W1 mà chỉ chậm khoảng 1% và giảm 78% leakage L2 được nhận xét là không thực tế. Em kiểm tra lại thì thấy đúng là có vấn đề ở cả workload, controller lẫn cấu hình mô phỏng:
- Workload gần như không dùng tới L2. Với gemm768 ở W16, L1D miss rate chỉ có 0,075%, cả lần chạy 64M chu kỳ chỉ có 52 274 lần truy cập L2 (khoảng 0,8 lần mỗi 1000 chu kỳ) và DRAM chỉ chạy 1,2 MB/s. Nếu bỏ hẳn L2 thì thời gian tăng khoảng 51 500 × 49 / 4 core ≈ 1%, đúng bằng kết quả của dynamic ở W1. Nghĩa là thí nghiệm đó không phân biệt được chính sách nào tốt hơn. Nguyên nhân là M = 32 nên ma trận B chỉ được đọc 2 lần, cộng với việc int8 chạy vô hướng trên core 1-issue nên chương trình bị giới hạn bởi tính toán chứ không phải bộ nhớ
- Controller xuống W1 là do luật idle chứ không phải do ATD. ATD chỉ thấy khoảng 25 truy cập mẫu mỗi khoảng, nhân 32 ra khoảng 790, nhỏ hơn ngưỡng idle 1000 nên bị ép xuống W1. Ngưỡng miss thêm cho phép (656 lần mỗi khoảng) cũng lớn hơn cả tổng số truy cập L2, nên chọn W nào cũng qua
- tmem lúc chạy dùng 61, đây là độ trễ toàn phần chứ không phải phần phạt thêm (49). Đường từ L2 xuống DRAM thì đang để mặc định của gem5
- `mostly_incl` của gem5 chuyển line dirty lên L1 ở trạng thái Modified, nên B chỉ được đọc mà L1D vẫn có 51 466 lần writeback, gần bằng số truy cập demand
- Script đổi đơn vị theo 1 GHz cứng (`interval / 1e9`, latency chia 1000), và lúc tính năng lượng cho fixed W thì lại lấy leakage của L2 16 way

Và hướng anh Nam đưa ra là về lấy workload của repo github cva6 trích ra. Nhưng sau khi đọc thì em thấy nó cũng giống như các workload từng khảo sát trước đây và capicity của nó còn ít hơn. Hiện tại cũng chưa nhận được workload từ Khánh Ngọc nên em vẫn sẽ làm bằng workload của tuần 3

Ngoài ra em sửa thêm 2 lỗi trong phần tự thêm vào gem5: ATD chỉ cấp cứng 32 set mẫu (L2 nhiều hơn 1056 set là ghi 
tràn bộ nhớ), và drowsy đánh thức line cả khi gặp CleanEvict, trong khi CleanEvict chỉ đụng tới tag.


## Cấu hình sau khi sửa
Các thông số core lấy theo RTL `cv64a6_imafdc_sv39_wb`:

| Thông số | Tuần 3 | Tuần 4 | Lý do |
|---|---|---|---|
| Xung nhịp | 1 GHz | 100 MHz (chạy thêm 1 GHz để so) | Theo góp ý 50–100 MHz |
| Độ trễ | chu kỳ cứng | khai báo theo ns rồi đổi ra chu kỳ | L2 tag 2 ns / data 6 ns / resp 2 ns, NoC 2 ns. Ở 1 GHz thì trùng tuần 3 |
| NoC core → L2 | 16 B | 8 B | AXI data của CVA6 là 64 bit |
| L2 → DRAM | mặc định gem5 | 25 ns (giả định) | cộng thêm MemCtrl và DDR4 ra khoảng 70–80 ns |
| ALU / nhân / chia | 3 / 3 / 9 | 1 / 2 / 32 | CVA6 ALU 1 chu kỳ, mult 2, bộ chia tuần tự |
| Branch predictor | Tournament | BHT 128, BTB 32, RAS 2 | Theo RTL |
| Store buffer | 5 | 4 | `DEPTH_COMMIT = 4` |
| MSHR L1 | 1 | 8 | |
| Replacement L1 | LRU | LFSR | RTL chọn victim bằng LFSR |
| Vùng đo | warmup 10M chu kỳ | từ lúc cả 4 chương trình khởi tạo xong (`m5 work_begin`) | không đo phần khởi tạo |
| tmem | 61 (cứng) | đo bằng `tmem_calc.py` | |
| Luật idle | 1000 | tắt | để ATD tự quyết |

Những thứ giữ nguyên: L2 1 MiB, 16 way, 4 bank, Tree-PLRU, non-inclusive, MSHR L2 32, DDR4-2400, controller chạy mỗi 1M chu kỳ, k = 3, margin 1.

# Workload

| Tên | Lệnh | Footprint 4 core | Để làm gì? |
|---|---|---|---|
| vec192 | `vec_stream 192 400` | 768 KiB (12 way) | `y[i] += 3*x[i]` kiểu int64, rất ít lệnh trên mỗi byte nên traffic L2 cao, giống vector/DSP |
| gemm64 | `gemm_int8 768 64` | B 4 × 192 KiB, đọc lại 4 lần | GEMM int8 như tuần 3 nhưng M = 64 |
| conv256 | `conv_int8 256` | trọng số 4 × 144 KiB, đọc lại 4 lần | Như tuần 3 |
| mix | 2 core gemm64 + 2 core `vec_stream 192 900` | khoảng 780 KiB | luồng vector chen L2 với GEMM |

- vec_stream là workload mới thêm vào, vì GEMM và conv chạy vô hướng không tạo đủ traffic để L2 có ý nghĩa. Trong đề tài thì traffic vector/DSP cũng là phần cần xấp xỉ
- Mỗi chương trình gọi `m5 work_begin` ngay sau khi khởi tạo xong, đợi cả 4 core gọi xong thì mới bắt đầu đo

# Đo tmem
tmem là số chu kỳ mà một lần miss L2 làm core phải chờ thêm, tính bằng L1D miss latency khi mọi truy cập L2 đều miss trừ đi L1D miss latency khi mọi truy cập L2 đều hit. Trường hợp all-miss em chạy `vec_stream 4096` (4 × 4 MiB, lớn hơn L2 rất nhiều), còn all-hit chạy `vec_stream 64` (4 × 64 KiB, lớn hơn L1 nhưng nằm gọn trong L2).

| Clock | L1D miss lat all-miss | all-hit | tmem |
|---|---|---|---|
| 100 MHz | 15,5 | 5,1 | 10,4 chu kỳ (104 ns) |
| 1 GHz | 97,1 | 13,0 | 84,0 chu kỳ (84 ns) |

- Cùng một DRAM nhưng nếu tính theo chu kỳ thì ở 100 MHz một lần miss rẻ hơn khoảng 8 lần, nên tắt way ở 100 MHz ít tốn thời gian hơn nhiều so với ở 1 GHz
- Đổi ra ns thì 100 MHz lại dài hơn (104 so với 84 ns), vì mỗi tầng (NoC, L2, membus) tối thiểu cũng mất 1 chu kỳ = 10 ns nên độ trễ bị làm tròn lên

# Kết quả ở 100 MHz
Ở đây `fixed W` là L2 vẫn dựng 16 way nhưng chỉ bật W way trong cả lần chạy, giống với cách dynamic tắt way, để làm mốc kiểm tra controller. Cột thời gian là so với W16.

## vec192

| Lần chạy | W trung bình | L2 miss % | L1D miss lat | Thời gian |
|---|---|---|---|---|
| W16 | 16 | 0,01 | 5,2 | — |
| fixed W12 | 12 | 6,96 | 5,7 | +0,63% |
| fixed W8 | 8 | 84,22 | 14,1 | +13,81% |
| fixed W4 | 4 | 90,53 | 14,6 | +14,70% |
| dyn | 14,07 | 0,06 | 5,1 | −0,08% |

## gemm64

| Lần chạy | W trung bình | L2 miss % | L1D miss lat | Thời gian |
|---|---|---|---|---|
| W16 | 16 | 2,35 | 4,4 | — |
| fixed W12 | 12 | 20,17 | 6,4 | +0,02% |
| fixed W8 | 8 | 39,02 | 8,8 | +0,04% |
| fixed W4 | 4 | 57,88 | 10,6 | +0,05% |
| dyn | 1,21 | 81,82 | 13,3 | +0,07% |

## conv256

| Lần chạy | W trung bình | L2 miss % | L1D miss lat | Thời gian |
|---|---|---|---|---|
| W16 | 16 | 0,89 | 4,1 | — |
| fixed W12 | 12 | 3,45 | 4,3 | +0,00% |
| fixed W8 | 8 | 48,92 | 9,6 | +0,03% |
| fixed W4 | 4 | 79,57 | 12,9 | +0,05% |
| dyn | 1,31 | 83,06 | 13,1 | +0,05% |

## mix

| Lần chạy | W trung bình | L2 miss % | L1D miss lat | Thời gian |
|---|---|---|---|---|
| W16 | 16 | 0,02 | 4,7 | — |
| fixed W12 | 12 | 0,37 | 5,7 | +0,02% |
| fixed W8 | 8 | 1,14 | 8,0 | +0,07% |
| fixed W4 | 4 | 74,59 | 13,7 | +2,21% |
| dyn | 11,22 | 0,48 | 6,1 | +0,03% |

## Số way của dynamic theo thời gian
Mỗi khoảng là 1M chu kỳ:

| Workload | Số way | ATD dự đoán miss % (W16 / 13 / 12 / 11 / 10 / 8) |
|---|---|---|
| vec192 | 16, 16, rồi W14 đến hết (57 khoảng) | 0 / 0 / 11,8 / 77,3 / 90,2 / 90,7 |
| gemm64 | 16, 16, rồi W1 (140 khoảng) | 0,9 / 16,0 / 28,7 / 34,9 / 36,2 / 38,1 |
| conv256 | 16, 16, rồi W1 (95 khoảng) | 0 / 0 / 0 / 0 / 8,4 / 79,3 |
| mix | 16, 16, W12 (127 khoảng), W9 (3), W1 (10 khoảng cuối) | 0 / 0,1 / 0,3 / 0,6 / 11,5 / 58,2 |

## Đánh giá kết quả
- Với vec192, vách nằm giữa W12 và W11 (ATD báo W13 0%, W12 11,8%, W11 77,3%), khớp với dự đoán 768 KiB / 64 KiB = 12 way. Tắt qua vách thì chậm thật: ở W8 miss 84% và chậm 13,8%. Controller giữ W14 (tức W13 cộng margin 1) suốt lần chạy nên miss chỉ 0,06% và không chậm. Lần này controller quyết định dựa trên ATD chứ không bị luật idle ép xuống như tuần 3
- Với gemm64 và conv256, dynamic vẫn xuống W1, miss tăng lên 82–83% nhưng chỉ chậm 0,05–0,07%. Lần này thì không phải lỗi mà đúng theo ngưỡng:
  - gemm64 chỉ có 141 754 truy cập L2 trong 142M chu kỳ (khoảng 1 lần mỗi 1000 chu kỳ), conv256 còn ít hơn (50 371 lần trong 98M chu kỳ)
  - Ngưỡng miss thêm cho phép là 0,01 × 1 000 000 × 4 / 10,4 ≈ 3 846 lần mỗi khoảng, trong khi cả khoảng chỉ có khoảng 1 000 truy cập L2. Miss hết thì vẫn dưới 1%, nên tắt hết là hợp lý
  - Có thể hiểu là GEMM và conv chạy vô hướng trên CVA6 gần như không cần L2. Kết luận "tắt hết way" chỉ đúng với loại workload này, còn traffic kiểu vector thì không được tắt qua vách
- Với mix, lúc 2 core vec còn chạy thì controller giữ W12, khi vec chạy xong chỉ còn GEMM thì giảm xuống W9 rồi W1, tức là controller theo được pha của chương trình. Trong cả 4 workload không có lần nào phải bật thêm way (`ways_turned_on = 0`), nên nhánh bật lại way vẫn chưa được kiểm tra
- ATD (dùng LRU) dự đoán miss cao hơn L2 thật (dùng Tree-PLRU) ở tất cả các chỗ so sánh được:

| | ATD (LRU) | fixed (Tree-PLRU) đo được |
|---|---|---|
| vec192 W12 | 11,8% | 6,96% |
| gemm64 W12 | 28,7% | 20,17% |
| conv256 W8 | 79,3% | 48,92% |
| mix W8 | 58,2% | 1,14% |

  - Ở mix chênh lệch rất lớn: W8 thật chỉ miss 1,14% mà ATD báo 58%, nên controller giữ W12 trong khi W8 vẫn đủ. Em nghĩ nguyên nhân là Tree-PLRU ít khi đuổi line của vec (được dùng liên tục) mà hay đuổi line của GEMM (lâu lâu mới dùng lại), còn LRU thì cứ line nào cũ nhất là đuổi. Phần này em chưa kiểm chứng. Muốn chính xác hơn thì ATD phải mô phỏng đúng Tree-PLRU, hoặc bỏ margin 1
- So giữa fixed và dynamic thì thời gian và miss của dynamic đều nằm đúng khoảng giữa các điểm fixed tương ứng: vec dyn ở W14 gần như W16, còn mix dyn ở khoảng W11 thì nằm giữa fixed W12 và W8

# Ảnh hưởng của xung nhịp (vec192)

| Lần chạy | 100 MHz: miss % / thời gian | 1 GHz: miss % / thời gian |
|---|---|---|
| W16 | 0,01 / — | 0,01 / — |
| fixed W8 | 84,22 / +13,81% | 84,23 / +127,90% |
| dyn | 0,06 / −0,08% (W14) | 0,06 / −0,11% (W14) |

- Miss rate ở 2 clock gần như giống hệt nhau, vì nó do chuỗi địa chỉ quyết định. Nhưng cái giá của việc tắt sai thì khác nhau khoảng 10 lần: ở 1 GHz tắt xuống W8 làm thời gian chạy tăng hơn gấp đôi, vì mỗi lần miss tốn 84 chu kỳ thay vì 10
- Controller chọn W14 ở cả 2 clock vì ngưỡng đã được tính theo tmem đo được, nên không cần chỉnh tay. Tuy vậy xung nhịp thật của chip ảnh hưởng rất nhiều đến việc tắt way có đáng hay không

# Năng lượng
Trước khi vào số liệu thì cần nói rõ phần leakage giảm được là nhờ power gate. Tắt một way thực chất có hai bước. Bước logic là không cấp chỗ mới vào way đó nữa, ghi các line dirty xuống DRAM rồi xóa line. Bước vật lý là sleep transistor cắt nguồn mảng SRAM của way, lúc đó leakage của way gần như về 0 nhưng dữ liệu bên trong cũng mất theo. Vì vậy phải xả xong rồi mới được cắt nguồn, và controller ở trên chính là phần quyết định khi nào làm hai bước này.

Phần năng lượng vẫn dùng McPAT 22 nm như tuần 3. P_leak L2 theo W: W16 0,1472 / W8 0,0799 / W4 0,0512 / W2 0,0342 / W1 0,0270 W. Leakage của dynamic = Σ P_leak(W) × thời gian ở mỗi W, có cộng thêm năng lượng DRAM để ghi các line dirty khi tắt way.

| Workload | Lần chạy | Leakage L2 mJ (giảm) | Tổng mJ (giảm) |
|---|---|---|---|
| vec192 | W16 | 88,23 | 1 112,07 |
| | fixed W12 | 68,48 (−22,4%) | 1 193,14 (tăng 7,29%) |
| | fixed W8 | 54,49 (−38,2%) | 1 455,76 (tăng 30,91%) |
| | dyn | 78,42 (−11,1%) | 1 101,91 (−0,91%) |
| gemm64 | W16 | 209,56 | 2 643,82 |
| | dyn | 40,85 (−80,5%) | 2 494,44 (−5,65%) |
| conv256 | W16 | 144,14 | 1 812,44 |
| | dyn | 28,84 (−80,0%) | 1 706,98 (−5,82%) |
| mix | W16 | 209,56 | 2 640,49 |
| | fixed W4 | 74,47 (−64,5%) | 2 998,02 (tăng 13,54%) |
| | dyn | 152,58 (−27,2%) | 2 594,20 (−1,75%) |

- Năng lượng để ghi các line dirty khi tắt way rất nhỏ, chỉ 0,003–0,03 mJ (1 376–13 057 line)
- Với vec192, fixed W12 chỉ chậm 0,63% nhưng tổng năng lượng lại tăng 7,3%. Phần tăng nằm ở DRAM (503 lên 599 mJ), trong khi năng lượng đọc/ghi thật chỉ khoảng 1,2 mJ. Xem stats DRAMPower thì thấy:

| DRAM | W16 | fixed W12 |
|---|---|---|
| active background | 24,6 mJ | 317,9 mJ |
| precharge background | 374,3 mJ | 174,3 mJ |
| refresh | 104,1 mJ | 104,7 mJ |
| đọc + ghi + act + pre | ~0 | ~1,9 mJ |

  - Khi có traffic thì các bank hay ở trạng thái mở hàng (active standby), tốn hơn trạng thái đóng hàng. Cấu hình hiện tại chưa bật power-down của DRAM (năng lượng power-down đều bằng 0), nên phần năng lượng nền này có thể đang bị tính cao hơn thực tế
- Leakage L2 chỉ chiếm khoảng 8% tổng (88 trên 1 112 mJ ở vec192), còn DRAM chiếm khoảng 45%. Vì vậy chỉ cần tắt sai làm DRAM chạy nhiều hơn là mất hết phần tiết kiệm. Dynamic giữ được thời gian nên tổng năng lượng vẫn giảm được 0,9–5,8%
- Power gate cũng có cái giá của nó. Sleep transistor tốn thêm diện tích và làm truy cập chậm đi một chút. Khi bật lại way thì có dòng khởi động lớn và phải chờ điện áp ổn định, sau đó way còn rỗng nên có thêm một đợt miss lạnh. Từ đó ra điều kiện hòa vốn: way chỉ nên tắt khi thời gian nằm ở trạng thái tắt lớn hơn T_min = E_flush / P_way
  - Áp số vào: P_way ≈ (0,1472 − 0,0270) / 15 ≈ 8 mW, mỗi line ghi xuống DRAM tốn khoảng 2,4 nJ (0,0308 mJ / 13 057 line ở gemm64). Trường hợp xấu nhất một way có đủ 1024 line dirty thì E_flush ≈ 2,4 µJ, suy ra T_min ≈ 0,3 ms, tức khoảng 30 000 chu kỳ ở 100 MHz. Một way đã tắt thì ít nhất cũng phải nằm yên hết một khoảng của controller (1M chu kỳ) mới có thể được bật lại, lâu hơn T_min rất nhiều, nên điều kiện hòa vốn luôn thỏa. Có điều T_min này chưa tính năng lượng bật lại way
- P_leak(W) lấy từ McPAT bằng cách dựng lại mảng W way, nên đây là cận trên: chưa tính phần rò qua sleep transistor và năng lượng bật lại way. Tuần này controller không lần nào phải bật lại way nên phần năng lượng bật lại chưa ảnh hưởng tới kết quả

# Kết luận
- Sau khi sửa thì kết quả hợp lý hơn. Với workload có traffic L2 cao như vec192, tắt qua vách làm chậm 14% (ở 100 MHz) đến 128% (ở 1 GHz), và ở 100 MHz còn tốn thêm 31% tổng năng lượng. Dynamic giữ đúng W14 nên không chậm mà vẫn giảm được 11% leakage L2
- Workload vô hướng như GEMM và conv gần như không dùng L2, nên tắt xuống W1 vẫn đúng: leakage L2 giảm 80%, tổng năng lượng giảm khoảng 5,7%, chậm chưa tới 0,1%
- ATD dùng LRU hơi bảo thủ so với L2 dùng Tree-PLRU, rõ nhất là ở mix

# Giới hạn mô hình
- Phần số đo: miss rate, số truy cập và thời gian trong gem5. Phần giả định: xung nhịp 100 MHz, độ trễ L2/NoC theo ns, L2 xuống DRAM 25 ns, bộ chia 32 chu kỳ. Phần tính toán: leakage theo W (McPAT) và năng lượng flush
- gem5 classic chỉ cho một line size nên L1 phải dùng 64 B (RTL là 16 B), vì vậy số truy cập L2 khi đọc tuần tự thấp hơn chip thật tới 4 lần
- `mostly_incl` của gem5 chuyển line Modified lên L1 nên có writeback lặp lại; cache không giới hạn port/bank; SE mode không có TLB và cấp trang vật lý liên tục
- Tắt/bật way xảy ra tức thời, flush không tốn thời gian (chỉ cộng năng lượng vào sau)

# Việc tiếp theo và những điều cần hỏi
- Cho ATD mô phỏng Tree-PLRU (hoặc thử margin 0) rồi chạy lại mix
- Thêm workload có pha tăng nhu cầu (nghỉ rồi mới chạy vec) để kiểm tra nhánh bật lại way
- Cần xin thêm ý kiến từ anh Nam hiện tại em bị không biết nên làm gì tiếp
