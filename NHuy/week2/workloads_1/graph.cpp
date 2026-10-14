// Pointer chasing: đi ngẫu nhiên trên đồ thị, mỗi node 64 byte có 4 cạnh ra
#include <cstdlib>
#include <vector>
using namespace std;

const long BYTES = 524288;
const long STEPS = 500000;

struct alignas(64) Node {       // mỗi node nằm gọn trong 1 cache line
    Node* next[4];
    long pad[4];
};

int main()
{
    long n = BYTES / 64;
    vector<Node> g(n);
    for (long i = 0; i < n; i++)
        for (int j = 0; j < 4; j++)
            g[i].next[j] = &g[rand() % n];

    Node* cur = &g[0];
    for (long s = 0; s < STEPS; s++)
        cur = cur->next[rand() % 4];

    return 0;
}
