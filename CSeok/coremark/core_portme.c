/*
 * Linux (gem5 SE mode) port of CVA6's core_portme.c.
 * Only the platform layer changes: timing uses clock() instead of the
 * bare-metal mcycle counter, and printing goes to normal printf.
 * The benchmark files (core_list_join.c, core_matrix.c, core_state.c,
 * core_util.c, coremark_main.c) are unchanged from the CVA6 repo.
 */
#include <time.h>
#include "coremark.h"

ee_u32 default_num_contexts = 1;

static clock_t start_time_val, stop_time_val;

#if VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PERFORMANCE_RUN
volatile ee_s32 seed1_volatile = 0x0;
volatile ee_s32 seed2_volatile = 0x0;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PROFILE_RUN
volatile ee_s32 seed1_volatile = 0x8;
volatile ee_s32 seed2_volatile = 0x8;
volatile ee_s32 seed3_volatile = 0x8;
#endif
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;

void portable_init(core_portable *p, int *argc, char *argv[])
{
    (void)p;
    (void)argc;
    (void)argv;
}

void portable_fini(core_portable *p)
{
    (void)p;
}

void start_time(void)
{
    start_time_val = clock();
}

void stop_time(void)
{
    stop_time_val = clock();
}

CORE_TICKS get_time(void)
{
    return (CORE_TICKS)(stop_time_val - start_time_val);
}

secs_ret time_in_secs(CORE_TICKS ticks)
{
    return ((secs_ret)ticks) / CLOCKS_PER_SEC;
}
