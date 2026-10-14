// Streaming: c[i] = a[i] + k * b[i], mỗi phần tử chỉ dùng một lần mỗi lượt
#include <vector>
using namespace std;

const long BYTES  = 2097152;    // 2 MiB mỗi mảng
const long PASSES = 8;

int main()
{
    long n = BYTES / 8;
    vector<long> a(n), b(n), c(n);
    for (long i = 0; i < n; i++) {
        a[i] = i;
        b[i] = 2 * i;
    }

    for (long k = 1; k <= PASSES; k++)
        for (long i = 0; i < n; i++)
            c[i] = a[i] + k * b[i];

    return 0;
}
