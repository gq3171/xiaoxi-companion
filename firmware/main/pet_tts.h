#pragma once
#include <stddef.h>
#include <stdint.h>

#define PET_TTS_MAX_ACK_SAMPLES 48000
/* Immutable official Chinese system-voice catalogue. */
int pet_tts_count(void);
const char *pet_tts_id(int index);
const char *pet_tts_label(int index);
int pet_tts_find(const char *id);
int pet_tts_current(void);
void pet_tts_start(void);
/* Atomically persist voice + matching 16kHz PCM cue; failure keeps old choice. */
int pet_tts_save(int index, const int16_t *pcm, size_t samples);
size_t pet_tts_ack_size(void);
size_t pet_tts_ack_read(size_t offset, int16_t *out, size_t capacity);
