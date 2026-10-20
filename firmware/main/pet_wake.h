#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool pet_wake_init(void);
bool pet_wake_ready(void);
bool pet_wake_feed(const int16_t *pcm,size_t samples);
void pet_wake_reset(void);

void pet_wake_set_name(const char *name);
void pet_wake_phrase(char *out,size_t size);

/* Public synthetic fixture only, for developer board diagnostics; never owner audio. */
const void *pet_wake_test_audio(const char *fixture,size_t *bytes);
