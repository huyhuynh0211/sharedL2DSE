import argparse
import csv
import glob
import os
import re
import subprocess
import sys
from collections import OrderedDict

LINE = 64                 
L1_SETS, L1_WAYS = 64, 8  
L2_SETS = 1024            
MAXW = 16                 
BIN = "./l2traffic/l2traffic_native"


#mô hình cache
class Cache:
    """Cache set-associative, LRU thật. Mỗi set là OrderedDict: đầu = cũ nhất, cuối = mới nhất."""

    def __init__(self, sets, ways):
        self.sets, self.ways = sets, ways
        self.data = [OrderedDict() for _ in range(sets)]

    def access(self, addr):
        """Trả True nếu hit, False nếu miss."""
        line = addr // LINE
        s = self.data[line % self.sets]
        if line in s:                   
            s.move_to_end(line)
            return True
        if len(s) >= self.ways:          
            s.popitem(last=False)
        s[line] = True                   
        return False


class CacheTick:
    """LRU cài theo kiểu gem5 LRURP: mỗi line lưu thời điểm chạm gần nhất; đuổi line có tick nhỏ nhất.
    Chỉ dùng để kiểm tra rằng Cache (OrderedDict) cho đúng kết quả như LRURP."""

    def __init__(self, sets, ways):
        self.sets, self.ways, self.t = sets, ways, 0
        self.data = [dict() for _ in range(sets)]      

    def access(self, addr):
        self.t += 1
        line = addr // LINE
        s = self.data[line % self.sets]
        if line in s:
            s[line] = self.t
            return True
        if len(s) >= self.ways:
            del s[min(s, key=s.get)]                 
        s[line] = self.t
        return False


#  chuỗi địa chỉ
def read_trace(path):
    """Đọc file trace do `l2traffic_native ... dump=N > file.csv` tạo ra."""
    addrs = []
    with open(path) as f:
        for ln in f:
            if ln and ln[0] != "#" and "," in ln:
                addrs.append(int(ln.split(",")[0]))
    return addrs


def gen_trace(args, n):
    """Gọi trực tiếp bản native để lấy n truy cập đầu tiên (offset)."""
    out = subprocess.run([BIN, *args.split(), f"dump={n}"],
                         capture_output=True, text=True, check=True).stdout
    for ln in out.splitlines():
        if ln and ln[0] != "#":
            yield int(ln.split(",")[0])


# oracle v1: mô phỏng trực tiếp
def run(addrs, l2_ways, warmup, cache_cls=Cache):
    """L1D -> L2 với W way. Trả (số truy cập, L1 miss, L2 truy cập, L2 miss), bỏ `warmup` truy cập đầu."""
    l1 = cache_cls(L1_SETS, L1_WAYS)
    l2 = cache_cls(L2_SETS, l2_ways)
    n = l1_miss = l2_acc = l2_miss = 0
    for i, a in enumerate(addrs):
        count = i >= warmup
        if l1.access(a):
            if count:
                n += 1
            continue
        hit2 = l2.access(a)              # miss L1 -> 1 truy cập L2
        if count:
            n += 1
            l1_miss += 1
            l2_acc += 1
            l2_miss += not hit2
    return n, l1_miss, l2_acc, l2_miss


def cmd_trace(a):
    addrs = read_trace(a.csv)
    print(f"{len(addrs):,} truy cập, bỏ {a.warmup:,} đầu (làm nóng)")
    for w in (16, 8, 4):
        n, l1m, l2a, l2m = run(addrs, w, a.warmup)
        print(f"L2 {w:2d} way ({64 * w:4d} KiB): L1D miss {100 * l1m / n:5.2f}%   "
              f"L2 acc {l2a:7,}   L2 miss {100 * l2m / max(1, l2a):6.2f}%")


# quét stream (vách 64K x W)
FOOTPRINTS_K = [128, 256, 384, 512, 640, 768, 896, 1024, 1280, 1536, 2048]
WAYS_SWEEP = [16, 12, 8, 4, 2]
PASSES = 3                               # 1 lượt làm nóng + 2 lượt đếm


def cmd_sweep(a):
    os.makedirs("validation", exist_ok=True)
    rows = []
    print(f"{'footprint':>10s} " + " ".join(f"{w:>6d}w" for w in WAYS_SWEEP))
    for fp in FOOTPRINTS_K:
        per_pass = fp * 1024 // 8                       # stream: 1 truy cập mỗi 8 byte
        addrs = list(gen_trace(f"mode=stream footprint={fp}K", per_pass * PASSES))
        line = f"{fp:>9d}K "
        for w in WAYS_SWEEP:
            _, _, l2a, l2m = run(addrs, w, per_pass)
            pct = 100 * l2m / max(1, l2a)
            rows.append({"footprint_KiB": fp, "ways": w, "L2_KiB": 64 * w, "l2_miss_pct": round(pct, 2)})
            line += f" {pct:6.1f}%"
        print(line)
    with open("validation/oracle_stream_sweep.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print("đã ghi validation/oracle_stream_sweep.csv")


# oracle v2: stack distance
# tên: (tham số workload, số truy cập mỗi lượt, số lượt đo) — giống hệt lúc chạy gem5 (roi=1, warm=1)
WORKLOADS = {
    "loop768K":         ("mode=loop footprint=768K",                 12288,  2),
    "stream3x2M":       ("mode=stream footprint=2M arrays=3",        786432, 2),
    "temporal512K":     ("mode=temporal hot=512K cold=4M hotpct=90", 73728,  4),
    "graph2M":          ("mode=graph footprint=2M",                  32768,  4),
    # biến thể temporal: đổi hot -> gối dịch chuyển; đổi hotpct -> sàn lên xuống
    "temporal_hot256K": ("mode=temporal hot=256K cold=4M hotpct=90", 69632,  4),
    "temporal_hot768K": ("mode=temporal hot=768K cold=4M hotpct=90", 77824,  4),
    "temporal_p80":     ("mode=temporal hot=512K cold=4M hotpct=80", 73728,  4),
    "temporal_p95":     ("mode=temporal hot=512K cold=4M hotpct=95", 73728,  4),
}


def profile(args, per_pass, passes):
    """1 lần chạy -> bảng đếm stack distance ở L2 (theo từng set).
    distance = vị trí line trong danh sách LRU của set (0 = mới nhất). Hit với W way <=> distance < W."""
    l1 = Cache(L1_SETS, L1_WAYS)
    l2 = [[] for _ in range(L2_SETS)]            
    hist = [0] * (MAXW + 1)                      
    for i, addr in enumerate(gen_trace(args, per_pass * (1 + passes))):
        if l1.access(addr):                      
            continue
        line = addr // LINE
        s2 = l2[line % L2_SETS]
        if line in s2:
            d = s2.index(line)
            s2.remove(line)
        else:
            d = MAXW                            
        s2.insert(0, line)
        del s2[MAXW:]
        if i >= per_pass:                        
            hist[d] += 1
    return hist


def miss_from_hist(hist, w):
    return 100 * sum(hist[w:]) / max(1, sum(hist))


def cmd_sd(a):
    os.makedirs("validation", exist_ok=True)
    rows = []
    print(f"{'workload':18s} {'L2 acc':>8s}" + "".join(f"{w:>7d}w" for w in range(MAXW, 0, -1)))
    for name, (args, per_pass, passes) in WORKLOADS.items():
        h = profile(args, per_pass, passes)
        line = f"{name:18s} {sum(h):8d}"
        for w in range(MAXW, 0, -1):
            m = miss_from_hist(h, w)
            rows.append({"workload": name, "ways": w, "l2_miss_pct": round(m, 2)})
            line += f" {m:6.1f}%"
        print(line)
    with open("validation/oracle_sd.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["workload", "ways", "l2_miss_pct"])
        wr.writeheader()
        wr.writerows(rows)
    print("đã ghi validation/oracle_sd.csv")


#  so sánh với gem5
def _read_stats():
    sys.path.insert(0, "l2traffic")
    from check_run import read_stats        
    return read_stats


def _gem5_miss(stats_path, read_stats):
    s = read_stats(stats_path)
    return 100 * s["l2_miss"] / s["l2_acc"] if s["l2_acc"] else float("nan")


def cmd_cmp_cliff(a):
    read_stats = _read_stats()
    pred = {(int(r["footprint_KiB"]), int(r["ways"])): float(r["l2_miss_pct"])
            for r in csv.DictReader(open("validation/oracle_stream_sweep.csv"))}
    print(f"{'run':22s} {'footprint':>9s} {'way':>4s} {'oracle':>8s} {'gem5':>8s} {'lệch':>7s}")
    for d in sorted(glob.glob("runs_oracle/v_fp*K_w*")):
        m = re.search(r"v_fp(\d+)K_w(\d+)$", d)
        st = os.path.join(d, "stats.txt")
        if not m or not os.path.exists(st):
            continue
        fp, w = int(m.group(1)), int(m.group(2))
        g, p = _gem5_miss(st, read_stats), pred.get((fp, w), float("nan"))
        flag = "  <- xem lại" if abs(g - p) > 5 else ""
        print(f"{os.path.basename(d):22s} {fp:8d}K {w:4d} {p:7.1f}% {g:7.2f}% {g - p:+6.1f}{flag}")


def cmd_cmp_sd(a):
    read_stats = _read_stats()
    pred = {(r["workload"], int(r["ways"])): float(r["l2_miss_pct"])
            for r in csv.DictReader(open("validation/oracle_sd.csv"))}
    print(f"{'run':22s} {'oracle':>8s} {'gem5':>8s} {'lệch':>7s}")
    for d in sorted(glob.glob("runs_sd/*_w*")):
        m = re.search(r"([^/]+)_w(\d+)$", d)
        st = os.path.join(d, "stats.txt")
        if not m or not os.path.exists(st):
            continue
        name, w = m.group(1), int(m.group(2))
        g, p = _gem5_miss(st, read_stats), pred.get((name, w), float("nan"))
        flag = "  <- xem lại" if abs(g - p) > 5 else ""
        print(f"{os.path.basename(d):22s} {p:7.1f}% {g:7.2f}% {g - p:+6.1f}{flag}")


# tự kiểm tra
def cmd_check(a):
    args, per_pass = "mode=temporal hot=512K cold=4M hotpct=90", 73728
    addrs = list(gen_trace(args, per_pass * 5))
    h = profile(args, per_pass, 4)
    ok = True
    print(f"{'way':>4s} {'OrderedDict':>12s} {'Tick(LRURP)':>12s} {'stack dist':>11s}")
    for w in (16, 8, 4):
        _, _, a1, m1 = run(addrs, w, per_pass, Cache)
        _, _, a2, m2 = run(addrs, w, per_pass, CacheTick)
        p1, p2, p3 = 100 * m1 / a1, 100 * m2 / a2, miss_from_hist(h, w)
        ok &= abs(p1 - p2) < 1e-9 and abs(p1 - p3) < 1e-9
        print(f"{w:4d} {p1:11.2f}% {p2:11.2f}% {p3:10.2f}%")
    print("KHỚP" if ok else "KHÔNG KHỚP")


def main():
    p = argparse.ArgumentParser(description="Oracle LRU cho L2 dùng chung (way shutdown)")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trace", help="oracle v1 trên 1 file trace")
    t.add_argument("csv")
    t.add_argument("warmup", type=int)
    t.set_defaults(fn=cmd_trace)
    sub.add_parser("sweep", help="quét stream 11 footprint x 5 way").set_defaults(fn=cmd_sweep)
    sub.add_parser("cmp-cliff", help="so sweep với runs_oracle/").set_defaults(fn=cmd_cmp_cliff)
    sub.add_parser("sd", help="oracle stack distance cho mọi workload").set_defaults(fn=cmd_sd)
    sub.add_parser("cmp-sd", help="so oracle_sd với runs_sd/").set_defaults(fn=cmd_cmp_sd)
    sub.add_parser("check", help="tự kiểm tra các cách cài LRU").set_defaults(fn=cmd_check)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
