#!/usr/bin/env python3
"""binv_model.py - Mô hình chức năng (trace-driven) L1D riêng + L2 chia sẻ, so sánh
L2 INCLUSIVE (có back-invalidation) với NON-INCLUSIVE (như gem5 classic mostly_incl).

Vì sao cần: gem5 classic không có L2 inclusive nghiêm ngặt, nên khi L2 đuổi một line,
L1 vẫn giữ bản sao -> không bao giờ có back-invalidation. Mô hình này sinh đúng chuỗi
địa chỉ của workload trong l2_workloads.cpp và chạy qua hai kiểu L2 để đo phần chênh.

Nhãn bằng chứng: COMPUTED (mô hình chức năng, không có timing). Độ tin cậy của mô hình
được kiểm bằng --validate: chạy cap/rand ở chế độ non-inclusive rồi so với số gem5 đo.

Giả định của mô hình:
  - L1D 32 KiB, 8 way, 64 set, thay thế ngẫu nhiên (ưu tiên way trống) như CVA6/gem5 RandomRP.
  - L2 1024 set x W way (tắt way giữ số set), LRU.
  - Non-inclusive: L1 miss -> L2 cấp line và giữ lại (mostly_incl); L2 đuổi line không
    đụng tới L1. Inclusive: L2 đuổi line -> xoá line đó khỏi mọi L1 (back-invalidation).
  - Line sạch bị L1 đuổi không ghi về L2 (writeback_clean = False). Bỏ qua dữ liệu dirty.
  - 4 core xen kẽ ngẫu nhiên từng truy cập (mô phỏng tốc độ tương đối dao động).
  - Trang vật lý 4 KiB cấp theo lần chạm đầu, 4 core memset song song (xen kẽ theo trang).
  - Không mô hình code, stack, L1I.

Dùng:
  python3 binv_model.py                      # bảng binv, inclusive vs non-inclusive theo W
  python3 binv_model.py --validate           # so cap/rand non-inclusive với gem5 (ways.csv)
  python3 binv_model.py --hot 16384 --csv out.csv
"""
import argparse
import csv
import random

LINE, PAGE = 64, 4096
L1_SETS, L1_WAYS = 64, 8
L2_SETS = 1024
HOT_BYTES, HOT_PER_COLD = 8 * 1024, 8          # giống kHotBytes, kHotPerCold trong .cpp
# Độ trễ (chu kỳ @100 MHz) chỉ dùng để quyết định core nào chạy trước; lấy từ gem5 đo:
# rand W16 miss L1D 8.9 chu kỳ (hit L2), mỗi miss L2 thêm ~16 chu kỳ. CPA = chu kỳ cho
# các lệnh không phải load giữa hai truy cập (vòng lặp -O2, ~4 lệnh, IPC ~0.5-0.7).
LAT_L1, LAT_L2, LAT_DRAM, CPA = 0, 9, 25, 4

# Số gem5 đo (results/100MHz/ways.csv, non-inclusive) để kiểm mô hình
GEM5_MISS = {
    "cap":  {16: 0.00, 14: 0.00, 13: 0.00, 12: 3.99, 11: 65.95, 10: 83.12, 8: 97.39, 6: 100.0, 4: 100.0, 2: 100.0},
    "rand": {16: 0.00, 14: 0.00, 13: 0.00, 12: 0.62, 11: 10.04, 10: 19.96, 8: 39.61, 6: 58.53, 4: 76.06, 2: 91.37},
}


def stream(mode, nbytes, rng, hot_bytes):
    """Chuỗi địa chỉ ảo (byte) của MỘT core, vô hạn, đúng như l2_workloads.cpp."""
    nbytes -= nbytes % LINE
    if mode == "cap":
        while True:
            for a in range(0, nbytes, LINE):
                yield a
    elif mode == "rand":
        n = nbytes // LINE
        while True:
            yield rng.randrange(n) * LINE
    elif mode == "binv":
        h = 0
        while True:
            for a in range(hot_bytes, nbytes, LINE):        # luồng lạnh
                yield a
                for _ in range(HOT_PER_COLD):               # vùng nóng, luôn ở L1
                    yield h
                    h = (h + LINE) % hot_bytes
    else:
        raise ValueError(mode)


def pass_len(mode, nbytes, hot_bytes):
    if mode == "binv":
        return (nbytes - hot_bytes) // LINE * (1 + HOT_PER_COLD)
    return nbytes // LINE


def page_table(ncores, nbytes, rng, gap):
    """Cấp trang vật lý theo lần chạm đầu khi 4 core memset song song.

    gap = xác suất có một trang "lạ" (code, stack, bảng trang, heap của tiến trình khác)
    chen vào giữa hai trang buffer. Không có gap thì mỗi set L2 nhận đúng 12 line và vách
    LRU thẳng đứng; gem5 thật có các trang chen này nên số line mỗi set không đều.
    Trả về (bảng trang, thứ tự memset)."""
    npages = (nbytes + PAGE - 1) // PAGE
    order = [(c, p) for p in range(npages) for c in range(ncores)]
    # tốc độ memset hơi khác nhau giữa core: xáo nhẹ trong từng cửa sổ 4 trang
    for i in range(0, len(order), ncores):
        win = order[i:i + ncores]
        rng.shuffle(win)
        order[i:i + ncores] = win
    pt, ppn = {}, 0x1000_0000 // PAGE
    for cp in order:
        while rng.random() < gap:
            ppn += 1
        pt[cp] = ppn
        ppn += 1
    return pt, order


def simulate(mode, ways, inclusive, ncores=4, nbytes=192 * 1024, hot_bytes=HOT_BYTES,
             warm_passes=2, meas_passes=3, seed=1, gap=0.0, timed=True, l1_lru=False):
    rng = random.Random(seed)
    pt, order = page_table(ncores, nbytes, rng, gap)
    gens = [stream(mode, nbytes, random.Random(seed * 100 + c), hot_bytes) for c in range(ncores)]
    l1 = [[[] for _ in range(L1_SETS)] for _ in range(ncores)]       # list line, <= 8
    l2 = [dict() for _ in range(L2_SETS)]                             # line -> tuổi (LRU)
    holders = {}                                                      # line -> tập core có trong L1
    clock = 0
    st = dict(l1_acc=0, l1_miss=0, hot_miss=0, l2_acc=0, l2_miss=0, backinv=0, backinv_hit_l1=0)
    plen = pass_len(mode, nbytes, hot_bytes)
    warm, total = warm_passes * plen * ncores, (warm_passes + meas_passes) * plen * ncores

    def access(c, va):
        nonlocal clock
        line = pt[(c, va // PAGE)] * (PAGE // LINE) + (va % PAGE) // LINE
        st["l1_acc"] += 1
        s1 = l1[c][line % L1_SETS]
        if line in s1:
            if l1_lru:                      # LRU: đưa line về cuối (mới dùng nhất)
                s1.remove(line)
                s1.append(line)
            return LAT_L1
        st["l1_miss"] += 1
        if mode == "binv" and va < hot_bytes:
            st["hot_miss"] += 1
        # ---- L2 ----
        st["l2_acc"] += 1
        clock += 1
        s2 = l2[line % L2_SETS]
        lat = LAT_L2
        if line in s2:
            s2[line] = clock
        else:
            lat = LAT_DRAM
            st["l2_miss"] += 1
            if len(s2) >= ways:
                victim = min(s2, key=s2.get)
                del s2[victim]
                if inclusive:
                    hs = holders.pop(victim, ())
                    if hs:
                        st["backinv"] += 1
                    for h in hs:
                        st["backinv_hit_l1"] += 1
                        l1[h][victim % L1_SETS].remove(victim)
            s2[line] = clock
        # ---- nạp L1, thay thế ngẫu nhiên ----
        if len(s1) >= L1_WAYS:
            ev = s1.pop(0 if l1_lru else rng.randrange(L1_WAYS))
            hs = holders.get(ev)
            if hs:
                hs.discard(c)
                if not hs:
                    del holders[ev]
        s1.append(line)
        holders.setdefault(line, set()).add(c)
        return lat

    # memset ban đầu: mọi core chạm toàn bộ buffer, xen kẽ theo trang (giống gem5)
    for c, p in order:
        for off in range(0, PAGE, LINE):
            if p * PAGE + off < nbytes:
                access(c, p * PAGE + off)
    now = [rng.random() for _ in range(ncores)]       # thời điểm (chu kỳ) mỗi core sẵn sàng
    for step in range(total):
        if step == warm:
            for k in st:
                st[k] = 0
        if timed:   # core nào tới lượt trước thì truy cập trước -> core hay hit chạy nhanh hơn
            c = min(range(ncores), key=now.__getitem__)
        else:
            c = rng.randrange(ncores)
        now[c] += CPA + access(c, next(gens[c])) * (1 + 0.1 * rng.random())

    div = lambda a, b: a / b if b else 0.0     # noqa: E731
    return dict(mode=mode, l1_repl="lru" if l1_lru else "random", ways=ways, l2_kib=ways * 64, policy="inclusive" if inclusive else "non-inclusive",
                l1_miss_pct=100 * div(st["l1_miss"], st["l1_acc"]),
                hot_miss=st["hot_miss"], l2_miss_pct=100 * div(st["l2_miss"], st["l2_acc"]),
                l2_mpka=1000 * div(st["l2_miss"], st["l1_acc"]),
                l1_miss=st["l1_miss"], l2_miss=st["l2_miss"], backinv=st["backinv"],
                backinv_l1_lines=st["backinv_hit_l1"])


WAYS = (16, 14, 13, 12, 11, 10, 8, 6, 4, 2)


def validate(seed):
    print("Kiểm mô hình: non-inclusive, so với gem5 (L2 miss %, results/100MHz/ways.csv)\n")
    print("| W | cap mô hình | cap gem5 | rand mô hình | rand gem5 |")
    print("|---|---|---|---|---|")
    for w in WAYS:
        cm = simulate("cap", w, False, seed=seed)["l2_miss_pct"]
        rm = simulate("rand", w, False, seed=seed)["l2_miss_pct"]
        print(f"| {w} | {cm:.2f} | {GEM5_MISS['cap'][w]:.2f} | {rm:.2f} | {GEM5_MISS['rand'][w]:.2f} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--hot", type=int, default=HOT_BYTES, help="byte vùng nóng mỗi core (mặc định 8192)")
    ap.add_argument("--footprint", type=int, default=192 * 1024, help="byte mỗi core (mặc định 196608)")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--l1-lru", action="store_true",
                    help="L1D dùng LRU thay cho random (để so: CVA6 RTL là pseudo-random)")
    ap.add_argument("--csv")
    a = ap.parse_args()
    if a.validate:
        validate(1)
        return
    rows = []
    for w in WAYS:
        for incl in (False, True):
            runs = [simulate("binv", w, incl, nbytes=a.footprint, hot_bytes=a.hot, seed=s,
                             l1_lru=a.l1_lru)
                    for s in range(1, a.seeds + 1)]
            r = dict(runs[0])
            for k in ("l1_miss_pct", "l2_miss_pct", "l2_mpka", "hot_miss", "l1_miss", "l2_miss",
                      "backinv", "backinv_l1_lines"):
                vals = [x[k] for x in runs]
                r[k] = sum(vals) / len(vals)
                if k in ("l2_miss_pct", "hot_miss"):
                    r[k + "_range"] = max(vals) - min(vals)
            rows.append(r)
    print(f"binv, 4 core x {a.footprint // 1024} KiB (vùng nóng {a.hot // 1024} KiB/core), "
          f"L1D {'LRU' if a.l1_lru else 'random'}, trung bình {a.seeds} seed. COMPUTED (mô hình chức năng).\n")
    print("| W | L2 | Chính sách | L1D miss (%) | Miss vùng nóng | L2 miss (%) | Truy cập DRAM / 1000 truy cập | Back-inv |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['ways']} | {r['l2_kib']} KiB | {r['policy']} | {r['l1_miss_pct']:.2f} | "
              f"{r['hot_miss']:.0f} | {r['l2_miss_pct']:.2f} | {r['l2_mpka']:.2f} | {r['backinv']:.0f} |")
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n[*] {a.csv}")


if __name__ == "__main__":
    main()
