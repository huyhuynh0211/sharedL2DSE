#include <cstdio>
#include <cstdint>
#include <cstdlib>
using namespace std;

// Temporal: 90% of accesses go to a small hot region (512 KiB), 10% to a big cold region (4 MiB).
const int HOT_N = 512 * 1024 / 4;          // 512 KiB of int
const int COLD_N = 4 * 1024 * 1024 / 4;    // 4 MiB of int
int hot[HOT_N];
int cold[COLD_N];

int main()
{
    int hot_lines = HOT_N / 16;            // 16 ints per 64-byte line
    int cold_lines = COLD_N / 16;
    int accesses = 300000;
    for (int i=0; i<HOT_N; i++){
        hot[i]=i;
    }
    for (int i=0; i<COLD_N; i++){
        cold[i]=i;
    }

    int64_t sum = 0;
    for (int k=0; k<accesses; k++){
        if (rand()%100 < 90){
            sum+=hot[(rand()%hot_lines)*16];
        } else {
            sum+=cold[(rand()%cold_lines)*16];
        }
    }

    printf("%lld\n", (long long)sum);
    return 0;
}