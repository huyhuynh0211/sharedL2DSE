import os
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.components.memory import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource, obtain_resource
from gem5.simulate.simulator import Simulator

board = SimpleBoard(
    clk_freq="1GHz",
    processor=SimpleProcessor(cpu_type=CPUTypes.MINOR, isa=ISA.RISCV, num_cores=1),
    memory=SingleChannelDDR3_1600(size="512MiB"),
    cache_hierarchy=NoCache(),
)
binary = BinaryResource(local_path=os.path.expanduser("~/Documents/workspace/project_gem5/tests/hello.riscv"))
board.set_se_binary_workload(binary)
sim = Simulator(board=board)
sim.run()
