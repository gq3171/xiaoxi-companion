#pragma once

#include <stdint.h>
#include <stdbool.h>

#define PET_VOICE_BANDS 16
typedef struct {
    float rms;
    int clipped_permille;
    int active_ms;
} pet_voice_stats_t;
pet_voice_stats_t pet_voice_stats(const int16_t *mono, int samples);

void pet_voice_measure(const int16_t *mono, int samples, float band[PET_VOICE_BANDS]);
void pet_voice_save(const float band[PET_VOICE_BANDS]);
int pet_voice_has(void);
float pet_voice_match(const int16_t *mono, int samples);
/* Content gate for short replies inside an already authenticated session. */
bool pet_voice_reply_usable(const int16_t *mono, int samples);
bool pet_voice_usable(const int16_t *mono, int samples);
