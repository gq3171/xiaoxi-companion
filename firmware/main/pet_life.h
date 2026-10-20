#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "cJSON.h"

/* Runtime worker owns all state and flash writes. No raw dialogue/audio here. */
int pet_life_start(void);
bool pet_life_active(void);
/* One bounded virtual goal, 1..4 whitelisted steps, saved before dispatch. */
int pet_life_plan(const cJSON *plan, int64_t epoch, bool replace);
/* handoff pauses an old plan without retargeting a newer shared-room action. */
int pet_life_control(const char *control);
void pet_life_tick(uint32_t now, int64_t epoch, bool engaged, bool night, bool tired);
void pet_life_context(char *out, size_t capacity);
const char *pet_life_rules(void);
