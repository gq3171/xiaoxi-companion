#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

size_t pet_speech_chunk(const char *text, size_t max_bytes);
/* Returns 0 when fully delivered/displayed, -1 on failure or interruption. */
int pet_speech_say(const char *text, uint32_t generation, int16_t *pcm, int max_samples);
size_t pet_speech_delivered_bytes(void);
/* True only when this delivery actually submitted PCM to the audio sink. */
bool pet_speech_audible(void);
