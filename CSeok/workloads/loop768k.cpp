#include <cstdio>
#include <cstdint>
#include <vector>
using namespace std;

// Loop: walk a 768 KiB array in order, one access per 64-byte line, many passes.
int main()
{
    int n = 768 * 1024 / 4;     // 768 KiB of int
    int pass = 400;
    vector <int> a(n);
    for (int i=0; i<n; i++){
        a[i]=i;
    }

    int64_t sum = 0;
    for (int p=0; p<pass; p++){
        for (int i=0; i<n; i+=16){     // 16 ints = 64 bytes = 1 cache line
            sum+=a[i];
        }
        asm volatile("" ::: "memory");
    }

    printf("%lld\n", (long long)sum);
    return 0;
}