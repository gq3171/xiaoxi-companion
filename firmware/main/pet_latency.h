#pragma once
#include <stdint.h>
typedef enum {PET_TIME_ASR_START,PET_TIME_ASR_END,PET_TIME_LLM_START,PET_TIME_LLM_TEXT,PET_TIME_LLM_END,PET_TIME_TTS_START,PET_TIME_TTS_AUDIO,PET_TIME_SPEAKER} pet_time_point_t;
void pet_latency_begin(uint32_t generation,int64_t last_voice_us,int64_t captured_us);
void pet_latency_mark(uint32_t generation,pet_time_point_t point);
