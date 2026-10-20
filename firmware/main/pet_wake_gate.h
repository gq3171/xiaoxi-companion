#pragma once
#include <stdbool.h>
#include <stdint.h>
void pet_wake_require(bool required);
bool pet_wake_required(void);
bool pet_wake_active(uint32_t now_ms);
void pet_wake_open(uint32_t now_ms);
void pet_wake_hold(bool holding,uint32_t now_ms);
void pet_wake_activity(uint32_t now_ms);
void pet_wake_sleep(void);
void pet_wake_end_conversation(void);
/* Viewing doesn't keep the microphone open. An explicit return resumes the
 * conversation unless the owner ended it or requested rest in the meantime. */
void pet_wake_media_begin(void);
bool pet_wake_media_return(uint32_t now_ms);

void pet_wake_heard(uint32_t now_ms);
bool pet_wake_feedback(uint32_t now_ms);
/* Changes only on explicit wake/open or model-accepted conversation. */
unsigned pet_wake_interactions(void);
unsigned pet_wake_activations(void);
void pet_wake_rest(void);
bool pet_wake_resting(void);
