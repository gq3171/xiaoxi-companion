#include "pet_audio.h"
#ifdef ESP_PLATFORM
#include "pet_tts.h"
#include "pet_runtime.h"
#endif

#include <assert.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>

#include "bsp/esp-bsp.h"
#include "esp_codec_dev.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
#include "pet_capture.h"
#include "pet_turn.h"
#include "pet_latency.h"
#include "pet_pcm_ring.h"
#include "pet_util.h"
#include "sdkconfig.h"
#endif

static const char *TAG = "pet_audio";
static esp_codec_dev_handle_t s_spk;
static esp_codec_dev_handle_t s_mic;
static atomic_bool s_stop;
static SemaphoreHandle_t s_volume_lock;
static int s_volume = PET_DEFAULT_VOLUME;
static atomic_bool s_output_allowed = true;
static atomic_bool s_playing;

static int load_volume(void)
{
    nvs_handle_t handle;
    uint8_t volume = PET_DEFAULT_VOLUME;
    if (nvs_open("pet", NVS_READONLY, &handle) == ESP_OK) {
        if (nvs_get_u8(handle, "volume", &volume) != ESP_OK || volume > 100) {
            volume = PET_DEFAULT_VOLUME;
        }
        nvs_close(handle);
    }
    return volume;
}

static void save_volume(int volume)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open("pet", NVS_READWRITE, &handle);
    if (err == ESP_OK) {
        err = nvs_set_u8(handle, "volume", (uint8_t)volume);
        if (err == ESP_OK) {
            err = nvs_commit(handle);
        }
        nvs_close(handle);
    }
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "cannot save volume: %s", esp_err_to_name(err));
    }
}

static int apply_volume(int volume)
{
    int err = esp_codec_dev_set_out_vol(s_spk, volume);
    if (err == ESP_CODEC_DEV_OK) {
        err = esp_codec_dev_set_out_mute(s_spk, volume == 0 || !atomic_load(&s_output_allowed));
    }
    return err;
}

void pet_audio_allow_output(bool allowed)
{
    atomic_store(&s_output_allowed, allowed);
    if (!allowed) s_stop = true;
    if (s_volume_lock && s_spk) {
        xSemaphoreTake(s_volume_lock, portMAX_DELAY);
        apply_volume(s_volume);
        xSemaphoreGive(s_volume_lock);
    }
}

bool pet_audio_output_allowed(void) { return atomic_load(&s_output_allowed); }
bool pet_audio_playing(void) { return atomic_load(&s_playing); }

int pet_audio_read_frame(int16_t *stereo, int samples)
{
    return esp_codec_dev_read(s_mic, stereo, samples * sizeof(int16_t));
}

int pet_audio_get_volume(void)
{
    if (!s_volume_lock) {
        return PET_DEFAULT_VOLUME;
    }
    xSemaphoreTake(s_volume_lock, portMAX_DELAY);
    int volume = s_volume;
    xSemaphoreGive(s_volume_lock);
    return volume;
}

int pet_audio_adjust_volume(int delta)
{
    if (!s_volume_lock || !s_spk) {
        return -1;
    }
    xSemaphoreTake(s_volume_lock, portMAX_DELAY);
    int volume = s_volume + delta;
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    if (volume != s_volume) {
        if (apply_volume(volume) != ESP_CODEC_DEV_OK) {
            ESP_LOGE(TAG, "cannot change speaker volume");
            xSemaphoreGive(s_volume_lock);
            return -1;
        }
        s_volume = volume;
        save_volume(volume);
    }
    xSemaphoreGive(s_volume_lock);
    return volume;
}

static int frame_energy(const int16_t *stereo, int frames)
{
    int64_t sum = 0;
    for (int i = 0; i < frames; i++) {
        int mixed = ((int)stereo[i * 2] + (int)stereo[i * 2 + 1]) / 2;
        sum += (int64_t)mixed * mixed;
    }
    return (int)sqrt((double)sum / frames);
}

void pet_audio_start(void)
{
    s_volume_lock = xSemaphoreCreateMutex();
    assert(s_volume_lock);
    s_volume = load_volume();
    esp_codec_dev_sample_info_t fs = {
        .sample_rate = PET_SAMPLE_RATE,
        .channel = 2,
        .bits_per_sample = 16,
    };
    s_spk = bsp_audio_codec_speaker_init();
    s_mic = bsp_audio_codec_microphone_init();
    assert(s_spk && s_mic);
    /* The codec opens at volume zero; set the saved/quiet level before any playback. */
    ESP_ERROR_CHECK(esp_codec_dev_open(s_spk, &fs));
    ESP_ERROR_CHECK(apply_volume(s_volume));
    ESP_ERROR_CHECK(esp_codec_dev_open(s_mic, &fs));
    /* ES7210's vendor default is 30 dB. Real owner clips at 24 dB were
     * below the quality floor without clipping; restore the input gain. */
    ESP_ERROR_CHECK(esp_codec_dev_set_in_gain(s_mic, 30.0));
    ESP_LOGI(TAG, "mic and speaker ready, volume %d%%", s_volume);
}

void pet_audio_stop(void)
{
    s_stop = true;
}

#ifndef PET_AUDIO_HOST_VOLUME_ONLY
static uint32_t s_stream_generation;
static size_t s_stream_samples;
static unsigned s_stream_prebuffer=PET_SAMPLE_RATE/2;
static pet_pcm_ring_t s_stream_ring;
static atomic_bool s_stream_active,s_stream_input_done,s_stream_worker_done=true,s_stream_aborted;
static bool s_stream_ready;
static portMUX_TYPE s_ack_lock=portMUX_INITIALIZER_UNLOCKED;
static bool s_ack_requested;
static uint32_t s_ack_generation;
static void play_wake_reply(uint32_t generation,int16_t *mono,int16_t *frame)
{
#ifdef ESP_PLATFORM
    pet_audio_allow_output(pet_runtime_audio_allowed());
#endif
#if defined(ESP_PLATFORM) && defined(CONFIG_DESKPET_WAKE)
    extern const unsigned char ack_start[] asm("_binary_wake_ack_pcm_start");
    extern const unsigned char ack_end[] asm("_binary_wake_ack_pcm_end");
    const unsigned char *data=ack_start;size_t samples=(ack_end-ack_start)/2;
    bool cached=pet_tts_ack_size()>0;if(cached)samples=pet_tts_ack_size();
#else
    /* Host codec shim: the actual PCM is validated by its asset manifest. */
    static const int16_t fixture[]={100,-100,50,-50};const unsigned char *data=(const unsigned char*)fixture;size_t samples=4;
#endif
    if(!pet_turn_valid(generation)||!pet_audio_output_allowed()||pet_audio_get_volume()==0)return;
    s_stop=false;size_t offset=0;
    ESP_LOGI(TAG,"local wake reply started");
    while(offset<samples&&!s_stop&&pet_turn_valid(generation)&&pet_audio_output_allowed()){
        size_t n=samples-offset;if(n>512)n=512;
        /* Embedded bytes need not be half-word aligned in the link map. */
#if defined(ESP_PLATFORM) && defined(CONFIG_DESKPET_WAKE)
        if(cached){if(pet_tts_ack_read(offset,mono,n)!=n)break;}
        else
#endif
        memcpy(mono,data+offset*sizeof(*mono),n*sizeof(*mono));
        for(size_t i=0;i<n;i++)frame[i*2]=frame[i*2+1]=mono[i];
        pet_capture_reference(mono,n,offset==0);atomic_store(&s_playing,true);
        if(esp_codec_dev_write(s_spk,frame,n*2*sizeof(int16_t))!=ESP_CODEC_DEV_OK)break;
        offset+=n;
    }
    atomic_store(&s_playing,false);
    ESP_LOGI(TAG,"local wake reply %s (%u/%u samples)",offset==samples?"complete":"interrupted",(unsigned)offset,(unsigned)samples);
}
static void stream_player(void *unused)
{
    int16_t mono[512],frame[1024];
    while(true){
        if(!atomic_load(&s_stream_active)){
            portENTER_CRITICAL(&s_ack_lock);bool pending=s_ack_requested;portEXIT_CRITICAL(&s_ack_lock);
            bool available=true;
            if(pending&&atomic_compare_exchange_strong(&s_stream_worker_done,&available,false)){
                portENTER_CRITICAL(&s_ack_lock);uint32_t g=s_ack_generation;s_ack_requested=false;portEXIT_CRITICAL(&s_ack_lock);
                play_wake_reply(g,mono,frame);atomic_store(&s_stream_worker_done,true);
            }
            vTaskDelay(pdMS_TO_TICKS(5));continue;
        }
        uint32_t generation=s_stream_generation;
        /* 0.5s jitter buffer; a short complete utterance can start immediately. */
        bool started=false;
        unsigned underruns=0;
        while(true){
            if(s_stop||atomic_load(&s_stream_aborted)||!pet_turn_valid(generation)||!pet_audio_output_allowed()){
                atomic_store(&s_stream_aborted,true);break;
            }
            unsigned used=pet_pcm_ring_used(&s_stream_ring);
            bool done=atomic_load(&s_stream_input_done);
            if(done&&!used)break;
            if(!started&&!done&&used<s_stream_prebuffer){vTaskDelay(pdMS_TO_TICKS(5));continue;}
            if(!used){underruns++;vTaskDelay(pdMS_TO_TICKS(5));continue;}
            if(used<512&&!done){vTaskDelay(pdMS_TO_TICKS(5));continue;}
            size_t count=pet_pcm_ring_pop(&s_stream_ring,mono,512);
            for(size_t i=0;i<count;i++)frame[i*2]=frame[i*2+1]=mono[i];
            pet_capture_reference(mono,count,s_stream_samples==0);
            atomic_store(&s_playing,true);
            if(esp_codec_dev_write(s_spk,frame,count*2*sizeof(int16_t))!=ESP_CODEC_DEV_OK){atomic_store(&s_stream_aborted,true);break;}
            if(!s_stream_samples)pet_latency_mark(generation,PET_TIME_SPEAKER);
            s_stream_samples+=count;started=true;
        }
        atomic_store(&s_playing,false);
        ESP_LOGI(TAG,"audio buffer empty waits=%u",underruns);
        atomic_store(&s_stream_active,false);atomic_store(&s_stream_worker_done,true);
    }
}
static bool stream_prepare(void)
{
    if(!s_volume_lock)return false;
    xSemaphoreTake(s_volume_lock,portMAX_DELAY);
    if(!s_stream_ready){
        int16_t *buffer=pet_alloc(32768*sizeof(int16_t));
        if(buffer){
            pet_pcm_ring_init(&s_stream_ring,buffer,32768);
            if(xTaskCreate(stream_player,"pet_pcm_player",6144,NULL,5,NULL)==pdPASS)s_stream_ready=true;
            else free(buffer);
        }
    }
    bool ready=s_stream_ready;xSemaphoreGive(s_volume_lock);return ready;
}
static bool stream_begin(uint32_t generation,unsigned prebuffer)
{
    if(!pet_turn_valid(generation)||!stream_prepare())return false;
    bool available=true;if(!atomic_compare_exchange_strong(&s_stream_worker_done,&available,false))return false;
    pet_pcm_ring_init(&s_stream_ring,s_stream_ring.data,32768);
    s_stream_generation=generation;s_stream_samples=0;s_stream_prebuffer=prebuffer;s_stop=false;
    atomic_store(&s_stream_aborted,false);atomic_store(&s_stream_input_done,false);
    atomic_store(&s_stream_worker_done,false);atomic_store(&s_stream_active,true);return true;
}
bool pet_audio_stream_begin(uint32_t generation){return stream_begin(generation,PET_SAMPLE_RATE/2);}
/* One video frame of initial audio, keeping preview picture/audio aligned.
 * TTS retains its existing half-second network jitter buffer. */
bool pet_audio_stream_begin_media(uint32_t generation){return stream_begin(generation,PET_SAMPLE_RATE/8);}
bool pet_audio_stream_write(const int16_t *mono,size_t samples,uint32_t generation)
{
    if(generation!=s_stream_generation||!mono||!samples||!atomic_load(&s_stream_active))return false;
    for(size_t offset=0;offset<samples;){
        if(s_stop||atomic_load(&s_stream_aborted)||!pet_turn_valid(generation)||!pet_audio_output_allowed())return false;
        size_t count=pet_pcm_ring_push(&s_stream_ring,mono+offset,samples-offset);offset+=count;
        if(!count)vTaskDelay(pdMS_TO_TICKS(5));
    }
    return true;
}
void pet_audio_stream_end(bool complete)
{
    if(!complete)atomic_store(&s_stream_aborted,true);
    atomic_store(&s_stream_input_done,true);
    while(!atomic_load(&s_stream_worker_done))vTaskDelay(pdMS_TO_TICKS(5));
    ESP_LOGI(TAG,"stream playback %s (%u samples)",complete&&!atomic_load(&s_stream_aborted)?"complete":"interrupted",(unsigned)s_stream_samples);
}
bool pet_audio_stream_ok(void){return !atomic_load(&s_stream_aborted);}
bool pet_audio_wake_ack(uint32_t generation)
{
    if(!pet_turn_valid(generation)||!pet_audio_output_allowed()||pet_audio_get_volume()==0||!stream_prepare())return false;
    portENTER_CRITICAL(&s_ack_lock);s_ack_generation=generation;s_ack_requested=true;portEXIT_CRITICAL(&s_ack_lock);
    return true;
}
#endif

int pet_audio_listen(int16_t *mono, size_t max_samples)
{
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
    if (pet_capture_started()) {
        pet_utterance_t utterance;
        while (pet_capture_take(&utterance, portMAX_DELAY)) {
            if (utterance.too_long || (size_t)utterance.samples > max_samples) { free(utterance.pcm); return 0; }
            if (!pet_turn_valid(utterance.generation)) { free(utterance.pcm); continue; }
            memcpy(mono, utterance.pcm, utterance.samples * sizeof(int16_t));
            free(utterance.pcm);
            return utterance.samples;
        }
        return 0;
    }
#endif
    int16_t frame[640];
    size_t stored = 0;
    int heard = 0;
    int quiet_frames = 0;
    s_stop = false;

    while (stored + 320 <= max_samples && !s_stop) {
        if (esp_codec_dev_read(s_mic, frame, sizeof(frame)) != ESP_OK) {
            break;
        }
        int energy = frame_energy(frame, 320);
        if (!heard) {
            if (energy < 900) {
                continue;
            }
            heard = 1;
        }
        for (int i = 0; i < 320 && stored < max_samples; i++) {
            mono[stored++] = (int16_t)(((int)frame[i * 2] + (int)frame[i * 2 + 1]) / 2);
        }
        if (energy < 500) {
            quiet_frames++;
            if (quiet_frames > 25) {
                break;
            }
        } else {
            quiet_frames = 0;
        }
    }
    return (int)stored;
}

void pet_audio_play(const int16_t *mono, size_t samples)
{
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
    pet_audio_play_turn(mono, samples, pet_turn_current());
}

int pet_audio_play_turn(const int16_t *mono, size_t samples, uint32_t generation)
{
#endif
    int16_t frame[1024];
    size_t offset = 0;
    s_stop = false;
    atomic_store(&s_playing, true);
    while (offset < samples && !s_stop && pet_audio_output_allowed()) {
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
        if (!pet_turn_valid(generation)) break;
#endif
        size_t count = samples - offset;
        if (count > 512) {
            count = 512;
        }
        for (size_t i = 0; i < count; i++) {
            frame[i * 2] = mono[offset + i];
            frame[i * 2 + 1] = mono[offset + i];
        }
        memset(frame + count * 2, 0, (512 - count) * 2 * sizeof(int16_t));
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
        pet_capture_reference(mono + offset, count, offset == 0);
#endif
        if (esp_codec_dev_write(s_spk, frame, sizeof(frame)) != ESP_CODEC_DEV_OK) break;
        offset += count;
    }
    atomic_store(&s_playing, false);
#ifndef PET_AUDIO_HOST_VOLUME_ONLY
    ESP_LOGI(TAG, "playback %s (%u/%u samples)", offset == samples ? "complete" : "interrupted", (unsigned)offset, (unsigned)samples);
    return offset == samples ? 0 : -1;
#endif
}
