**Cấu hình chung:**
- CPU thì lấy theo cấu hình của Tiến Anh
- shared L2: 1 MiB, 16 way, line 64 B, 1024 set, chia **4 bank** theo bit 14–15 của địa chỉ. Tree-PLRU, non-inclusive (`mostly_incl`).
- DDR4-2400, 1 GHz, warmup 10M chu kỳ.

**Workload:** tiled GEMM và conv int8

| Tên | Lệnh | Footprint 4 core |
|---|---|---|
| gemm256 | `gemm_int8 256` | 320 KiB (~5 way) |
| gemm768 | `gemm_int8 768` | 896 KiB (~14 way) |
| conv64 | `conv_int8 64` | ~185 KiB (~3 way) |
| conv256 | `conv_int8 256` | ~665 KiB (~11 way) |
| mixai | 2 core gemm768 + 2 core conv256 | ~780 KiB (~12 way) |

**Mốc so sánh:** 16 way luôn bật, không drowsy

**Năng lượng:** McPAT 22 nm tương tự với tuần 2
# Dynamic 
- L2 luôn có 16 way. Ta cho một controller chạy mỗi 1M chu kỳ và sẽ quyết định bật bao nhiêu way và vấn đề ở đây là cần biết được nếu chỉ bật W way thì L2 sẽ miss bao nhiêu? để chọn W nhỏ nhất mà chương trình chưa chậm quá 1%. Khó ở chỗ cache thật chỉ đang chạy ở một giá trị W. Nếu đang bật 4 way, thì chỉ thấy miss của 4 way, không biết 8 way sẽ ra sao. Muốn biết hết thì phải chạy 16 cache song song, quá tốn -> Cần ATD (Auxiliary Tag Directory) nó đơn giản mô phỏng 1 cache 16 way chạy LRU, chỉ chứa tag không chứa dữ liệu nó xem chuỗi truy cập L2 và không ảnh hưởng đến cache chính -> biết được miss ở mọi W way.
- Cache LRU có W way luôn giữ đúng W line dùng gần nhất của set, tức các vị trí 0 đến W−1 (do LRU). Vậy một truy cập ở vị trí p (có đúng p line khác được dùng gần đây) sẽ:
  - hit nếu cache có W-1 ≥ p way
  - miss nếu cache có W ≤ p way
- Sau khi có ATD rồi thì ta chọn W nhỏ nhất sai cho số miss tăng thêm không vượt ngưỡng cho phép (1%,2%,...): *miss_thêm(W) × tmem / 4 core ≤ smax × interval* . tmem = số chu kỳ trung bình mà miss L2 làm trễ thêm (chênh lệnh giữa việc lấy ở L2 và xuống DRAM lấy)
- Cuối cùng là quyết định bật và tắt way: chỉ tắt bớt way khi 3 khoảng (1 khoảng - 1000000 chu kỳ) liên tiếp cùng đồng ý và khi tắt 1 way thì phải ghi các line dirty trong way đó xuống bộ nhớ rồi xóa line. Và sẽ có các trường hợp tắt xuống W1 luôn nếu: dưới 1000 truy cập L2 mỗi khoảng, miss rate tăng thêm vẫn nằm trong ngưỡng
- Cần fix lại config gem5 sao cho Tree-PLRU rẽ sang nhánh còn way bật

`dyn` là tham số mặc định. `dyn idle0` là bản mà số way chỉ do ATD quyết định.

| Workload | Lần chạy | W trung bình | Số way theo thời gian | L2 miss % | L1D miss lat | Thời gian so với W16 |
|---|---|---|---|---|---|---|
| gemm256 | W16 | 16 | | 3,35 | 12,3 | — |
| | dyn | 3,00 | 16, 16, rồi W1 | 81,92 | 62,7 | **+0,98%** |
| gemm768 | W16 | 16 | | 1,48 | 12,4 | — |
| | dyn | 1,65 | 16, 16, 13, rồi W1 | 95,18 | 68,1 | **+1,06%** |
| | dyn idle0 | 5,34 | 16, 16, rồi **W5** | 68,42 | 50,2 | **+0,71%** |
| conv64 | W16 | 16 | | 5,39 | 12,6 | — |
| | dyn | 3,00 | 16, 16, rồi W1 | 42,55 | 33,5 | **+0,21%** |
| conv256 | W16 | 16 | | 1,18 | 12,1 | — |
| | dyn / dyn idle0 | 1,33 | 16, 16, rồi W1 | 97,09 | 65,3 | **+0,48%** |
| mixai | W16 | 16 | | 1,44 | 12,3 | — |
| | dyn | 1,33 | 16, 16, rồi W1 | 95,75 | 66,8 | **+0,48%** |
| | dyn idle0 | 1,63 | chủ yếu W1, có lúc W3 / W6 | 95,11 | 66,8 | **+0,48%** |

  - Missrate cao nhưng hãy xét đến thời gian so với W16 thì chỉ tăng 1.06%  ở gemm768 thì nếu tính ra thời gian mỗi miss thêm là 61/4=15.25 chu kỳ -> ra khoảng 45000 miss thêm trong cả lần chạy 64M chu kỳ. Nếu missrate = 95% thì tổng truy cập L2 khoảng 48000 tương đương 750 mỗi 1M chu kỳ -> 95% là một lượng truy cập rất nhỏ bị miss thôi

| - |L2 acc	|L2 miss|	miss %|
|---|---|---|---|
|W16	|52 274|	774	|1,48|
|dyn|	52 274	|49 755|	95,18|
  
  - Các kết quả khác cũng có thể giải thích tương tự như vậy
  - Cột quan tâm nhất là chính là chênh lệch thời gian so với W16 không lớn dẫn đến con số miss cao cũng không có ý nghĩa lắm

Leakage L2 của bản dynamic = Σ P_leak(W) × thời gian ở mỗi W. P_leak(W) lấy từ McPAT cho L2 4 bank, chỉ đổi cấu hình L2:

| W | 16 | 8 | 4 | 2 | 1 |
|---|---|---|---|---|---|
| P_leak L2 (W) | 0,1472 | 0,0799 | 0,0512 | 0,0342 | 0,0270 |

| Workload | Lần chạy | Leakage L2 mJ (giảm) | Phần còn lại mJ | Tổng mJ (giảm) | Chênh so với W16: core / DRAM, mJ |
|---|---|---|---|---|---|
| gemm256 | W16 | 2,232 | 29,179 | 31,411 | |
| | dyn | 0,653 (**−70,7%**) | 29,857 | 30,510 (**−2,87%**) | +0,11 / +0,51 |
| gemm768 | W16 | 9,480 | 124,002 | 133,482 | |
| | dyn | 2,101 (**−77,8%**) | 126,913 | 129,014 (**−3,35%**) | +0,49 / +2,14 |
| | dyn idle0 | 3,963 (−58,2%) | 126,437 | 130,400 (−2,31%) | +0,33 / +1,90 |
| conv64 | W16 | 2,254 | 28,945 | 31,199 | |
| | dyn | 0,654 (**−71,0%**) | 29,169 | 29,823 (**−4,41%**) | +0,02 / +0,18 |
| conv256 | W16 | 13,204 | 169,554 | 182,758 | |
| | dyn | 2,672 (**−79,8%**) | 171,672 | 174,344 (**−4,60%**) | +0,31 / +1,62 |
| mixai | W16 | 13,204 | 168,124 | 181,329 | |
| | dyn | 2,672 (**−79,8%**) | 171,575 | 174,247 (**−3,91%**) | +0,31 / +2,93 |

- Dynamic giảm 71–80% leakage L2, nhưng leakage L2 chỉ khoảng 7% chip và miss tăng làm DRAM, core tốn thêm, nên tổng chỉ giảm 2,9–4,6%.

# Drowsy
- Leakage current giảm rất mạnh khi hạ điện áp nguồn. Một ô SRAM vẫn có thể giữ được dữ liệu ở điện áp thấp hơn nhiều so với điện áp cần để đọc/ghi. Drowsy cache [https://web.eecs.umich.edu/~manowar/publications/drowsy-caches-ISCA2002.pdf]
- Trong paper có nói về việc awake tags và drowsy tags. Với awake thì mức điện áp luôn là 1V nhưng drowsy thì sẽ giảm xuống 0.3V -> leakage power giảm mạnh nhưng vẫn giữ được data trong đó. Với awake thì way sẽ bật liên tục không nghỉ -> leakage power cao -> lãng phí nhưng tốc độ nhanh còn drowsy vẫn sẽ giữ được tốc độ nhưng giảm leakage power đáng kể
- Tóm tắt lại như sau:
  - Vấn đề
    - L2 có 16 384 line nhưng tại mỗi thời điểm chỉ rất ít line được dùng, trong khi mọi line đều rò điện ở 1 V.
    Way shutdown cắt nguồn nên mất dữ liệu -> miss tăng -> DRAM tốn thêm. Ta cần giảm rò mà không mất dữ liệu.
    Ý tưởng: không cắt nguồn mà hạ điện áp. Ô SRAM ở 0,3 V vẫn giữ dữ liệu nhưng rò rất ít. Muốn đọc/ghi thì phải nâng lại 1 V.
  - Khó ở đâu
    - Cho line nào ngủ? Nếu dự đoán line sắp dùng thì tốn phần cứng -> chọn "simple" để khỏi phải dự đoán.
  - simple
    - Cứ hết window N chu kỳ (4000 hoặc 16000), mọi line chuyển sang drowsy, bất kể đang dùng hay không
    - Line được truy cập -> được đánh thức, thức đến hết window.
    - Dựa trên locality: line vừa dùng thì nhiều khả năng dùng lại sớm, line lâu không đụng thì ngủ cũng không sao. Chỉ cần một bộ đếm window chung
    
    |Thời điểm	|event|	status A	|Phạt|
    |---|---|---|---|
    |0	|Bắt đầu window 0|	ngủ	| |
    |100	|Truy cập A (hit)|	ngủ -> thức|	+wake_lat|
    |500	|Truy cập A|	thức|	0|
    |3900	|Truy cập A|	thức|	0|
    |4000	|Hết cửa sổ 0, mọi line ngủ lại|	ngủ	||
    |4200|	Truy cập A|	ngủ -> thức|	+wake_lat|
  - Trade-offs
    - Hit vào line ngủ: nâng áp mảng data -> chậm thêm wake_lat (1 hoặc 2 chu kỳ)
    - Miss, nạp line vào ô ngủ: việc nâng áp chạy song song với lúc chờ DRAM -> không phạt thêm
    - Tag luôn thức (bản "awake tags") -> biết hit/miss ngay, không phải đánh thức tag trước. Đổi lại, mảng tag vẫn rò đủ (đây là f_tag)
    - Tag và data truy cập song song: hit latency = max(tag 2, data 6 + wake), nên phạt cộng vào phía data. Vì vậy L1D miss latency tăng đúng bằng khoảng wake_lat. latency tăng khoảng = wake_lat * (tỉ lệ L1D miss là L2 hit)

| Workload | Lần chạy | L2 miss % | L1D miss lat | Thời gian so với W16 | a (line thức) | Hit vào line ngủ |
|---|---|---|---|---|---|---|
| gemm256 | w4000 | 3,35 (W16: 3,35) | 13,3 (12,3) | +0,002% | 0,020% | 25 038 |
| gemm768 | off (`window 0`) | 1,48 | 12,4 | 0 (trùng W16) | — | — |
| | w4000 | 1,71 (W16: 1,48) | 13,5 (12,4) | +0,006% | 0,020% | 103 302 |
| | w16000 | 1,71 | 13,5 | +0,006% | 0,08% | 103 301 |
| | w4000, wake 2 | 1,69 | 14,5 | +0,007% | 0,020% | — |
| conv64 | w4000 | 5,39 (5,39) | 13,5 (12,6) | −0,001% | 0,011% | 13 220 |
| conv256 | w4000 | 1,17 (1,18) | 13,1 (12,1) | +0,000% | 0,010% | 72 063 |
| mixai | w4000 | 1,50 (1,44) | 13,3 (12,3) | +0,002% | 0,012% | 87 677 |
  - Drowsy giữ nguyên miss L2 và chỉ chậm dưới 0,01%, vì phạt đánh thức chỉ 1–2 chu kỳ trên rất ít truy cập L2. Chỉ 0,01–0,02% line thức, và tăng cửa sổ gấp 4 không bớt được lần đánh thức nào, cho thấy L2 gần như không có tái sử dụng ngắn hạn. Mức tiết kiệm bị chặn ở khoảng 75,6% bởi phần tag luôn thức và hệ số rò r, không phải bởi chính sách ngủ

- Còn về phần đo leakage power thì không thể đo được bằng McPAT do McPAT không có cho phần đo cho Drowsy nên phần này cần phải tìm cách tự lập công thức tính toán. Em cũng đang tìm hiểu để ước lượng năng lượng một cách chính xác nhất
