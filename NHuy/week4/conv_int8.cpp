// Tiled conv 3x3 int8 (NHWC), weights dominate memory
// usage: conv_int8 CO
#include <vector>
#include <cstdint>
#include <cstdlib>
using namespace std;

const int OH = 8;
const int OW = 8;
const int CI = 64;
const int R = 3;
const int IH = OH + R - 1;
const int IW = OW + R - 1;
const int TOH = 2;
const int TCO = 16;
const int SHIFT = 8;

volatile long sink;

// m5 work_begin: the ROI starts here
void roi_begin()
{
    asm volatile("li a0, 0\n\tli a1, 0\n\t.4byte 0xb400007b" : : : "a0", "a1", "memory");
}

int main(int argc, char **argv)
{
    int CO = 64;
    if (argc > 1)
        CO = atoi(argv[1]);
    if (CO < TCO || CO % TCO != 0)
        return 1;

    // part 1: init data
    vector<int8_t> X(IH * IW * CI), Wt(CO * R * R * CI), Y(OH * OW * CO);
    for (int i = 0; i < IH * IW * CI; i++)
        X[i] = (int8_t)(i % 11 - 5);
    for (int i = 0; i < CO * R * R * CI; i++)
        Wt[i] = (int8_t)(i % 7 - 3);

    // part 2: start ROI
    roi_begin();

    // part 3: tiled conv
    for (int oh0 = 0; oh0 < OH; oh0 += TOH)
        for (int co0 = 0; co0 < CO; co0 += TCO)
            for (int oh = oh0; oh < oh0 + TOH; oh++)
                for (int ow = 0; ow < OW; ow++)
                    for (int co = co0; co < co0 + TCO; co++) {
                        int acc = 0;
                        for (int r = 0; r < R; r++)
                            for (int s = 0; s < R; s++) {
                                int xb = ((oh + r) * IW + (ow + s)) * CI;
                                int wb = ((co * R + r) * R + s) * CI;
                                for (int ci = 0; ci < CI; ci++)
                                    acc += X[xb + ci] * Wt[wb + ci];
                            }
                        int v = acc >> SHIFT;
                        if (v > 127)
                            v = 127;
                        if (v < -128)
                            v = -128;
                        Y[(oh * OW + ow) * CO + co] = (int8_t)v;
                    }

    // part 4: checksum
    long sum = 0;
    for (int i = 0; i < OH * OW * CO; i++)
        sum += Y[i];
    sink = sum;
    return 0;
}
