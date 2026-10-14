#include <cstdio>
#include <cstdint>
#include <vector>
using namespace std;


int main()
{
    int n = 8192;
    int pass = 50;
    vector <int> a(n);
    for (int i=0; i<n; i++){
        a[i]=i;
    }

    int64_t sum = 0;
    for (int p=0; p<pass; p++){
        for (int i=0; i<n; i++){
            sum+=a[i];
        }
        asm volatile("" ::: "memory");
    }

    printf("%lld\n", (long long)sum);
}
