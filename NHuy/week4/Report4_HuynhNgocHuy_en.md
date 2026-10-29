# Fixing the model after the week 3 feedback
In week 3, the result where dynamic turned off ways down to W1, with only about 1% slowdown and 78% less L2 leakage, was said to be unrealistic. I checked again and found that there were real problems in the workload, the controller and the simulation setup:
- The workload almost did not use L2. For gemm768 at W16, the L1D miss rate was only 0.075%. The whole 64M-cycle run had only 52,274 L2 accesses (about 0.8 per 1000 cycles), and DRAM ran at only 1.2 MB/s. If we removed L2 completely, run time would grow by about 51,500 × 49 / 4 cores ≈ 1%, which is exactly the result of dynamic at W1. This means that experiment could not tell which policy is better. The reason is that M = 32, so matrix B was read only 2 times, and int8 code runs as scalar code on a 1-issue core, so the program is limited by compute, not by memory
- The controller went down to W1 because of the idle rule, not because of the ATD. The ATD saw only about 25 sampled accesses per interval. Times 32, that is about 790, which is lower than the idle threshold of 1000, so it was forced to W1. The allowed number of extra misses (656 per interval) was also larger than the total number of L2 accesses, so any W would pass
- The runs used tmem = 61, which is the full latency, not the extra penalty (49). The path from L2 to DRAM was left at the gem5 default
- `mostly_incl` in gem5 moves dirty lines up to L1 in the Modified state, so even though B was only read, L1D still had 51,466 writebacks, almost the same as the number of demand accesses
- The scripts converted units with a fixed 1 GHz (`interval / 1e9`, latency divided by 1000), and the energy for fixed W used the leakage of a 16-way L2

The direction from anh Nam was to take workloads from the cva6 GitHub repo. But after reading them, I found they are similar to the workloads I already studied before, and their capacity is even smaller. I have not received the workloads from Khánh Ngọc yet, so I still use the week 3 workloads.

I also fixed 2 bugs in the parts I added to gem5: the ATD had a fixed number of 32 sampled sets (an L2 with more than 1056 sets would write outside the memory), and drowsy woke up a line even on a CleanEvict, while a CleanEvict only touches the tag.

## Configuration after the fix
The core settings follow the RTL `cv64a6_imafdc_sv39_wb`:

| Setting | Week 3 | Week 4 | Reason |
|---|---|---|---|
| Clock | 1 GHz | 100 MHz (also ran 1 GHz to compare) | Following the 50–100 MHz feedback |
| Latency | fixed cycles | given in ns, then converted to cycles | L2 tag 2 ns / data 6 ns / resp 2 ns, NoC 2 ns. At 1 GHz this is the same as week 3 |
| NoC core → L2 | 16 B | 8 B | CVA6 AXI data is 64 bit |
| L2 → DRAM | gem5 default | 25 ns (assumed) | with MemCtrl and DDR4 this gives about 70–80 ns |
| ALU / mul / div | 3 / 3 / 9 | 1 / 2 / 32 | CVA6 ALU 1 cycle, mult 2, serial divider |
| Branch predictor | Tournament | BHT 128, BTB 32, RAS 2 | Following the RTL |
| Store buffer | 5 | 4 | `DEPTH_COMMIT = 4` |
| L1 MSHR | 1 | 8 | |
| L1 replacement | LRU | LFSR | The RTL picks the victim with an LFSR |
| Measured region | 10M-cycle warmup | from when all 4 programs finish init (`m5 work_begin`) | init is not measured |
| tmem | 61 (fixed) | measured with `tmem_calc.py` | |
| Idle rule | 1000 | off | let the ATD decide |

Things kept the same: L2 1 MiB, 16 ways, 4 banks, Tree-PLRU, non-inclusive, L2 MSHR 32, DDR4-2400, controller runs every 1M cycles, k = 3, margin 1.

# Workload

| Name | Command | 4-core footprint | Purpose |
|---|---|---|---|
| vec192 | `vec_stream 192 400` | 768 KiB (12 ways) | `y[i] += 3*x[i]` with int64, very few instructions per byte, so L2 traffic is high, like vector/DSP |
| gemm64 | `gemm_int8 768 64` | B 4 × 192 KiB, read again 4 times | int8 GEMM like week 3 but M = 64 |
| conv256 | `conv_int8 256` | weights 4 × 144 KiB, read again 4 times | Same as week 3 |
| mix | 2 cores gemm64 + 2 cores `vec_stream 192 900` | about 780 KiB | a vector stream sharing L2 with GEMM |

- vec_stream is a new workload. It was added because GEMM and conv running as scalar code do not make enough traffic for L2 to matter. In the project, vector/DSP traffic is also a part that needs to be approximated
- Each program calls `m5 work_begin` right after init. Measuring only starts after all 4 cores have called it

# Measuring tmem
tmem is the number of extra cycles a core waits for one L2 miss. It is the L1D miss latency when every L2 access misses, minus the L1D miss latency when every L2 access hits. For the all-miss case I ran `vec_stream 4096` (4 × 4 MiB, much larger than L2), and for the all-hit case I ran `vec_stream 64` (4 × 64 KiB, larger than L1 but fits in L2).

| Clock | L1D miss lat all-miss | all-hit | tmem |
|---|---|---|---|
| 100 MHz | 15.5 | 5.1 | 10.4 cycles (104 ns) |
| 1 GHz | 97.1 | 13.0 | 84.0 cycles (84 ns) |

- It is the same DRAM, but counted in cycles, one miss at 100 MHz is about 8 times cheaper, so turning off ways at 100 MHz costs much less time than at 1 GHz
- In ns, 100 MHz is actually longer (104 vs 84 ns), because each stage (NoC, L2, membus) takes at least 1 cycle = 10 ns, so the latency is rounded up

# Results at 100 MHz
Here `fixed W` means L2 is still built with 16 ways, but only W ways are on for the whole run, the same way dynamic turns ways off. It is used as a reference to check the controller. The time column is compared with W16.

## vec192

| Run | Average W | L2 miss % | L1D miss lat | Time |
|---|---|---|---|---|
| W16 | 16 | 0.01 | 5.2 | — |
| fixed W12 | 12 | 6.96 | 5.7 | +0.63% |
| fixed W8 | 8 | 84.22 | 14.1 | +13.81% |
| fixed W4 | 4 | 90.53 | 14.6 | +14.70% |
| dyn | 14.07 | 0.06 | 5.1 | −0.08% |

## gemm64

| Run | Average W | L2 miss % | L1D miss lat | Time |
|---|---|---|---|---|
| W16 | 16 | 2.35 | 4.4 | — |
| fixed W12 | 12 | 20.17 | 6.4 | +0.02% |
| fixed W8 | 8 | 39.02 | 8.8 | +0.04% |
| fixed W4 | 4 | 57.88 | 10.6 | +0.05% |
| dyn | 1.21 | 81.82 | 13.3 | +0.07% |

## conv256

| Run | Average W | L2 miss % | L1D miss lat | Time |
|---|---|---|---|---|
| W16 | 16 | 0.89 | 4.1 | — |
| fixed W12 | 12 | 3.45 | 4.3 | +0.00% |
| fixed W8 | 8 | 48.92 | 9.6 | +0.03% |
| fixed W4 | 4 | 79.57 | 12.9 | +0.05% |
| dyn | 1.31 | 83.06 | 13.1 | +0.05% |

## mix

| Run | Average W | L2 miss % | L1D miss lat | Time |
|---|---|---|---|---|
| W16 | 16 | 0.02 | 4.7 | — |
| fixed W12 | 12 | 0.37 | 5.7 | +0.02% |
| fixed W8 | 8 | 1.14 | 8.0 | +0.07% |
| fixed W4 | 4 | 74.59 | 13.7 | +2.21% |
| dyn | 11.22 | 0.48 | 6.1 | +0.03% |

## Number of ways of dynamic over time
Each interval is 1M cycles:

| Workload | Number of ways | ATD predicted miss % (W16 / 13 / 12 / 11 / 10 / 8) |
|---|---|---|
| vec192 | 16, 16, then W14 until the end (57 intervals) | 0 / 0 / 11.8 / 77.3 / 90.2 / 90.7 |
| gemm64 | 16, 16, then W1 (140 intervals) | 0.9 / 16.0 / 28.7 / 34.9 / 36.2 / 38.1 |
| conv256 | 16, 16, then W1 (95 intervals) | 0 / 0 / 0 / 0 / 8.4 / 79.3 |
| mix | 16, 16, W12 (127 intervals), W9 (3), W1 (last 10 intervals) | 0 / 0.1 / 0.3 / 0.6 / 11.5 / 58.2 |

## Discussion of the results
- For vec192, the cliff is between W12 and W11 (the ATD shows W13 0%, W12 11.8%, W11 77.3%), which matches the prediction of 768 KiB / 64 KiB = 12 ways. Going past the cliff really makes it slower: at W8 the miss rate is 84% and it is 13.8% slower. The controller keeps W14 (W13 plus margin 1) for the whole run, so the miss rate is only 0.06% and there is no slowdown. This time the controller decides based on the ATD, and is not forced down by the idle rule like in week 3
- For gemm64 and conv256, dynamic still goes down to W1, and the miss rate rises to 82–83%, but it is only 0.05–0.07% slower. This time it is not a bug, it follows the threshold correctly:
  - gemm64 has only 141,754 L2 accesses in 142M cycles (about 1 per 1000 cycles), and conv256 has even fewer (50,371 in 98M cycles)
  - The allowed number of extra misses is 0.01 × 1,000,000 × 4 / 10.4 ≈ 3,846 per interval, while each interval only has about 1,000 L2 accesses. Even if all of them miss, it is still under 1%, so turning everything off makes sense
  - In other words, GEMM and conv running as scalar code on CVA6 almost do not need L2. The conclusion "turn off all ways" is only true for this kind of workload. For vector-like traffic, we must not turn off ways past the cliff
- For mix, while the 2 vec cores are still running, the controller keeps W12. When vec finishes and only GEMM is left, it goes down to W9 and then W1, so the controller can follow the phases of the program. In all 4 workloads, the controller never had to turn ways back on (`ways_turned_on = 0`), so the turn-on path has not been tested yet
- The ATD (using LRU) predicts more misses than the real L2 (using Tree-PLRU) in every case we can compare:

| | ATD (LRU) | fixed (Tree-PLRU) measured |
|---|---|---|
| vec192 W12 | 11.8% | 6.96% |
| gemm64 W12 | 28.7% | 20.17% |
| conv256 W8 | 79.3% | 48.92% |
| mix W8 | 58.2% | 1.14% |

  - In mix the gap is very large: the real W8 only misses 1.14% but the ATD says 58%, so the controller keeps W12 while W8 would be enough. I think the reason is that Tree-PLRU rarely evicts vec lines (used all the time) and often evicts GEMM lines (used again only once in a while), while LRU always evicts the oldest line. I have not checked this yet. To be more accurate, the ATD should model Tree-PLRU, or the margin of 1 should be removed
- Comparing fixed and dynamic, the time and miss rate of dynamic fall in the right place between the matching fixed points: vec dyn at W14 is almost the same as W16, and mix dyn at about W11 is between fixed W12 and W8

# Effect of the clock (vec192)

| Run | 100 MHz: miss % / time | 1 GHz: miss % / time |
|---|---|---|
| W16 | 0.01 / — | 0.01 / — |
| fixed W8 | 84.22 / +13.81% | 84.23 / +127.90% |
| dyn | 0.06 / −0.08% (W14) | 0.06 / −0.11% (W14) |

- The miss rate at the 2 clocks is almost the same, because it is decided by the address stream. But the cost of turning off ways wrongly is about 10 times different: at 1 GHz, going down to W8 makes the run more than twice as long, because each miss costs 84 cycles instead of 10
- The controller chooses W14 at both clocks because the threshold is computed from the measured tmem, so no manual tuning is needed. Still, the real clock of the chip has a big effect on whether turning off ways is worth it

# Energy
Before the numbers, it should be clear that the leakage saving comes from the power gate. Turning off a way has two steps. The logic step is to stop placing new lines in that way, write the dirty lines to DRAM and then clear the lines. The physical step is that a sleep transistor cuts the power of that way's SRAM array. Then the leakage of the way is almost 0, but the data inside is lost. So the way must be flushed first before the power is cut, and the controller above is the part that decides when to do these two steps.

The energy part still uses McPAT 22 nm like week 3. L2 P_leak by W: W16 0.1472 / W8 0.0799 / W4 0.0512 / W2 0.0342 / W1 0.0270 W. Dynamic leakage = Σ P_leak(W) × time at each W, plus the DRAM energy to write the dirty lines when ways are turned off.

| Workload | Run | L2 leakage mJ (saving) | Total mJ (saving) |
|---|---|---|---|
| vec192 | W16 | 88.23 | 1,112.07 |
| | fixed W12 | 68.48 (−22.4%) | 1,193.14 (up 7.29%) |
| | fixed W8 | 54.49 (−38.2%) | 1,455.76 (up 30.91%) |
| | dyn | 78.42 (−11.1%) | 1,101.91 (−0.91%) |
| gemm64 | W16 | 209.56 | 2,643.82 |
| | dyn | 40.85 (−80.5%) | 2,494.44 (−5.65%) |
| conv256 | W16 | 144.14 | 1,812.44 |
| | dyn | 28.84 (−80.0%) | 1,706.98 (−5.82%) |
| mix | W16 | 209.56 | 2,640.49 |
| | fixed W4 | 74.47 (−64.5%) | 2,998.02 (up 13.54%) |
| | dyn | 152.58 (−27.2%) | 2,594.20 (−1.75%) |

- The energy to write dirty lines when turning off ways is very small, only 0.003–0.03 mJ (1,376–13,057 lines)
- For vec192, fixed W12 is only 0.63% slower, but total energy goes up by 7.3%. The increase is in DRAM (503 to 599 mJ), while the real read/write energy is only about 1.2 mJ. The DRAMPower stats show:

| DRAM | W16 | fixed W12 |
|---|---|---|
| active background | 24.6 mJ | 317.9 mJ |
| precharge background | 374.3 mJ | 174.3 mJ |
| refresh | 104.1 mJ | 104.7 mJ |
| read + write + act + pre | ~0 | ~1.9 mJ |

  - When there is traffic, the banks spend more time with a row open (active standby), which costs more than with rows closed. The current setup does not turn on DRAM power-down (the power-down energy is all 0), so this background energy may be higher than in reality
- L2 leakage is only about 8% of the total (88 out of 1,112 mJ for vec192), while DRAM is about 45%. So if a wrong shutdown makes DRAM work more, all the saving is lost. Dynamic keeps the run time, so total energy still drops by 0.9–5.8%
- The power gate also has a cost. The sleep transistor takes extra area and makes access a little slower. When a way is turned back on, there is a large inrush current and we must wait for the voltage to become stable. After that the way is empty, so there is an extra burst of cold misses. This gives a break-even condition: a way should only be turned off if the time it stays off is longer than T_min = E_flush / P_way
  - Putting in the numbers: P_way ≈ (0.1472 − 0.0270) / 15 ≈ 8 mW, and writing one line to DRAM costs about 2.4 nJ (0.0308 mJ / 13,057 lines in gemm64). In the worst case, one way has all 1024 lines dirty, so E_flush ≈ 2.4 µJ, which gives T_min ≈ 0.3 ms, or about 30,000 cycles at 100 MHz. A way that is turned off must stay off for at least one controller interval (1M cycles) before it can be turned on again, which is much longer than T_min, so the break-even condition is always met. Note that this T_min does not include the energy to turn the way back on
- P_leak(W) comes from McPAT by building a W-way array again, so it is an upper bound: it does not include the leakage through the sleep transistor or the energy to turn a way back on. This week the controller never had to turn a way back on, so the turn-on energy does not affect the results yet

# Conclusion
- After the fix, the results make more sense. For a workload with high L2 traffic like vec192, going past the cliff makes the run 14% slower (at 100 MHz) up to 128% slower (at 1 GHz), and at 100 MHz it also uses 31% more total energy. Dynamic keeps the right W14, so it is not slower and still saves 11% of L2 leakage
- Scalar workloads like GEMM and conv almost do not use L2, so going down to W1 is still correct: L2 leakage drops by 80%, total energy drops by about 5.7%, and the slowdown is under 0.1%
- The ATD with LRU is a bit too careful compared with the L2 using Tree-PLRU, most clearly in mix

# Model limitations
- Measured: miss rate, number of accesses and time in gem5. Assumed: 100 MHz clock, L2/NoC latency in ns, 25 ns from L2 to DRAM, 32-cycle divider. Computed: leakage by W (McPAT) and flush energy
- gem5 classic allows only one line size, so L1 has to use 64 B (the RTL uses 16 B). Because of this, the number of L2 accesses for sequential reads is up to 4 times lower than on the real chip
- `mostly_incl` in gem5 moves Modified lines up to L1, so writebacks repeat; the cache has no port/bank limit; SE mode has no TLB and gives physical pages in order
- Turning ways off and on happens instantly, and the flush takes no time (only its energy is added afterwards)

# Next steps and questions
- Make the ATD model Tree-PLRU (or try margin 0), then run mix again
- Add a workload with a phase where demand goes up (idle first, then vec) to test the turn-on path
- I would like more advice from anh Nam, because right now I am not sure what to do next
