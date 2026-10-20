#include "pet_latency.h"
#include <stdatomic.h>
#include "esp_timer.h"
#include "esp_log.h"
/* Begin runs between turns, after the old audio worker has drained/stopped. */
static atomic_uint s_generation,s_seen;
static int64_t s_last_voice;
void pet_latency_begin(uint32_t generation,int64_t last_voice_us,int64_t captured_us)
{
    s_last_voice=last_voice_us;atomic_store(&s_seen,0);atomic_store(&s_generation,generation);
    ESP_LOGI("pet_latency","turn=%lu endpoint_ms=%lld",(unsigned long)generation,(long long)((captured_us-last_voice_us)/1000));
}
void pet_latency_mark(uint32_t generation,pet_time_point_t point)
{
    if(generation!=atomic_load(&s_generation) || !s_last_voice || point>PET_TIME_SPEAKER)return;
    unsigned bit=1u<<point;
    if(atomic_fetch_or(&s_seen,bit)&bit)return;
    const char *names[]={"asr_start","asr_end","llm_start","llm_text","llm_end","tts_start","tts_audio","speaker"};
    ESP_LOGI("pet_latency","turn=%lu phase=%s since_voice_ms=%lld",(unsigned long)generation,names[point],
        (long long)((esp_timer_get_time()-s_last_voice)/1000));
}
