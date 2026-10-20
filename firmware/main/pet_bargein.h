#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool playing, trusted;
    int good_frames;
    int64_t started, tail_until;
} pet_bargein_t;
bool pet_bargein_voice(pet_bargein_t *state, bool playing, bool speech,
                       float raw_rms, float reference_rms, float clean_rms, int64_t now);
