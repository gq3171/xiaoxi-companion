#pragma once
#include <stddef.h>
#include <stdbool.h>

void pet_runtime_start(void);
void pet_runtime_prepare(void);
bool pet_runtime_audio_allowed(void);
bool pet_runtime_reminder_ready(void);
void pet_runtime_notify(const char *event);
void pet_runtime_quiet(int minutes);
void pet_runtime_voice_override(int minutes);
void pet_runtime_set_quiet_hours(const char *hhmm_range);
void pet_runtime_quiet_hours(char *out, size_t capacity);
