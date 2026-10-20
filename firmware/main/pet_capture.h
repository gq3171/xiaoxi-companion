#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "freertos/FreeRTOS.h"

typedef struct {
    int16_t *pcm;
    int samples;
    uint32_t generation;
    int64_t last_voice_us, captured_us;
    bool too_long;
    bool deferred; /* Recorded during an earlier reply; worker claims it afterwards. */
    bool overlap; /* Unconfirmed speech during playback; never an immediate interruption. */
} pet_utterance_t;

int pet_capture_start(void);
bool pet_capture_started(void);
bool pet_capture_listening(void);
/* A complete, current utterance is waiting for the worker (no PCM access). */
bool pet_capture_pending(void);
int pet_capture_recorded_ms(void);
/* Keep reading hardware, but do not start turns during enrollment prompts or verification. */
void pet_capture_pause_turns(bool paused);
bool pet_capture_take(pet_utterance_t *utterance, TickType_t wait);
void pet_capture_discard(void);
/* Playback reference is delivered before each corresponding I2S write. */
void pet_capture_reference(const int16_t *pcm, size_t samples, bool restart);

/* Preparation is not audible playback: a new onset must not cancel it. */
void pet_capture_reply_pending(bool pending, uint32_t generation);
bool pet_capture_claim(pet_utterance_t *utterance);
