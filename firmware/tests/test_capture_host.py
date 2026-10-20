"""Replay input frames through the real capture task and end-of-turn logic."""
import unittest
import test_runtime_core

SDK = r'''
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned TickType_t;
typedef void *QueueHandle_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_SPIRAM 2
#define MALLOC_CAP_8BIT 4
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define AEC_MODE_FD_LOW_COST 0
#define VAD_MODE_1 1
#define VAD_SPEECH 1
typedef int aec_handle_t;
typedef void *vad_handle_t;
static int shrink_fail, shrink_calls, aec_divisor=1;
static size_t shrink_size;
static inline void *heap_caps_realloc(void *p,size_t n,int caps) {shrink_calls++;shrink_size=n;return shrink_fail ? NULL : realloc(p,n);}
static inline void *heap_caps_malloc(size_t n,int caps) {return malloc(n);}
static inline void *heap_caps_aligned_alloc(size_t a,size_t n,int caps) {return malloc(n);}
static inline aec_handle_t *aec_create(int rate,int a,int b,int c) {return (aec_handle_t *)1;}
static inline int aec_get_chunksize(aec_handle_t *a) {return 512;}
static inline void aec_process(aec_handle_t *a,int16_t *mic,int16_t *ref,int16_t *clean) {for(int i=0;i<512;i++)clean[i]=mic[i]/aec_divisor;}
static inline vad_handle_t vad_create(int mode) {return (void *)1;}
int vad_process(vad_handle_t,const int16_t *,int,int);
QueueHandle_t xQueueCreate(int,int);
int xQueueReceive(QueueHandle_t,void *,TickType_t);
int xQueuePeek(QueueHandle_t,void *,TickType_t);
int xQueueSend(QueueHandle_t,const void *,TickType_t);
int xTaskCreatePinnedToCore(void (*)(void *),const char *,unsigned,void *,unsigned,void *,int);
void vTaskDelay(TickType_t);
int64_t esp_timer_get_time(void);
'''


class CaptureHostTests(unittest.TestCase):
    def test_environment_double_talk_does_not_stop_reply_or_show_listening(self):
        headers={'capture_test_sdk.h':SDK,'sdkconfig.h':''}
        for name in ['esp_aec.h','esp_vad.h','esp_heap_caps.h','esp_log.h','esp_timer.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "capture_test_sdk.h"\n'
        code=r'''
#include <setjmp.h>
#include "pet_capture.c"
static int frame=-1,stops;static uint32_t speaking;
static bool playback=true;
static jmp_buf ended;static pet_utterance_t result;
int pet_audio_read_frame(int16_t*p,int n){
 frame++;assert(frame<150&&pet_turn_valid(speaking)&&!pet_capture_listening());
 aec_divisor=frame>=30&&frame<60?1:10;
 for(int i=0;i<n;i++)p[i]=2000;
 int16_t ref[512];for(int i=0;i<512;i++)ref[i]=1000;pet_capture_reference(ref,512,false);
 return 0;
}
bool pet_audio_wake_ack(uint32_t g){return true;}
bool pet_audio_playing(void){return playback;}
void pet_audio_stop(void){stops++;}
int vad_process(vad_handle_t v,const int16_t*p,int r,int ms){return frame>=30&&frame<60?VAD_SPEECH:0;}
QueueHandle_t xQueueCreate(int n,int z){return (void*)1;}
int xQueuePeek(QueueHandle_t q,void*p,TickType_t t){*(pet_utterance_t*)p=result;return result.pcm?pdTRUE:pdFALSE;}
int xQueueReceive(QueueHandle_t q,void*p,TickType_t t){return pdFALSE;}
int xQueueSend(QueueHandle_t q,const void*p,TickType_t t){
 result=*(pet_utterance_t*)p;assert(frame==109&&result.overlap&&result.deferred&&result.generation==speaking);
 assert(!stops&&pet_turn_valid(speaking)&&!pet_capture_pending());longjmp(ended,1);return pdTRUE;
}
int xTaskCreatePinnedToCore(void(*f)(void*),const char*n,unsigned z,void*a,unsigned p,void*h,int c){return pdPASS;}
void vTaskDelay(TickType_t t){}
int64_t esp_timer_get_time(void){return (int64_t)frame*32000;}
int main(void){
 speaking=pet_turn_current();assert(!pet_capture_start());if(!setjmp(ended))capture(0);
 /* The audio generation stays valid throughout playback; worker claims later. */
 assert(!stops&&pet_turn_valid(speaking));assert(!pet_capture_claim(&result)&&pet_turn_valid(speaking));
 playback=false;assert(pet_capture_claim(&result));
 assert(result.overlap&&!result.deferred&&!pet_turn_valid(speaking));free(result.pcm);return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_util','pet_turn','pet_bargein','pet_wake_gate','pet_wake'],headers)

    def test_music_like_speech_does_not_record_until_offline_wake(self):
        headers={'capture_test_sdk.h':SDK,'sdkconfig.h':''}
        for name in ['esp_aec.h','esp_vad.h','esp_heap_caps.h','esp_log.h','esp_timer.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "capture_test_sdk.h"\n'
        code=r'''
#include <setjmp.h>
#include "pet_capture.c"
static int frame=-1,detector_calls,voice_starts;
static jmp_buf ended;static pet_utterance_t result;
bool pet_wake_init(void){return true;}
bool pet_wake_ready(void){return true;}
void pet_wake_reset(void){}
bool pet_wake_feed(const int16_t*p,size_t n){assert(!pet_capture_listening());detector_calls++;return frame==100;}
int pet_audio_read_frame(int16_t*p,int n){
 frame++;assert(frame<250);if(frame<=100)assert(!voice_starts&&!pet_capture_listening());
 for(int i=0;i<n;i++)p[i]=frame<180?2000:0;return 0;
}
bool pet_audio_wake_ack(uint32_t g){assert(pet_turn_valid(g));return true;}
bool pet_audio_playing(void){return false;}
void pet_audio_stop(void){assert(frame>100);voice_starts++;}
int vad_process(vad_handle_t v,const int16_t*p,int rate,int ms){return frame<180?VAD_SPEECH:0;}
QueueHandle_t xQueueCreate(int n,int z){return (void*)1;}
int xQueuePeek(QueueHandle_t q,void*p,TickType_t t){return pdFALSE;}
int xQueueReceive(QueueHandle_t q,void*p,TickType_t t){return pdFALSE;}
int xQueueSend(QueueHandle_t q,const void*p,TickType_t t){result=*(pet_utterance_t*)p;assert(frame==229);longjmp(ended,1);return pdTRUE;}
int xTaskCreatePinnedToCore(void(*f)(void*),const char*n,unsigned z,void*a,unsigned p,void*h,int c){return pdPASS;}
void vTaskDelay(TickType_t t){}
int64_t esp_timer_get_time(void){return (int64_t)frame*32000;}
int main(void){
 pet_wake_require(true);assert(!pet_capture_start());if(!setjmp(ended))capture(0);
 assert(detector_calls==101&&voice_starts==1&&result.samples<100*512);
 assert(result.last_voice_us>0&&result.captured_us-result.last_voice_us>=1500000);
 free(result.pcm);return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_util','pet_turn','pet_bargein','pet_wake_gate'],headers)

    def test_new_onset_during_reply_preparation_does_not_cancel_pending_answer(self):
        headers={'capture_test_sdk.h':SDK,'sdkconfig.h':''}
        for name in ['esp_aec.h','esp_vad.h','esp_heap_caps.h','esp_log.h','esp_timer.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "capture_test_sdk.h"\n'
        code=r'''
#include <setjmp.h>
#include "pet_capture.c"
static int frame=-1,stops;static uint32_t preparing;
static jmp_buf ended;static pet_utterance_t result;
int pet_audio_read_frame(int16_t*p,int n){
 frame++;assert(frame<120&&pet_turn_valid(preparing));
 for(int i=0;i<n;i++)p[i]=frame>=7&&frame<31?500:0;
 return 0;
}
bool pet_audio_wake_ack(uint32_t g){return true;}
bool pet_audio_playing(void){return false;}
void pet_audio_stop(void){stops++;}
int vad_process(vad_handle_t v,const int16_t*p,int r,int ms){return frame>=7&&frame<31?VAD_SPEECH:0;}
QueueHandle_t xQueueCreate(int n,int z){return (void*)1;}
int xQueuePeek(QueueHandle_t q,void*p,TickType_t t){return pdFALSE;}
int xQueueReceive(QueueHandle_t q,void*p,TickType_t t){return pdFALSE;}
int xQueueSend(QueueHandle_t q,const void*p,TickType_t t){
 result=*(pet_utterance_t*)p;assert(frame==80&&result.deferred&&result.generation==preparing);
 assert(pet_turn_valid(preparing)&&stops==0);longjmp(ended,1);return pdTRUE;
}
int xTaskCreatePinnedToCore(void(*f)(void*),const char*n,unsigned z,void*a,unsigned p,void*h,int c){return pdPASS;}
void vTaskDelay(TickType_t t){}
int64_t esp_timer_get_time(void){return (int64_t)frame*32000;}
int main(void){
 preparing=pet_turn_current();pet_capture_reply_pending(true,preparing);
 assert(!pet_capture_start());if(!setjmp(ended))capture(0);
 /* The worker claims the queued recording only after finishing its reply. */
 pet_capture_reply_pending(false,0);assert(pet_capture_claim(&result));
 assert(!result.deferred&&!pet_turn_valid(preparing)&&pet_turn_valid(result.generation));
 free(result.pcm);
 pet_utterance_t stale={.generation=pet_turn_current(),.deferred=true};
 uint32_t newer=pet_turn_next();assert(!pet_capture_claim(&stale)&&pet_turn_valid(newer));
 return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_util','pet_turn','pet_bargein','pet_wake_gate','pet_wake'],headers)

    def test_short_pause_keeps_sentence_and_long_pause_closes_with_trimmed_tail(self):
        headers = {'capture_test_sdk.h': SDK}
        headers['sdkconfig.h']=''
        for name in ['esp_aec.h', 'esp_vad.h', 'esp_heap_caps.h', 'esp_log.h',
                     'esp_timer.h', 'freertos/FreeRTOS.h', 'freertos/queue.h', 'freertos/task.h']:
            headers[name] = '#include "capture_test_sdk.h"\n'
        code = r'''
#include <setjmp.h>
#include "pet_capture.c"
static int frame=-1, stopped, delivered, scenario;
static bool consume;
static uint32_t paused_generation;
static jmp_buf finished;
static pet_utterance_t result;
static bool speech_now(void) {return scenario==1 ? frame>=7 : (scenario==2 || scenario==3) ? frame>=7 && frame<60 : (frame>=7 && frame<40) || (frame>=65 && frame<126);}
int pet_audio_read_frame(int16_t *stereo,int n) {
    frame++;assert(frame<700);
    if(scenario==2 && frame==0) {paused_generation=pet_turn_current();pet_capture_pause_turns(true);}
    if(scenario==2 && frame==20) {
        assert(!pet_capture_listening() && stopped==0 && paused_generation==pet_turn_current());
        pet_capture_pause_turns(false);
    }
    if(!scenario && frame==10)assert(pet_capture_listening() && !pet_capture_pending() && delivered==0);
    if(!scenario && frame==65)assert(delivered==0 && pet_capture_listening());
    for(int i=0;i<n;i++)stereo[i]=speech_now() ? (scenario==3?150:2000) : 0;
    return 0;
}
bool pet_audio_wake_ack(uint32_t g){return true;}
bool pet_audio_playing(void) {return false;}
void pet_audio_stop(void) {stopped++;}
int vad_process(vad_handle_t v,const int16_t *p,int r,int ms) {return speech_now() ? VAD_SPEECH : 0;}
QueueHandle_t xQueueCreate(int n,int size) {return (void *)1;}
int xQueueReceive(QueueHandle_t q,void *p,TickType_t t) {
    if(!consume || !delivered)return pdFALSE;
    *(pet_utterance_t *)p=result;delivered=0;return pdTRUE;
}
int xQueuePeek(QueueHandle_t q,void *p,TickType_t t) {
    if(!delivered)return pdFALSE;
    *(pet_utterance_t *)p=result;return pdTRUE;
}
int xQueueSend(QueueHandle_t q,const void *p,TickType_t t) {
    result=*(const pet_utterance_t *)p;delivered++;
    assert(frame==(scenario==1 ? 626 : (scenario==2 || scenario==3) ? 109 : 175) && !pet_capture_listening() && pet_capture_recorded_ms()==0);
    longjmp(finished,1);return pdTRUE;
}
int xTaskCreatePinnedToCore(void (*f)(void *),const char *n,unsigned z,void *a,unsigned p,void *h,int c) {return pdPASS;}
void vTaskDelay(TickType_t t) {}
int64_t esp_timer_get_time(void) {return (int64_t)frame*32000;}
int main(void) {
    assert(pet_capture_start()==0);
    if(setjmp(finished)==0)capture(NULL);
    assert(delivered==1 && stopped==1 && !result.too_long);
    /* One utterance includes the 0.8-second internal pause, but only keeps
       0.192 seconds of the final 1.6-second silence. */
    assert(result.samples==131*512 && pet_turn_valid(result.generation));
    assert(shrink_calls==1 && shrink_size==result.samples*sizeof(int16_t));
    assert(result.pcm[20*512]==2000 && result.pcm[result.samples-1]==0);
    assert(pet_capture_pending());
    pet_turn_next();assert(!pet_capture_pending()); /* cancelled recording cannot keep "thinking" */
    free(result.pcm);
    pet_wake_require(true);pet_wake_open(0);
    scenario=1;frame=-1;delivered=stopped=0;
    if(setjmp(finished)==0)capture(NULL);
    assert(delivered==1 && stopped==1 && result.too_long && result.samples==MAX_SAMPLES);
    free(result.pcm);
    scenario=2;frame=-1;delivered=stopped=0;shrink_fail=1;aec_divisor=4;
    if(setjmp(finished)==0)capture(NULL);
    assert(delivered==1 && stopped==1 && !result.too_long && result.samples==52*512);
    assert(shrink_calls==3 && result.pcm[20*512]==2000 && result.pcm[result.samples-1]==0);
    assert(pet_capture_pending());consume=true;pet_utterance_t taken={0};
    assert(pet_capture_take(&taken,0) && taken.pcm==result.pcm && !pet_capture_pending());
    free(taken.pcm);
    /* Soft speech above room noise must not be absorbed into the noise floor. */
    scenario=3;frame=-1;delivered=stopped=0;consume=false;aec_divisor=1;
    if(setjmp(finished)==0)capture(NULL);
    assert(result.samples==65*512 && result.pcm[20*512]==150);free(result.pcm);
    return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self, code, ['pet_util', 'pet_turn', 'pet_bargein','pet_wake_gate','pet_wake'], headers)
