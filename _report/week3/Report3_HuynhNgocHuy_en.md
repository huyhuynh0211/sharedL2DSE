# Summary

- **Goal:** reduce the leakage power of a shared 1 MiB, 16-way L2 cache. Two methods are tested on 5 workloads (gemm256, gemm768, conv64, conv256, mixai): **Dynamic** (turn off ways) and **Drowsy** (lower the voltage).
- **Dynamic:** a controller runs every 1M cycles and uses an ATD to predict how many misses each number of ways would give. Then it turns off ways that are not needed.
  - L2 leakage drops by 71–80%.
  - The L2 miss rate becomes very high (up to about 97%), but run time only increases by 0.21–1.06%, because there are very few L2 accesses.
  - Total energy only drops by 2.9–4.6%, because L2 leakage is only about 7% of the chip, and the extra misses make DRAM and the core use more energy.
- **Drowsy:** lines go to a low voltage (0.3 V) and keep their data.
  - L2 misses stay the same and run time grows by less than 0.01%.
  - Only 0.01–0.02% of lines are awake at any time.
  - The savings are capped at about 75.6% by the always-awake tags and the leakage factor r, not by the sleep policy.
- **Still to do:** McPAT cannot model Drowsy, so a formula for Drowsy energy still needs to be made.

---

**General configuration:**
- The CPU follows Tiến Anh's configuration
- Shared L2: 1 MiB, 16-way, 64 B line, 1024 sets, split into **4 banks** by address bits 14–15. Tree-PLRU, non-inclusive (`mostly_incl`).
- DDR4-2400, 1 GHz, 10M-cycle warmup.

**Workload:** tiled GEMM and conv int8

| Name | Command | 4-core footprint |
|---|---|---|
| gemm256 | `gemm_int8 256` | 320 KiB (~5 ways) |
| gemm768 | `gemm_int8 768` | 896 KiB (~14 ways) |
| conv64 | `conv_int8 64` | ~185 KiB (~3 ways) |
| conv256 | `conv_int8 256` | ~665 KiB (~11 ways) |
| mixai | 2 cores gemm768 + 2 cores conv256 | ~780 KiB (~12 ways) |

**Baseline:** 16 ways always on, no drowsy

**Energy:** McPAT 22 nm, similar to week 2

# Dynamic

- L2 always has 16 ways. We let a controller run every 1M cycles, and it decides how many ways to turn on. The problem is that we need to know: if only W ways are on, how many misses will L2 have? We want to choose the smallest W that does not make the program more than 1% slower. The hard part is that the real cache only runs at one value of W. If 4 ways are on, we only see the misses of 4 ways, and we do not know what 8 ways would give. To know everything, we would have to run 16 caches in parallel, which is too expensive -> so we need an ATD (Auxiliary Tag Directory). It simply simulates a 16-way cache running LRU, holds only tags and no data, watches the L2 access stream and does not affect the main cache -> so we can know the misses for every W.
- An LRU cache with W ways always keeps exactly the W most recently used lines of a set, which means positions 0 to W−1 (because of LRU). So an access at position p (exactly p other lines were used more recently) will:
  - hit if the cache has W-1 ≥ p ways
  - miss if the cache has W ≤ p ways
- After we have the ATD, we choose the smallest W such that the extra misses do not go over the allowed limit (1%, 2%, ...): *extra_miss(W) × tmem / 4 cores ≤ smax × interval*. tmem = the average number of cycles that an L2 miss delays things (the difference between getting the data from L2 and going down to DRAM to get it).
- Finally, the decision to turn ways on and off: a way is only turned off when 3 intervals in a row (1 interval = 1,000,000 cycles) all agree, and when a way is turned off, the dirty lines in that way must be written to memory and the lines cleared. There are also cases where it goes down to W1 right away: if there are fewer than 1000 L2 accesses per interval and the extra miss rate is still within the limit.
- The gem5 config needs to be fixed so that Tree-PLRU turns to the branch that still has ways turned on.

`dyn` is the default setting. `dyn idle0` is the version where the number of ways is decided only by the ATD.

| Workload | Run | Average W | Ways over time | L2 miss % | L1D miss latency | Time vs. W16 |
|---|---|---|---|---|---|---|
| gemm256 | W16 | 16 | | 3.35 | 12.3 | — |
| | dyn | 3.00 | 16, 16, then W1 | 81.92 | 62.7 | **+0.98%** |
| gemm768 | W16 | 16 | | 1.48 | 12.4 | — |
| | dyn | 1.65 | 16, 16, 13, then W1 | 95.18 | 68.1 | **+1.06%** |
| | dyn idle0 | 5.34 | 16, 16, then **W5** | 68.42 | 50.2 | **+0.71%** |
| conv64 | W16 | 16 | | 5.39 | 12.6 | — |
| | dyn | 3.00 | 16, 16, then W1 | 42.55 | 33.5 | **+0.21%** |
| conv256 | W16 | 16 | | 1.18 | 12.1 | — |
| | dyn / dyn idle0 | 1.33 | 16, 16, then W1 | 97.09 | 65.3 | **+0.48%** |
| mixai | W16 | 16 | | 1.44 | 12.3 | — |
| | dyn | 1.33 | 16, 16, then W1 | 95.75 | 66.8 | **+0.48%** |
| | dyn idle0 | 1.63 | mostly W1, sometimes W3 / W6 | 95.11 | 66.8 | **+0.48%** |

  - The miss rate is high, but if we look at the time compared to W16, it only increases by 1.06% for gemm768. Working it out, the time per extra miss is 61/4 = 15.25 cycles -> about 45,000 extra misses over the whole 64M-cycle run. If the miss rate = 95%, total L2 accesses are about 48,000, which is 750 per 1M cycles -> so 95% is only a very small number of accesses that miss.

| - | L2 acc | L2 miss | miss % |
|---|---|---|---|
| W16 | 52,274 | 774 | 1.48 |
| dyn | 52,274 | 49,755 | 95.18 |

  - The other results can be explained in the same way.
  - The column we care about most is the time difference compared to W16. It is not big, so the high miss numbers do not mean much.

L2 leakage of the dynamic version = Σ P_leak(W) × time spent at each W. P_leak(W) is taken from McPAT for a 4-bank L2, changing only the L2 setting:

| W | 16 | 8 | 4 | 2 | 1 |
|---|---|---|---|---|---|
| P_leak L2 (W) | 0.1472 | 0.0799 | 0.0512 | 0.0342 | 0.0270 |

| Workload | Run | L2 leakage mJ (reduction) | Rest mJ | Total mJ (reduction) | Difference vs. W16: core / DRAM, mJ |
|---|---|---|---|---|---|
| gemm256 | W16 | 2.232 | 29.179 | 31.411 | |
| | dyn | 0.653 (**−70.7%**) | 29.857 | 30.510 (**−2.87%**) | +0.11 / +0.51 |
| gemm768 | W16 | 9.480 | 124.002 | 133.482 | |
| | dyn | 2.101 (**−77.8%**) | 126.913 | 129.014 (**−3.35%**) | +0.49 / +2.14 |
| | dyn idle0 | 3.963 (−58.2%) | 126.437 | 130.400 (−2.31%) | +0.33 / +1.90 |
| conv64 | W16 | 2.254 | 28.945 | 31.199 | |
| | dyn | 0.654 (**−71.0%**) | 29.169 | 29.823 (**−4.41%**) | +0.02 / +0.18 |
| conv256 | W16 | 13.204 | 169.554 | 182.758 | |
| | dyn | 2.672 (**−79.8%**) | 171.672 | 174.344 (**−4.60%**) | +0.31 / +1.62 |
| mixai | W16 | 13.204 | 168.124 | 181.329 | |
| | dyn | 2.672 (**−79.8%**) | 171.575 | 174.247 (**−3.91%**) | +0.31 / +2.93 |

- Dynamic cuts L2 leakage by 71–80%, but L2 leakage is only about 7% of the chip, and the extra misses make DRAM and the core use more energy, so the total only drops by 2.9–4.6%.

# Drowsy
- Leakage current drops a lot when the supply voltage is lowered. An SRAM cell can still keep its data at a voltage much lower than the voltage needed to read or write. Drowsy cache [https://web.eecs.umich.edu/~manowar/publications/drowsy-caches-ISCA2002.pdf]
- The paper talks about awake tags and drowsy tags. For awake, the voltage is always 1 V, but for drowsy it is lowered to 0.3 V -> leakage power drops a lot but the data is still kept. An awake way is on all the time without rest -> high leakage power -> wasteful but fast, while a drowsy way is still fast but cuts leakage power by a lot.
- To summarize:
  - Problem
    - L2 has 16,384 lines, but at any moment only very few lines are being used, while every line leaks power at 1 V.
    Way shutdown cuts the power, so data is lost -> misses go up -> DRAM uses more energy. We need to cut leakage without losing data.
    Idea: do not cut the power, lower the voltage instead. An SRAM cell at 0.3 V still keeps its data but leaks very little. To read or write, it must be raised back to 1 V.
  - Where the difficulty is
    - Which lines should sleep? If we predict which lines will be used soon, it costs hardware -> so we choose "simple" to avoid having to predict.
  - Simple
    - After every window of N cycles (4000 or 16000), all lines go drowsy, whether they are being used or not
    - A line that is accessed -> is woken up, and stays awake until the end of the window.
    - It is based on locality: a line that was just used will probably be used again soon, and a line that has not been touched for a long time can sleep without problems. It only needs one shared window counter.

    | Time | Event | Status of A | Penalty |
    |---|---|---|---|
    | 0 | Window 0 starts | asleep | |
    | 100 | Access A (hit) | asleep -> awake | +wake_lat |
    | 500 | Access A | awake | 0 |
    | 3900 | Access A | awake | 0 |
    | 4000 | Window 0 ends, all lines go back to sleep | asleep | |
    | 4200 | Access A | asleep -> awake | +wake_lat |
  - Trade-offs
    - Hit on a sleeping line: the voltage of the data array must be raised -> an extra delay of wake_lat (1 or 2 cycles)
    - Miss, loading a line into a sleeping cell: raising the voltage runs at the same time as waiting for DRAM -> no extra penalty
    - Tags are always awake ("awake tags") -> we know hit or miss right away, with no need to wake the tag first. In return, the tag array still leaks fully (this is f_tag)
    - Tag and data are accessed at the same time: hit latency = max(tag 2, data 6 + wake), so the penalty is added on the data side. That is why L1D miss latency goes up by about wake_lat. The latency increase is about = wake_lat * (fraction of L1D misses that are L2 hits)

| Workload | Run | L2 miss % | L1D miss latency | Time vs. W16 | a (awake lines) | Hits on sleeping lines |
|---|---|---|---|---|---|---|
| gemm256 | w4000 | 3.35 (W16: 3.35) | 13.3 (12.3) | +0.002% | 0.020% | 25,038 |
| gemm768 | off (`window 0`) | 1.48 | 12.4 | 0 (same as W16) | — | — |
| | w4000 | 1.71 (W16: 1.48) | 13.5 (12.4) | +0.006% | 0.020% | 103,302 |
| | w16000 | 1.71 | 13.5 | +0.006% | 0.08% | 103,301 |
| | w4000, wake 2 | 1.69 | 14.5 | +0.007% | 0.020% | — |
| conv64 | w4000 | 5.39 (5.39) | 13.5 (12.6) | −0.001% | 0.011% | 13,220 |
| conv256 | w4000 | 1.17 (1.18) | 13.1 (12.1) | +0.000% | 0.010% | 72,063 |
| mixai | w4000 | 1.50 (1.44) | 13.3 (12.3) | +0.002% | 0.012% | 87,677 |
  - Drowsy keeps L2 misses the same and only slows the program by less than 0.01%, because the wake-up penalty is only 1–2 cycles on very few L2 accesses. Only 0.01–0.02% of lines are awake, and making the window 4 times longer does not remove any wake-ups, which shows that L2 has almost no short-term reuse. The savings are capped at about 75.6% by the always-awake tag part and the leakage factor r, not by the sleep policy

- As for measuring leakage power, it cannot be done with McPAT, because McPAT has no option for Drowsy, so I need to find a way to make my own formula for this part. I am also studying how to estimate the energy as accurately as possible.
