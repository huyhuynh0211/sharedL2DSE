#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <numeric>
#include <random>
#include <string>
#include <vector>
 
namespace {
 
constexpr std::size_t kLine = 64;
constexpr std::size_t kHotBytes = 8 * 1024;  // binv: vùng nóng nằm gọn trong L1D 32 KiB
constexpr int kHotPerCold = 8;               // binv: số lần đọc vùng nóng mỗi line lạnh
 
volatile std::uint64_t g_sink;  // chặn compiler bỏ vòng lặp
 
struct FreeDeleter {
    void operator()(std::uint8_t *p) const { std::free(p); }
};
using Buffer = std::unique_ptr<std::uint8_t[], FreeDeleter>;
 
struct Config {
    std::string mode;
    std::size_t bytes;   // footprint của core này
    std::size_t stride;
    int core;
    std::uint64_t seed;
    std::uint64_t iters; // 0 = vô hạn
};
 
// Vòng lặp ngoài: chạy iters lượt, hoặc mãi nếu iters == 0
template <typename Body>
void repeat(std::uint64_t iters, Body body) {
    for (std::uint64_t it = 0; iters == 0 || it < iters; ++it) body(it);
}
 
// cap: quét tuần tự lặp lại, chỉ đọc. LRU: miss L2 ~0 khi tổng footprint <= C(W),
// ~100% ngay khi vượt (vách LRU).
void run_cap(std::uint8_t *buf, const Config &c) {
    std::uint64_t acc = 0;
    repeat(c.iters, [&](std::uint64_t) {
        for (std::size_t i = 0; i < c.bytes; i += c.stride) acc += buf[i];
    });
    g_sink = acc;
}
 
// cap_rand: pointer chase qua mọi line theo một hoán vị ngẫu nhiên (1 vòng duy nhất).
// Không có vách LRU, đường cong miss rate mượt.
void run_cap_rand(std::uint8_t *buf, const Config &c) {
    const std::size_t lines = c.bytes / kLine;
    std::vector<std::size_t> perm(lines);
    std::iota(perm.begin(), perm.end(), 0);
    std::mt19937_64 rng(c.seed);
    for (std::size_t i = lines - 1; i > 0; --i) {  // Fisher-Yates, xác định theo seed
        std::size_t j = rng() % (i + 1);
        std::swap(perm[i], perm[j]);
    }
    for (std::size_t i = 0; i < lines; ++i) {      // nối thành 1 vòng
        auto **slot = reinterpret_cast<std::uint8_t **>(buf + perm[i] * kLine);
        *slot = buf + perm[(i + 1) % lines] * kLine;
    }
    perm.clear();
    perm.shrink_to_fit();
 
    std::uint8_t *p = buf;
    repeat(c.iters, [&](std::uint64_t) {
        for (std::size_t i = 0; i < lines; ++i) p = *reinterpret_cast<std::uint8_t **>(p);
    });
    g_sink = static_cast<std::uint64_t>(p - buf) / kLine;  // chỉ số line cuối, xác định
}
 
// binv: vùng nóng luôn hit L1 (nên không được làm mới trong LRU của L2) xen với luồng
// lạnh đi qua L2. L2 inclusive đẩy line nóng ra và back-invalidate L1 -> L1D miss vượt
// quá số line lạnh. L2 non-inclusive: không có phần vượt đó.
void run_binv(std::uint8_t *buf, const Config &c) {
    std::uint8_t *hot = buf;
    std::uint8_t *cold = buf + kHotBytes;
    const std::size_t ncold = c.bytes - kHotBytes;
    std::size_t h = 0;
    std::uint64_t acc = 0;
    repeat(c.iters, [&](std::uint64_t) {
        for (std::size_t i = 0; i < ncold; i += c.stride) {
            acc += cold[i];
            for (int k = 0; k < kHotPerCold; ++k) {
                acc += hot[h];
                h = (h + kLine) % kHotBytes;
            }
        }
    });
    g_sink = acc;
}
 
// write: chỉ ghi (kiểu memset) -> line bẩn ở L1, writeback vào L2 rồi xuống DRAM.
// rmw  : đọc - sửa - ghi.
void run_write(std::uint8_t *buf, const Config &c, bool rmw) {
    repeat(c.iters, [&](std::uint64_t it) {
        for (std::size_t i = 0; i < c.bytes; i += c.stride) {
            auto *w = reinterpret_cast<std::uint64_t *>(buf + i);
            if (rmw) *w += it + 1;
            else *w = it;
        }
    });
    g_sink = buf[0];
}
 
[[noreturn]] void usage(const char *prog, const char *why) {
    std::fprintf(stderr, "%s\nusage: %s <cap|cap_rand|binv|write|rmw> <bytes_per_core> "
                         "<stride> <core_id> <seed> <iters>\n", why, prog);
    std::exit(2);
}
 
Config parse(int argc, char **argv) {
    if (argc != 7) usage(argv[0], "sai số tham số");
    Config c{argv[1],
             std::strtoull(argv[2], nullptr, 0),
             std::strtoull(argv[3], nullptr, 0),
             std::atoi(argv[4]),
             std::strtoull(argv[5], nullptr, 0) | 1,
             std::strtoull(argv[6], nullptr, 0)};
    if (c.stride < 8 || c.stride % 8 != 0 || c.bytes < 2 * kLine)
        usage(argv[0], "stride phải là bội của 8, footprint >= 128 B");
    if (c.mode == "binv" && c.bytes <= kHotBytes)
        usage(argv[0], "binv cần footprint mỗi core > 8192 B");
    c.bytes -= c.bytes % kLine;
    return c;
}
 
}  // namespace
 
int main(int argc, char **argv) {
    const Config c = parse(argc, argv);
 
    Buffer buf(static_cast<std::uint8_t *>(std::aligned_alloc(4096, c.bytes)));
    if (!buf) { std::perror("aligned_alloc"); return 1; }
    // Chạm mọi trang trước: SE mode cấp trang vật lý khi chạm lần đầu.
    std::memset(buf.get(), c.core + 1, c.bytes);
 
    if (c.mode == "cap") run_cap(buf.get(), c);
    else if (c.mode == "cap_rand") run_cap_rand(buf.get(), c);
    else if (c.mode == "binv") run_binv(buf.get(), c);
    else if (c.mode == "write") run_write(buf.get(), c, false);
    else if (c.mode == "rmw") run_write(buf.get(), c, true);
    else usage(argv[0], ("mode không hợp lệ: " + c.mode).c_str());
 
    std::printf("core %d %s done, sink=%llu\n", c.core, c.mode.c_str(),
                static_cast<unsigned long long>(g_sink));
    return 0;
}
