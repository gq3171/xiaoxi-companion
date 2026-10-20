#pragma once

#include <stdint.h>
#include <stdbool.h>

void pet_setup_wifi(void);
bool pet_setup_connected(void);
typedef struct { bool connected,connecting; int rssi; } pet_network_state_t;
/* Cached Wi-Fi link/IP state; safe to read without Wi-Fi calls on the UI task. */
pet_network_state_t pet_setup_network_state(void);
int pet_setup_wifi_configure(void);
void pet_setup_wifi_poll(void);
int pet_setup_keys(bool force);
int pet_setup_soul(int16_t *mic, int mic_cap, int16_t *speaker, int speaker_cap);
int pet_setup_voice(int16_t *speaker, int speaker_capacity, bool force);
int pet_setup_voice_keys(int16_t *speaker, int speaker_capacity);
void pet_setup_cancel(void);
void pet_setup_keyboard(void);
