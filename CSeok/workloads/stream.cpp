#include <cstdio>
#include <cstdint>
#include <vector>
using namespace std;

// Stream: a[i] = b[i] + 3*c[i] over three 2 MiB arrays (stream triad).
int main()
{
    int n = 2 * 1024 * 1024 / 4;   // 2 MiB of int per array
    int pass = 2;
    vector <int> a(n), b(n), c(n);
    for (int i=0; i<n; i++){
        b[i]=i;
        c[i]=2*i;
    }

    for (int p=0; p<pass; p++){
        for (int i=0; i<n; i++){
            a[i]=b[i]+3*c[i];
        }
        asm volatile("" ::: "memory");
    }

    int64_t sum = 0;
    for (int i=0; i<n; i+=16){
        sum+=a[i];
    }

    printf("%lld\n", (long long)sum);
    return 0;
}