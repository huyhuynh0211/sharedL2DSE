// Vector/DSP-like stream: y[i] = y[i] + 3 * x[i] (int64), high L2 traffic
// usage: vec_stream KIB PASSES   (x and y are KIB/2 each)
#include <vector>
#include <cstdint>
#include <cstdlib>
using namespace std;

volatile long sink;

// m5 work_begin: the ROI starts here
void roi_begin()
{
    asm volatile("li a0, 0\n\tli a1, 0\n\t.4byte 0xb400007b" : : : "a0", "a1", "memory");
}

int main(int argc, char **argv)
{
    int kib = 192;
    int passes = 100;
    if (argc > 1)
        kib = atoi(argv[1]);
    if (argc > 2)
        passes = atoi(argv[2]);
    int n = kib * 1024 / 16;
    if (n < 8)
        return 1;

    // part 1: init data
    vector<int64_t> x(n), y(n);
    for (int i = 0; i < n; i++) {
        x[i] = i % 13;
        y[i] = i % 5;
    }

    // part 2: start ROI
    roi_begin();

    // part 3: stream
    for (int p = 0; p < passes; p++)
        for (int i = 0; i < n; i++)
            y[i] = y[i] + 3 * x[i];

    // part 4: checksum
    long sum = 0;
    for (int i = 0; i < n; i++)
        sum += y[i];
    sink = sum;
    return 0;
}
