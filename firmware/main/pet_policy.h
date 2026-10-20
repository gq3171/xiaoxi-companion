#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int quiet_start; /* Minutes since local midnight. */
    int quiet_end;
    int daily_limit;
    int min_gap_minutes;
} pet_policy_t;

bool pet_policy_quiet(const pet_policy_t *policy, int minute);
/* No valid wall clock means silent output, regardless of monotonic uptime. */
bool pet_policy_audio(const pet_policy_t *policy, bool clock_valid, int minute,
                      int64_t now_us, int64_t quiet_until_us, int64_t voice_until_us);
int pet_policy_backoff_minutes(int ignored_count, int base_minutes);
