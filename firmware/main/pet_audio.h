#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define PET_SAMPLE_RATE 16000
#define PET_DEFAULT_VOLUME 5
#define PET_VOLUME_STEP 5

void pet_audio_start(void);
int pet_audio_get_volume(void);
/* Adjust 0..100 volume, persist it, and return the resulting volume (-1 on error). */
int pet_audio_adjust_volume(int delta);
void pet_audio_allow_output(bool allowed);
bool pet_audio_output_allowed(void);
int pet_audio_read_frame(int16_t *stereo, int samples);
int pet_audio_play_turn(const int16_t *mono, size_t samples, uint32_t generation);
bool pet_audio_stream_begin(uint32_t generation);
bool pet_audio_stream_begin_media(uint32_t generation);
bool pet_audio_stream_ok(void);
bool pet_audio_stream_write(const int16_t *mono, size_t samples, uint32_t generation);
void pet_audio_stream_end(bool complete);
/* Nonblocking local wake reply; obeys mute, volume and turn cancellation. */
bool pet_audio_wake_ack(uint32_t generation);
bool pet_audio_playing(void);
int pet_audio_listen(int16_t *mono, size_t max_samples);
void pet_audio_play(const int16_t *mono, size_t samples);
void pet_audio_stop(void);
