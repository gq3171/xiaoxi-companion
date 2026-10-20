#pragma once
#include <stdbool.h>
#include "cJSON.h"
/* ASR is a candidate, never identity evidence. A valid direct response is
 * required before committing it to history or owner reflection. */
bool pet_input_direct(const cJSON *answer, bool microphone);
bool pet_input_remember(const cJSON *answer, bool microphone, bool owner);
/* Textual echo screening is only a short-lived playback guard, not identity. */
bool pet_input_echo_candidate(const char *candidate,const char *recent_reply);
