#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "cJSON.h"

void pet_cloud_begin_turn(uint32_t generation);
bool pet_cloud_cancelled(void);
bool pet_cloud_network_active(void);
/* Caller owns returned strings. MiniMax handles reflection and autonomous plans. */
char *pet_cloud_dialogue(const char *system_prompt, const cJSON *history);
char *pet_cloud_minimax(const char *system_prompt, const char *request, bool reflection);
char *pet_cloud_search(const char *query);
int pet_cloud_transcribe(const int16_t *mono, int samples, char *text, int text_len);
int pet_cloud_chat(const char *system_prompt, const char *user_text, char *reply, int reply_len);
int pet_cloud_speak(const char *text, int16_t *mono, int max_samples);
/* Explicit catalogue voice for preview; does not change the saved choice. */
int pet_cloud_speak_voice(const char *text, const char *voice_id, int16_t *mono, int max_samples);
typedef bool (*pet_audio_sink_fn)(const int16_t *mono, size_t samples, void *user);
/* Streams bounded PCM chunks; success requires provider's terminal event. */
int pet_cloud_speak_stream(const char *text, pet_audio_sink_fn sink, void *user);
/* Fixed provider URLs signed by the owner-verification module, no bearer header. */
char *pet_cloud_signed_json(const char *url, const cJSON *request);
/* Fixed configured HTTPS computer bridge only; model cannot supply a URL/key. */
bool pet_cloud_computer_configured(void);
char *pet_cloud_computer(const char *operation, const cJSON *request);
char *pet_cloud_brain(const char *operation, const cJSON *request);
bool pet_cloud_ready(void);
void pet_cloud_input_source(bool microphone);
char *pet_cloud_birth(const char *system_prompt,const char *request);
