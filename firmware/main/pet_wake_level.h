#pragma once
#include <stdint.h>
#include <stddef.h>
typedef struct { float gain; unsigned quiet_frames; } pet_wake_level_t;
/* Only the local recognizer's frame is changed; never the recorded ASR audio. */
void pet_wake_level(pet_wake_level_t *state,int16_t *pcm,size_t samples);
