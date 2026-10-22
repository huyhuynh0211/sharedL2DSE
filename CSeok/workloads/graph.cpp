#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <vector>
using namespace std;

// Graph: random walk over a 2 MiB graph. Each node is one 64-byte line with links to 4 random nodes.
int main()
{
    int nodes = 2 * 1024 * 1024 / 64;    // 32768 nodes
    int steps = 300000;
    vector <int> g(nodes*16);            // 16 ints per node = 64 bytes
    for (int v=0; v<nodes; v++){
        for (int k=0; k<4; k++){
            g[v*16+k]=rand()%nodes;      // the 4 neighbours of node v
        }
    }

    int v = 0;
    for (int s=0; s<steps; s++){
        v=g[v*16+rand()%4];              // next node comes from this load
    }

    printf("%d\n", v);
    return 0;
}