import os
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.classic.private_l1_shared_l2_cache_hierarchy import (
    PrivateL1SharedL2CacheHierarchy,
)
from gem5.components.memory import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource
from gem5.simulate.simulator import Simulator

LINE = 64
SETS = 1024
L2_WAYS = 16

# dung lượng = số set x số way x kích thước line
l2_size_kib = SETS * L2_WAYS * LINE // 1024

cache_hierarchy = PrivateL1SharedL2CacheHierarchy(
    l1d_size="32KiB", l1d_assoc=8,
    l1i_size="32KiB", l1i_assoc=8,
    l2_size=f"{l2_size_kib}KiB", l2_assoc=L2_WAYS,
)

board = SimpleBoard(
    clk_freq="1GHz",
    processor=SimpleProcessor(
        cpu_type=CPUTypes.MINOR, isa=ISA.RISCV, num_cores=1
    ),
    memory=SingleChannelDDR3_1600(size="512MiB"),
    cache_hierarchy=cache_hierarchy,
)

binary = BinaryResource(
    local_path=os.path.expanduser(
        "~/Documents/workspace/project_gem5/tests/hello.riscv"
    )
)
board.set_se_binary_workload(binary)

print(f"L2 = {l2_size_kib} KiB, {L2_WAYS}-way, {SETS} set, line {LINE} B")

sim = Simulator(board=board)
sim.run()
