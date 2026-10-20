#include "pet_capture.h"
#include <math.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include "esp_aec.h"
#include "esp_vad.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "pet_audio.h"
#include "pet_turn.h"
#include "pet_util.h"
#include "pet_bargein.h"
#include "esp_timer.h"
#include "sdkconfig.h"
#include "pet_wake.h"
#include "pet_wake_gate.h"

#define FRAME 512
#define PRE_FRAMES 8
#define MAX_SAMPLES (PET_SAMPLE_RATE * 20)
#define REF_SAMPLES (FRAME * 8)
#define END_SILENCE_FRAMES 50 /* 1.6 seconds: allow breathing and thinking pauses. */
#define KEEP_TAIL_FRAMES 6
static const char *TAG = "pet_capture";
static QueueHandle_t s_queue;
static atomic_bool s_listening;
static atomic_int s_recorded_samples;
static atomic_bool s_paused;
static atomic_uint s_reply_generation;
static int16_t *s_reference;
static size_t s_ref_read, s_ref_count;
static portMUX_TYPE s_reference_lock = portMUX_INITIALIZER_UNLOCKED;
static aec_handle_t *s_aec;
static vad_handle_t s_vad;

bool pet_capture_started(void) { return s_queue != NULL; }
bool pet_capture_listening(void) { return atomic_load(&s_listening); }
int pet_capture_recorded_ms(void) { return atomic_load(&s_recorded_samples) * 1000 / PET_SAMPLE_RATE; }
void pet_capture_pause_turns(bool paused) { atomic_store(&s_paused, paused); }

void pet_capture_reply_pending(bool pending,uint32_t generation)
{
    atomic_store(&s_reply_generation,pending?generation:0);
}

bool pet_capture_claim(pet_utterance_t *utterance)
{
    if(!utterance)return false;
    if(utterance->deferred) {
        /* Local wake cues also use the independent player. A candidate must
         * not cancel one just because the cloud worker is currently idle. */
        if(utterance->overlap&&pet_audio_playing())return false;
        uint32_t claimed=pet_turn_claim(utterance->generation);
        if(!claimed)return false;
        utterance->generation=claimed;utterance->deferred=false;
    }
    return pet_turn_valid(utterance->generation);
}

void pet_capture_reference(const int16_t *pcm, size_t samples, bool restart)
{
    if (!s_reference) return;
    portENTER_CRITICAL(&s_reference_lock);
    if (restart) {
        s_ref_read = 0; s_ref_count = FRAME;
        memset(s_reference, 0, FRAME * sizeof(int16_t));
    }
    for (size_t i = 0; i < samples; i++) {
        if (s_ref_count == REF_SAMPLES) { s_ref_read = (s_ref_read + 1) % REF_SAMPLES; s_ref_count--; }
        s_reference[(s_ref_read + s_ref_count) % REF_SAMPLES] = pcm[i]; s_ref_count++;
    }
    portEXIT_CRITICAL(&s_reference_lock);
}

static void read_reference(int16_t *frame)
{
    portENTER_CRITICAL(&s_reference_lock);
    for (int i = 0; i < FRAME; i++) {
        frame[i] = s_ref_count ? s_reference[s_ref_read] : 0;
        if (s_ref_count) { s_ref_read = (s_ref_read + 1) % REF_SAMPLES; s_ref_count--; }
    }
    portEXIT_CRITICAL(&s_reference_lock);
}

bool pet_capture_pending(void)
{
    pet_utterance_t utterance;
    return s_queue && xQueuePeek(s_queue, &utterance, 0) == pdTRUE && !utterance.overlap && pet_turn_valid(utterance.generation);
}

bool pet_capture_take(pet_utterance_t *utterance, TickType_t wait)
{
    return s_queue && xQueueReceive(s_queue, utterance, wait) == pdTRUE;
}

void pet_capture_discard(void)
{
    pet_utterance_t old;
    while (pet_capture_take(&old, 0)) free(old.pcm);
}

static float energy(const int16_t *pcm)
{
    double sum = 0;
    for (int i = 0; i < FRAME; i++) sum += (double)pcm[i] * pcm[i];
    return sqrtf(sum / FRAME);
}

static void capture(void *arg)
{
    int16_t *stereo = heap_caps_aligned_alloc(16, FRAME * 2 * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    int16_t *mic = heap_caps_aligned_alloc(16, FRAME * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    int16_t *ref = heap_caps_aligned_alloc(16, FRAME * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    int16_t *clean = heap_caps_aligned_alloc(16, FRAME * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    int16_t *pre = pet_alloc(FRAME * PRE_FRAMES * sizeof(int16_t));
    assert(stereo && mic && ref && clean && pre);
    memset(pre, 0, FRAME * PRE_FRAMES * sizeof(int16_t));
    size_t pre_index = 0;
    float noise = 50, peak_clean = 0;
    int16_t vad_buffer[1024];
    size_t vad_used = 0;
    int voice_frames = 0, quiet_frames = 0, last_voice_sample = 0;
    pet_utterance_t current = {0};
    pet_bargein_t bargein = {0};
    bool was_paused = false, was_awake=true;
    int64_t next_metrics = 0, echo_until = 0;
    while (true) {
        if (pet_audio_read_frame(stereo, FRAME * 2) != 0) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        for (int i = 0; i < FRAME; i++) mic[i] = ((int)stereo[i * 2] + stereo[i * 2 + 1]) / 2;
        read_reference(ref);
        bool playing = pet_audio_playing();
        int64_t metric_now = esp_timer_get_time();
        float reference_rms=energy(ref);
        if(playing || reference_rms>1)echo_until=metric_now+500000;
        /* Keep the adaptive filter running, but its nonlinear suppressor must
         * not erase quiet near-end speech when there is no playback reference.
         * Retain cancellation through the measured playback tail. */
        aec_process(s_aec, mic, ref, clean);
        int aec_rms=(int)energy(clean);
        bool echo_path=playing || metric_now<echo_until;
        if(!echo_path)memcpy(clean,mic,FRAME*sizeof(int16_t));
        float clean_rms=energy(clean);if(clean_rms>peak_clean)peak_clean=clean_rms;
        if (metric_now >= next_metrics) {
            double l=0,r=0,cross=0; int clipped=0;
            for(int i=0;i<FRAME;i++) {
                double a=stereo[2*i],b=stereo[2*i+1]; l+=a*a;r+=b*b;cross+=a*b;
                if(abs(stereo[2*i])>=32700 || abs(stereo[2*i+1])>=32700)clipped++;
            }
            ESP_LOGI(TAG,"MIC l=%d r=%d mix=%d clean=%d peak_clean=%d aec=%d echo=%d corr=%d clip=%d noise=%d awake=%d playing=%d",
                (int)sqrt(l/FRAME),(int)sqrt(r/FRAME),(int)energy(mic),(int)clean_rms,(int)peak_clean,aec_rms,echo_path,
                l*r>0?(int)(100*cross/sqrt(l*r)):0,clipped*1000/FRAME,(int)noise,
                pet_wake_active((uint32_t)(metric_now/1000)),pet_audio_playing());
            next_metrics=metric_now+2000000;
            peak_clean=0;
        }
        if (atomic_load(&s_paused)) {
            if (!was_paused) {
                free(current.pcm); current = (pet_utterance_t){0};
                atomic_store(&s_listening, false); atomic_store(&s_recorded_samples, 0);
                voice_frames = quiet_frames = 0; vad_used = 0;
                memset(pre, 0, FRAME * PRE_FRAMES * sizeof(int16_t));
            }
            was_paused = true; continue;
        }
        was_paused = false;
        uint32_t wake_now=(uint32_t)(esp_timer_get_time()/1000);
        memcpy(vad_buffer + vad_used, clean, FRAME * sizeof(int16_t)); vad_used += FRAME;
        bool speech = false;
        while (vad_used >= 480) {
            if (vad_process(s_vad, vad_buffer, PET_SAMPLE_RATE, 30) == VAD_SPEECH) speech = true;
            vad_used -= 480; memmove(vad_buffer, vad_buffer + 480, vad_used * sizeof(int16_t));
        }
        float rms = clean_rms;
        /* Learn room noise while waiting for a wake too. Quiet speech rejected
         * by the energy threshold must not raise its own future threshold. */
        if (!current.pcm && !speech && !playing && esp_timer_get_time() >= bargein.tail_until)
            noise = noise * 0.98f + fminf(rms, 1000) * 0.02f;
        float threshold = fmaxf(120, noise * 2.5f);
        if(!current.pcm && !pet_wake_active(wake_now)){
            if(was_awake){
                free(current.pcm);current=(pet_utterance_t){0};voice_frames=quiet_frames=0;vad_used=0;
                atomic_store(&s_listening,false);atomic_store(&s_recorded_samples,0);
                memset(pre,0,FRAME*PRE_FRAMES*sizeof(int16_t));pet_wake_reset();
                ESP_LOGI(TAG,"waiting for offline wake; no utterance uploads");
            }
            was_awake=false;
            if(!pet_audio_playing()&&pet_wake_feed(clean,FRAME)){
                uint32_t generation=pet_turn_next();pet_capture_discard();
                pet_wake_heard(wake_now);pet_wake_reset();pet_audio_wake_ack(generation);
                ESP_LOGI(TAG,"offline wake detected; conversation window open");
            }
            continue;
        }
        was_awake=true;
        bool voice = pet_bargein_voice(&bargein, playing, speech && rms > threshold,
                                       energy(mic), reference_rms, rms, esp_timer_get_time());
        if (voice) voice_frames++; else voice_frames = 0;
        if (!current.pcm && voice_frames >= 3) {
            ESP_LOGI(TAG, "voice onset (%s) rms=%d threshold=%d noise=%d", playing ? "AEC speech candidate; reply continues" : "idle",(int)rms,(int)threshold,(int)noise);
            uint32_t active=pet_turn_current();
            /* AEC only excludes self-echo: TV and other people also pass it.
             * Speech alone must not invalidate an audible/preparing answer. */
            current.overlap=playing;
            current.deferred=playing || atomic_load(&s_reply_generation)==active;
            current.generation=current.deferred?active:pet_turn_next();
            if(!current.deferred)pet_audio_stop();
            ESP_LOGI(TAG,"capture turn=%lu deferred=%d overlap=%d",(unsigned long)current.generation,current.deferred,current.overlap);
            pet_capture_discard();
            current.pcm = pet_alloc(MAX_SAMPLES * sizeof(int16_t));
            if (!current.pcm) { ESP_LOGE(TAG, "utterance buffer unavailable"); continue; }
            current.samples = FRAME * PRE_FRAMES;
            for (int i = 0; i < PRE_FRAMES; i++) {
                memcpy(current.pcm + i * FRAME, pre + ((pre_index + i) % PRE_FRAMES) * FRAME, FRAME * sizeof(int16_t));
            }
            atomic_store(&s_listening, !current.overlap);
            quiet_frames = 0; last_voice_sample = current.samples;
        }
        memcpy(pre + pre_index * FRAME, clean, FRAME * sizeof(int16_t));
        pre_index = (pre_index + 1) % PRE_FRAMES;
        if (!current.pcm) continue;
        if(!pet_turn_valid(current.generation)) {
            free(current.pcm);current=(pet_utterance_t){0};voice_frames=quiet_frames=0;
            atomic_store(&s_listening,false);atomic_store(&s_recorded_samples,0);continue;
        }
        /* Also protect an answer that starts playing after this candidate
         * began during preparation. Explicit touch/UI cancellation still wins. */
        if(current.deferred && playing) {
            current.overlap=true;atomic_store(&s_listening,false);
        }
        if (current.samples + FRAME <= MAX_SAMPLES) {
            memcpy(current.pcm + current.samples, clean, FRAME * sizeof(int16_t)); current.samples += FRAME;
        } else if (voice) current.too_long = true;
        if (voice) { quiet_frames = 0; last_voice_sample = current.samples; current.last_voice_us = esp_timer_get_time(); }
        else quiet_frames++;
        atomic_store(&s_recorded_samples, last_voice_sample - FRAME * PRE_FRAMES);
        if (current.too_long || quiet_frames >= END_SILENCE_FRAMES) {
            /* Retain a short natural tail, rather than uploading the entire
             * end-of-turn wait or counting it as the owner's spoken duration. */
            int trimmed = last_voice_sample + FRAME * KEEP_TAIL_FRAMES;
            if (current.samples > trimmed) current.samples = trimmed;
            /* Release unused recording capacity before model/TLS processing.
             * Failed shrinking leaves the original valid recording intact. */
            int16_t *compact = heap_caps_realloc(current.pcm, current.samples * sizeof(int16_t),
                                                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            if (compact) current.pcm = compact;
            atomic_store(&s_listening, false);
            atomic_store(&s_recorded_samples, 0);
            current.captured_us = esp_timer_get_time();
            pet_capture_discard();
            if (xQueueSend(s_queue, &current, 0) != pdTRUE) free(current.pcm);
            current = (pet_utterance_t){0}; voice_frames = 0;
        }
    }
}

int pet_capture_start(void)
{
    if (s_queue) return 0;
#ifdef CONFIG_DESKPET_WAKE
    if(!pet_wake_init())ESP_LOGE(TAG,"offline wake unavailable; touch can still open conversation");
#endif
    s_aec = aec_create(PET_SAMPLE_RATE, 4, 1, AEC_MODE_FD_LOW_COST);
    if (!s_aec || aec_get_chunksize(s_aec) != FRAME) return -1;
    s_vad = vad_create(VAD_MODE_1);
    if (!s_vad) return -1;
    s_reference = pet_alloc(REF_SAMPLES * sizeof(int16_t));
    s_queue = xQueueCreate(1, sizeof(pet_utterance_t));
    if (!s_reference || !s_queue) return -1;
    return xTaskCreatePinnedToCore(capture, "pet_capture", 8192, NULL, 8, NULL, 1) == pdPASS ? 0 : -1;
}
