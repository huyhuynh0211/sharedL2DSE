#include <iostream>
#include <cstdlib>

using namespace std;

int main(int argc, char *argv[]) {
    // Nhận tham số từ gem5 truyền vào
    long footprint = (argc > 1) ? atol(argv[1]) : 2097152; // Mặc định 2MB
    int stride     = (argc > 2) ? atoi(argv[2]) : 64;      // Mặc định 64B
    int core_id    = (argc > 3) ? atoi(argv[3]) : 0;

    cout << "[Core " << core_id << "] Started DSP Traffic! Footprint: " 
         << footprint << " bytes, Stride: " << stride << endl;

    // Cấp phát mảng động bằng 'new' của C++
    // Từ khóa 'volatile' rất quan trọng: Ép CPU phải thực sự ghi xuống RAM/Cache,
    // ngăn không cho trình biên dịch (compiler) tự động xóa vòng lặp này đi để tối ưu.
    volatile char *arr = new char[footprint];

    if (arr != nullptr) {
        for (long i = 0; i < footprint; i += stride) {
            arr[i] = (char)(i & 0xFF);
        }
        // Giải phóng bộ nhớ
        delete[] arr;
    }

    cout << "[Core " << core_id << "] Finished successfully." << endl;
    return 0;
}