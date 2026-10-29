// Tiled GEMM int8: C[M][N] = A[M][K] x B[K][N]
// usage: gemm_int8 N M   (B is read again M/TM times)
#include <vector>
#include <cstdint>
#include <cstdlib>
using namespace std;

const int K = 256;
const int TM = 16;
const int TN = 64;
const int TK = 32;
const int SHIFT = 8;

volatile long sink;

// m5 work_begin: the ROI starts here
void roi_begin()
{
    asm volatile("li a0, 0\n\tli a1, 0\n\t.4byte 0xb400007b" : : : "a0", "a1", "memory");
}

int main(int argc, char **argv)
{
    int N = 256;
    int M = 32;
    if (argc > 1)
        N = atoi(argv[1]);
    if (argc > 2)
        M = atoi(argv[2]);
    if (N < TN || N % TN != 0 || M < TM || M % TM != 0)
        return 1;

    // part 1: init data
    vector<int8_t> A(M * K), B(K * N), C(M * N);
    for (int i = 0; i < M * K; i++)
        A[i] = (int8_t)(i % 11 - 5);
    for (int i = 0; i < K * N; i++)
        B[i] = (int8_t)(i % 7 - 3);

    // part 2: start ROI
    roi_begin();

    // part 3: tiled GEMM
    int acc[TM][TN];
    for (int ii = 0; ii < M; ii += TM) {
        for (int jj = 0; jj < N; jj += TN) {
            for (int i = 0; i < TM; i++)
                for (int j = 0; j < TN; j++)
                    acc[i][j] = 0;

            for (int kk = 0; kk < K; kk += TK)
                for (int i = 0; i < TM; i++)
                    for (int k = 0; k < TK; k++) {
                        int a = A[(ii + i) * K + kk + k];
                        for (int j = 0; j < TN; j++)
                            acc[i][j] += a * B[(kk + k) * N + jj + j];
                    }

            for (int i = 0; i < TM; i++)
                for (int j = 0; j < TN; j++) {
                    int v = acc[i][j] >> SHIFT;
                    if (v > 127)
                        v = 127;
                    if (v < -128)
                        v = -128;
                    C[(ii + i) * N + jj + j] = (int8_t)v;
                }
        }
    }

    // part 4: checksum
    long sum = 0;
    for (int i = 0; i < M * N; i++)
        sum += C[i];
    sink = sum;
    return 0;
}
