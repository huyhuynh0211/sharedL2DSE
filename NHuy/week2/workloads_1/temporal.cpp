// Temporal locality
#include <cstdlib>
#include <vector>
using namespace std;

const long HOT_BYTES  = 131072;
const long COLD_BYTES = 1048576;
const long HOT_PCT    = 90;         // 90% số lần truy cập vào vùng nóng
const long ACCESSES   = 750000;

int main()
{
    // Mỗi line 64 byte = 8 phần tử long, chỉ đọc phần tử đầu của mỗi line
    long hot_lines  = HOT_BYTES / 64;
    long cold_lines = COLD_BYTES / 64;
    vector<long> hot(hot_lines * 8, 1), cold(cold_lines * 8, 2);

    long sum = 0;
    for (long k = 0; k < ACCESSES; k++) {
        if (rand() % 100 < HOT_PCT)
            sum += hot[(rand() % hot_lines) * 8];
        else
            sum += cold[(rand() % cold_lines) * 8];
    }

    return 0;
}
