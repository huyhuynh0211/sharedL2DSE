// Looping
#include <vector>
using namespace std;

const long BYTES  = 786432;     // 768 KiB
const long PASSES = 100;

int main()
{
    long n = BYTES / 8;
    vector<long> a(n);
    for (long i = 0; i < n; i++)
        a[i] = i;

    long sum = 0;
    for (long k = 0; k < PASSES; k++)
        for (long i = 0; i < n; i++)
            sum += a[i];

    return 0;
}
