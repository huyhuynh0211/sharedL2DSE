// Idle: chạy trên các core không làm bài test. Mảng 4 KiB nằm gọn trong L1, không xuống L2.
#include <vector>
using namespace std;

const long BYTES  = 4096;
const long PASSES = 1000;

int main()
{
    long n = BYTES / 8;
    vector<long> a(n, 1);

    long sum = 0;
    for (long k = 0; k < PASSES; k++)
        for (long i = 0; i < n; i++)
            sum += a[i];

    return 0;
}
