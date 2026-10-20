#pragma once
#include <stdint.h>
typedef struct { uint32_t frames,flushes,pixels; uint64_t transfer_us; } pet_display_profile_t;
void pet_display_start(void);
/* Read on the LVGL thread; counts actual completed flushes, not target FPS. */
pet_display_profile_t pet_display_profile(void);

/* Sensor task requests; only the LVGL thread changes panel/touch mapping. */
void pet_display_request_rotation(unsigned degrees);
unsigned pet_display_rotation(void);
