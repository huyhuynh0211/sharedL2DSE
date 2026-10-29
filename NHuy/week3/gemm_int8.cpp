// Tiled GEMM int8: C[M][N] = requant( A[M][K] x B[K][N] )
// int8 in/out, int32 accumulate (like a quantized fully-connected layer)
#include <vector>
#include <cstdint>
#include <cstdlib>
using namespace std;

const int M = 32;
const int K = 256;
const int TM = 16;     // row tile of A and C
const int TN = 64;     // column tile of B and C (64 B = 1 line)
const int TK = 32;     // tile along K
const int SHIFT = 8;   // requant: out = clamp(acc >> SHIFT, -128, 127)

volatile long sink;

int main(int argc, char **argv)
{
    int N = 256;
    if (argc > 1)
        N = atoi(argv[1]);
    if (N < TN || N % TN != 0)
        return 1;

    vector<int8_t> A(M * K), B(K * N), C(M * N);
    for (int i = 0; i < M * K; i++)
        A[i] = (int8_t)(i % 11 - 5);
    for (int i = 0; i < K * N; i++)
        B[i] = (int8_t)(i % 7 - 3);

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

    long sum = 0;
    for (int i = 0; i < M * N; i++)
        sum += C[i];
    sink = sum;
    return 0;
}
